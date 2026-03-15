"""Scrape careers pages and extract structured job listings using ScrapeGraphAI + Ollama.

ScrapeGraphAI combines web scraping and LLM-based extraction into a single step,
so there is no need for a separate reader service or manual LLM extraction call.
Everything runs locally via Ollama — zero external API costs.

The scraping pipeline has two extraction strategies:
1. **Direct HTML parsing** — structured career sites (e.g. Phenom People) embed job
   data in ``data-`` attributes.  When detected, jobs are parsed directly from the DOM
   without any LLM call.  This is faster and captures every listing reliably.
2. **LLM extraction** — for unstructured pages, the rendered HTML is cleaned (scripts,
   styles, nav, etc. stripped) and sent to ScrapeGraphAI page-by-page.

Both strategies benefit from Playwright pagination: the renderer automatically clicks
through "Next" / "Load More" buttons so all pages of results are captured.
"""

import asyncio
import contextlib
import io
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import warnings

# Silence noisy Pydantic v1 + Python 3.14 deprecation warnings from langchain_core.
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    module="langchain_core._api.deprecation",
)

from bs4 import BeautifulSoup, Tag
from playwright.async_api import async_playwright, Page
from scrapegraphai.graphs import SmartScraperGraph

from targetfit.ingestion.url_builder import resolve_search_url
from targetfit.log import setup_logger
from targetfit.models import SearchTerms


logger = setup_logger(__name__)


class ScrapingError(Exception):
    """Raised when a ScrapeGraphAI scrape fails."""


# ── Playwright renderer ─────────────────────────────────────────────────────

# Selectors that commonly represent "next page" or "load more" controls on
# career sites.  Tried in order; the first visible & enabled match wins.
_NEXT_SELECTORS = [
    # Phenom People (Roche, many pharma/tech companies)
    '[data-ph-at-id="pagination-next-link"]',
    # Generic patterns
    'a.next-btn', 'button.next-btn',
    'a[aria-label="Next"]', 'button[aria-label="Next"]',
    'a[aria-label="Next page"]', 'button[aria-label="Next page"]',
    'a:has-text("Next")', 'button:has-text("Next")',
]

_LOAD_MORE_SELECTORS = [
    'button:has-text("Load more")', 'button:has-text("Show more")',
    'a:has-text("Load more")', 'a:has-text("Show more")',
    'button:has-text("View more")', 'a:has-text("View more")',
    '[data-ph-at-id="load-more"]',
]


async def _try_click(page: Page, selectors: list[str], timeout: int = 5000) -> bool:
    """Click the first visible & enabled element matching *selectors*. Return True on success."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible() and await loc.is_enabled():
                await loc.click(timeout=timeout)
                return True
        except Exception:
            continue
    return False


# Common cookie-consent / overlay dismiss selectors.
_COOKIE_DISMISS_SELECTORS = [
    # OneTrust (Roche, many large companies)
    '#onetrust-accept-btn-handler',
    '#onetrust-reject-all-handler',
    '.onetrust-close-btn-handler',
    # Cookiebot
    '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
    '#CybotCookiebotDialogBodyButtonAccept',
    # Generic patterns
    'button:has-text("Accept all")',
    'button:has-text("Accept cookies")',
    'button:has-text("Accept All")',
    'button:has-text("I agree")',
    'button:has-text("Got it")',
    'a:has-text("Accept all")',
]


async def _dismiss_overlays(page: Page) -> None:
    """Try to dismiss cookie consent banners and other overlays that block clicks."""
    for sel in _COOKIE_DISMISS_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible():
                await loc.click(timeout=3000)
                await page.wait_for_timeout(500)
                logger.debug("Dismissed overlay via %s", sel)
                return
        except Exception:
            continue

    # Fallback: remove any overlay elements via JS (OneTrust dark filter, etc.)
    try:
        await page.evaluate("""() => {
            for (const sel of ['#onetrust-consent-sdk', '.onetrust-pc-dark-filter',
                               '#CybotCookiebotDialog', '.cookie-banner', '.cookie-consent']) {
                const el = document.querySelector(sel);
                if (el) el.remove();
            }
        }""")
    except Exception:
        pass


_SEARCH_INPUT_SELECTORS = [
    'input[type="search"]',
    'input[placeholder*="search" i]',
    'input[placeholder*="Search" i]',
    'input[placeholder*="job" i]',
    'input[placeholder*="keyword" i]',
    'input[aria-label*="search" i]',
    'input[name*="search" i]',
    'input[name*="keyword" i]',
    'input[id*="search" i]',
    '#searchKeywords',
    '.search-input',
]

_SEARCH_SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'button:has-text("Search")',
    'input[type="submit"]',
    '[aria-label*="search" i][role="button"]',
]


async def _search_via_form(page: Page, query: str, wait_ms: int = 3000) -> bool:
    """Find a search input, type the query, and submit. Return True if found."""
    for sel in _SEARCH_INPUT_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible():
                await loc.fill(query)
                await page.wait_for_timeout(300)
                # Try clicking a submit button, fall back to pressing Enter.
                submitted = False
                for ssub in _SEARCH_SUBMIT_SELECTORS:
                    try:
                        btn = page.locator(ssub).first
                        if await btn.count() and await btn.is_visible():
                            await btn.click()
                            submitted = True
                            break
                    except Exception:
                        continue
                if not submitted:
                    await loc.press("Enter")
                try:
                    await page.wait_for_load_state("networkidle", timeout=wait_ms)
                except Exception:
                    await page.wait_for_timeout(wait_ms)
                logger.debug("Search via form submitted: %r", query)
                return True
        except Exception:
            continue
    return False


async def _scroll_to_load(page: Page, max_scrolls: int = 6, pause_ms: int = 1000) -> None:
    """Scroll to bottom repeatedly to trigger lazy-loading / infinite-scroll."""
    try:
        prev = await page.evaluate("() => document.body.scrollHeight")
        for _ in range(max_scrolls):
            await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(pause_ms)
            cur = await page.evaluate("() => document.body.scrollHeight")
            if cur == prev:
                break
            prev = cur
    except Exception:
        pass


async def _render_all_pages(
    url: str,
    extra_wait_ms: int = 3000,
    max_pages: int = 50,
    page_wait_ms: int = 2000,
    search_query: str | None = None,
) -> list[str]:
    """Return rendered HTML for every page of results.

    Strategy:
    1. Load the URL; wait for network idle + extra delay.
    2. If ``search_query`` is given AND the URL is a landing page (url_builder
       returned None), attempt to find and fill a search form.
    3. Try "Load More" buttons first (some sites expand in-place).
    4. Then try "Next" pagination buttons, collecting HTML per page.
    5. Scroll each page to trigger lazy-loaded content.

    Returns a list of HTML strings, one per page visited.
    """
    pages_html: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=45000)
        await page.wait_for_timeout(extra_wait_ms)

        # Dismiss cookie banners / overlays that would block pagination clicks.
        await _dismiss_overlays(page)

        # If no search URL could be built, try to fill the on-page search form.
        if search_query:
            found = await _search_via_form(page, search_query)
            if found:
                await page.wait_for_timeout(extra_wait_ms)
                logger.info("Playwright form search for %r succeeded", search_query)
            else:
                logger.info("No search form found — scraping landing page directly")

        # Phase 1: expand in-place with "Load More" buttons.
        for _ in range(max_pages):
            await _scroll_to_load(page)
            if not await _try_click(page, _LOAD_MORE_SELECTORS):
                break
            await page.wait_for_timeout(page_wait_ms)

        # Capture page 1 (may already contain all expanded results).
        await _scroll_to_load(page)
        pages_html.append(await page.content())

        # Phase 2: paginate with "Next" buttons.
        for pg in range(2, max_pages + 1):
            if not await _try_click(page, _NEXT_SELECTORS):
                break
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                await page.wait_for_timeout(page_wait_ms)
            await page.wait_for_timeout(page_wait_ms)
            await _scroll_to_load(page)
            pages_html.append(await page.content())
            logger.debug("Captured page %d", pg)

        await browser.close()

    logger.info("Playwright captured %d page(s) from %s", len(pages_html), url)
    return pages_html


def fetch_rendered_html(url: str, extra_wait_ms: int = 3000,
                        search_query: str | None = None) -> str:
    """Sync wrapper — fetch fully-rendered HTML from *url* using Playwright (single page)."""
    pages = asyncio.run(
        _render_all_pages(url, extra_wait_ms=extra_wait_ms, max_pages=1,
                          search_query=search_query)
    )
    return pages[0] if pages else ""


def fetch_all_pages(url: str, extra_wait_ms: int = 3000, max_pages: int = 50,
                    search_query: str | None = None) -> list[str]:
    """Sync wrapper — fetch rendered HTML for every page of results."""
    return asyncio.run(
        _render_all_pages(url, extra_wait_ms=extra_wait_ms, max_pages=max_pages,
                          search_query=search_query)
    )


# ── Direct HTML extraction (structured career sites) ────────────────────────

def _extract_jobs_from_data_attrs(html: str) -> list[dict]:
    """Try to extract jobs directly from data attributes in the HTML.

    Many career platforms (Phenom People, Workday, etc.) embed structured
    data in ``data-ph-at-*`` or similar attributes on job-link elements.
    This is far more reliable than LLM extraction for these sites.
    """
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict] = []

    # Phenom People pattern: <a data-ph-at-job-title-text="..." ...>
    for link in soup.select("a[data-ph-at-job-title-text]"):
        title = link.get("data-ph-at-job-title-text", "").strip()
        if not title:
            continue

        location = link.get("data-ph-at-job-location-text", "").strip() or None
        href = link.get("href", "").strip() or None
        date_raw = link.get("data-ph-at-job-post-date-text", "").strip()

        date_posted = None
        if date_raw:
            # Normalise "2026-03-02T00:00:00.000+0000" → "2026-03-02"
            m = re.match(r"(\d{4}-\d{2}-\d{2})", date_raw)
            if m:
                date_posted = m.group(1)

        # Grab any visible description text inside the job card.
        card = link.find_parent("li") or link.parent
        desc_el = card.find(class_=re.compile(r"desc|snippet|summary", re.I)) if card else None
        description = desc_el.get_text(strip=True)[:1000] if desc_el else None

        jobs.append({
            "title": title,
            "location": location,
            "url": href,
            "date_posted": date_posted,
            "description": description,
        })

    return jobs


# ── HTML cleaning for LLM extraction ────────────────────────────────────────

_STRIP_TAGS = {"script", "style", "noscript", "svg", "img", "video", "audio",
               "iframe", "nav", "footer", "header"}


def _clean_html(html: str) -> str:
    """Strip non-content elements to reduce HTML size before LLM extraction."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove noisy elements.
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    # Remove hidden elements.
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.I)):
        tag.decompose()

    # Remove comments.
    from bs4 import Comment
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    return str(soup)


# ── ScrapeGraphAI configuration ────────────────────────────────────────────

def _build_graph_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Build the ScrapeGraphAI graph_config dict from our config.yaml values."""
    ollama_url = config.get("ollama_url", "http://localhost:11434")
    # Prefer a dedicated extraction model if configured, otherwise fall back to legacy 'model'.
    model = config.get("extraction_model") or config.get("model", "gemma3:27b")
    embedding_model = config.get("embedding_model", "nomic-embed-text")
    headless = config.get("headless", True)
    llm_max_tokens = int(config.get("llm_max_tokens", 8192))

    logger.debug(
        "ScrapeGraphAI config: model=%s, embedding_model=%s, headless=%s, llm_max_tokens=%d",
        model,
        embedding_model,
        headless,
        llm_max_tokens,
    )

    return {
        "llm": {
            "model": f"ollama/{model}",
            "temperature": 0,
            "format": "json",
            "base_url": ollama_url,
            # Help ScrapeGraphAI know the context window size for this model.
            "model_tokens": llm_max_tokens,
        },
        "embeddings": {
            "model": f"ollama/{embedding_model}",
            "base_url": ollama_url,
        },
        "verbose": False,
        "headless": headless,
    }


# ── Extraction prompt ──────────────────────────────────────────────────────

EXTRACT_PROMPT = """\
Extract ALL job listings visible on this page.

Return a JSON object with a single key "jobs" containing an array.
Each job object must have exactly these fields:
{
  "title": string,         // exact job title as written on the page
  "location": string,      // city, country or "Remote" — null if not found
  "url": string,           // direct link to the job posting — null if not found
  "date_posted": string,   // ISO date (YYYY-MM-DD) if available — null if not found
  "description": string    // short description or snippet — null if not found
}

Rules:
- Extract EVERY job listed. Do NOT skip any.
- Only extract jobs explicitly listed on the page. Do NOT invent jobs.
- If a field is missing, set it to null.
- If no jobs are found, return {"jobs": []}.
- Preserve original job titles exactly — do not rephrase or summarize.
"""


# ── Public API ──────────────────────────────────────────────────────────────

def _extract_with_llm(html: str, config: Dict[str, Any]) -> list[dict]:
    """Run ScrapeGraphAI LLM extraction on cleaned HTML. Returns raw job dicts."""
    cleaned = _clean_html(html)
    graph_config = _build_graph_config(config)
    scraper = SmartScraperGraph(
        prompt=EXTRACT_PROMPT,
        source=cleaned,
        config=graph_config,
    )

    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
        result = scraper.run()

    captured_output = "\n".join(
        part.strip()
        for part in (captured_stdout.getvalue(), captured_stderr.getvalue())
        if part.strip()
    )
    if captured_output:
        logger.debug("Suppressed ScrapeGraphAI console output (%d chars)", len(captured_output))

    if not result:
        return []
    raw = result if isinstance(result, list) else result.get("jobs", [])
    return raw if isinstance(raw, list) else []


def _dedup_jobs(jobs: list[dict]) -> list[dict]:
    """Remove duplicate jobs based on (title, url) pair."""
    seen: set[tuple] = set()
    unique: list[dict] = []
    for job in jobs:
        key = (job.get("title"), job.get("url"))
        if key not in seen:
            seen.add(key)
            unique.append(job)
    return unique


def scrape_and_extract(
    url: str,
    company: str,
    config: Dict[str, Any],
    *,
    query: str | None = None,
    search_url_template: str | None = None,
) -> List[Dict]:
    """Scrape a single careers page and return structured job dicts.

    Resolution order:
    0. **ATS API** — if the URL matches Greenhouse/Lever/Ashby/SmartRecruiters,
       fetch structured JSON directly (no Playwright, no LLM).
    1. ``search_url_template`` from companies.csv  (``{query}`` substituted).
    2. Auto-detected search URL from ``url_builder`` based on ATS pattern.
    3. Playwright form search: visit ``url``, type ``query`` into the search box.
    4. Fallback: scrape the landing page as-is.

    Extraction pipeline (for non-API paths):
    A. Playwright renders the resolved URL and paginates through all result pages.
    B. Try direct data-attribute extraction (fast, zero LLM cost).
    C. Fall back to ScrapeGraphAI LLM extraction on cleaned HTML per page.
    """
    # ── Strategy 0: ATS API (instant, structured, zero LLM cost) ────────
    from targetfit.ingestion.ats_api import fetch_via_api

    api_jobs = fetch_via_api(url, company, query=query)
    if api_jobs is not None:
        # API returned results (possibly empty list — still authoritative).
        logger.info("ATS API returned %d jobs for %s", len(api_jobs), company)
        return api_jobs

    logger.info("Scraping %s (%s)", company, url)

    # ── Resolve the actual URL to scrape ────────────────────────────────
    playwright_query: str | None = None  # set when we need Playwright form search
    location = config.get("location")

    if query:
        resolved = resolve_search_url(url, query, search_url_template, location=location)
        if resolved:
            scrape_url = resolved
            logger.info("Search URL for %s: %s", company, scrape_url)
        else:
            # url_builder couldn't build a URL — use Playwright form interaction
            scrape_url = url
            playwright_query = query
            logger.info(
                "No search URL pattern for %s — will try Playwright form search with %r",
                company, query,
            )
    else:
        scrape_url = url

    try:
        logger.info("Rendering pages with Playwright: %s", scrape_url)
        html_pages = fetch_all_pages(scrape_url, search_query=playwright_query)
    except Exception as exc:
        raise ScrapingError(f"Playwright render failed for {company} ({scrape_url}): {exc}") from exc

    # Strategy 1: direct extraction from structured data attributes.
    all_raw: list[dict] = []
    for page_html in html_pages:
        all_raw.extend(_extract_jobs_from_data_attrs(page_html))

    if all_raw:
        logger.info(
            "Direct HTML extraction found %d jobs across %d page(s) for %s",
            len(all_raw), len(html_pages), company,
        )
    else:
        # Strategy 2: LLM extraction on each page's cleaned HTML.
        logger.info("No structured data attributes found — falling back to LLM extraction for %s", company)
        for i, page_html in enumerate(html_pages, 1):
            try:
                page_jobs = _extract_with_llm(page_html, config)
                logger.debug("LLM extracted %d jobs from page %d for %s", len(page_jobs), i, company)
                all_raw.extend(page_jobs)
            except Exception as exc:
                logger.warning("LLM extraction failed on page %d for %s: %s", i, company, exc)

    if not all_raw:
        logger.warning("No jobs extracted for %s", company)
        return []

    # Normalise and deduplicate.
    all_raw = _dedup_jobs(all_raw)

    from pydantic import ValidationError

    from targetfit.models import Job

    jobs: List[Dict[str, Any]] = []
    for item in all_raw:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        if not title:
            continue
        try:
            jobs.append(Job(
                company=company,
                title=title,
                location=item.get("location"),
                url=item.get("url"),
                description=item.get("description"),
                date_posted=item.get("date_posted"),
            ).model_dump())
        except ValidationError:
            logger.debug("Skipping invalid job item: %s", title)
            continue

    logger.info("Extracted %d jobs for %s (%s)", len(jobs), company, url)
    return jobs


def fetch_all(
    companies: List[Dict[str, str]],
    config: Dict,
    search_terms: "SearchTerms | None" = None,
) -> List[Dict]:
    """Scrape + extract jobs for all companies in the list.

    When *search_terms* carries multiple queries, **every** query is tried
    for each company.  Results are deduplicated on (company, title, url)
    and merged into the per-company JSON file (never overwritten).

    Args:
        companies:    List of dicts with keys ``company``, ``url``,
                      and optional ``search_url`` (template from CSV).
        config:       Config dict from config.yaml.
        search_terms: SearchTerms extracted from the CV.  All ``queries``
                      are used (not just the first one).

    Returns a flat list of job dicts ready for saving / indexing.
    """
    from targetfit.storage.io import save_company_jobs

    # Build the list of queries to try.
    queries: list[str] = []
    if search_terms is not None:
        queries = [q for q in (search_terms.queries or []) if q and q.strip()]
    if not queries:
        queries = [None]  # type: ignore[list-item]  # None → scrape landing page

    if queries != [None]:
        logger.info(
            "fetch_all: using %d search queries: %s",
            len(queries),
            ", ".join(repr(q) for q in queries),
        )
    else:
        logger.info("fetch_all: no search query — scraping landing pages")

    all_jobs: List[Dict] = []

    logger.info("Starting fetch for %d companies × %d queries", len(companies), len(queries))
    for entry in companies:
        company = entry.get("company")
        url = entry.get("url")
        if not company or not url:
            continue

        search_url_template = entry.get("search_url") or None

        # Accumulate jobs across all queries for this company, dedup in memory.
        company_jobs: list[Dict] = []
        seen_keys: set[tuple] = set()

        for qi, query in enumerate(queries, 1):
            if query is not None:
                logger.info(
                    "[%s] query %d/%d: %r", company, qi, len(queries), query,
                )

            try:
                jobs = scrape_and_extract(
                    url,
                    company=company,
                    config=config,
                    query=query,
                    search_url_template=search_url_template,
                )
            except ScrapingError as exc:
                logger.warning("Skipping %s (query %r): %s", company, query, exc)
                continue

            # Dedup within the company across queries.
            for job in jobs:
                key = (job.get("title"), job.get("url"))
                if key not in seen_keys:
                    seen_keys.add(key)
                    company_jobs.append(job)

        # Fallback: if all search queries returned 0 jobs, scrape the
        # original landing page without a query (gets ALL jobs via pagination).
        if not company_jobs and queries != [None]:
            logger.info(
                "[%s] search queries returned 0 jobs — falling back to landing page: %s",
                company, url,
            )
            try:
                fallback_jobs = scrape_and_extract(
                    url, company=company, config=config, query=None,
                )
                for job in fallback_jobs:
                    key = (job.get("title"), job.get("url"))
                    if key not in seen_keys:
                        seen_keys.add(key)
                        company_jobs.append(job)
            except ScrapingError as exc:
                logger.warning("Fallback scrape failed for %s: %s", company, exc)

        # Persist per-company results immediately (merge, not overwrite).
        if company_jobs:
            try:
                path = save_company_jobs(company, company_jobs)
                logger.info("Saved %d jobs for %s to %s", len(company_jobs), company, path)
            except Exception:
                logger.debug("Immediate save failed for %s (continuing)", company)
            all_jobs.extend(company_jobs)
        else:
            logger.warning("No jobs found for %s across %d queries", company, len(queries))

    logger.info("Finished fetch_all: %d total jobs", len(all_jobs))
    return all_jobs


# ── Keyword probe ───────────────────────────────────────────────────────────

def probe_url(
    url: str,
    company: str,
    query: str,
    config: dict,
    *,
    search_url_template: str | None = None,
) -> tuple[list[dict], str]:
    """Return (jobs, resolved_url) for a company × keyword pair.

    Uses the ATS API when available (fast, authoritative).  For non-ATS sites
    resolves the search URL via url_builder — if that succeeds the call returns
    a sentinel list ``["probe-ok"]`` so the caller knows the URL is valid
    without paying for a full Playwright render here.  Returns ``([], url)``
    when no URL can be resolved.
    """
    from targetfit.ingestion.ats_api import fetch_via_api

    location = config.get("location")
    resolved = resolve_search_url(url, query, search_url_template, location=location)
    probe_target = resolved or url

    # ATS API path — instant and authoritative.
    api_jobs = fetch_via_api(url, company, query=query)
    if api_jobs is not None:
        return api_jobs, probe_target

    # Non-ATS: if url_builder could resolve a search URL, treat that as
    # a success without running a full Playwright fetch here.
    if resolved:
        return ["probe-ok"], resolved  # sentinel — full fetch re-runs properly

    return [], url


# ── Single-URL job fetching ──────────────────────────────────────────────────

def _resolve_company(extracted: str | None, hint: str | None, url: str) -> str:
    """Determine company name from hint, LLM extraction, or URL domain."""
    if hint:
        return hint
    if extracted and extracted.strip():
        return extracted.strip()
    host = urlparse(url).netloc.lower()
    parts = host.split(".")
    skip = {"jobs", "careers", "www", "apply", "work"}
    meaningful = next((p for p in parts if p not in skip), parts[0])
    return meaningful.title()


def _repair_job_json(broken: str, config: Dict[str, Any]) -> Dict | None:
    """Ask the fallback model to fix broken JSON from JOB_EXTRACTOR."""
    import json as _json

    from targetfit.models import ExtractedJob
    from targetfit.nlp.llm import call_ollama, parse_json_response, LLMError, ParseError

    repair_system = (
        "You are a JSON repair tool. The user will give you broken or malformed JSON. "
        "Return ONLY the corrected JSON object — no explanation, no markdown fences."
    )
    schema_str = _json.dumps(ExtractedJob.model_json_schema(), indent=2)
    repair_prompt = (
        "Fix this JSON so it is valid. Keep the same keys and values.\n"
        f"Required schema:\n{schema_str}\n\n"
        f"{broken}"
    )
    model = config.get("fallback_model") or config.get("extraction_model") or config.get("model")
    try:
        resp = call_ollama(
            prompt=repair_prompt,
            system=repair_system,
            config=config,
            response_schema=ExtractedJob.model_json_schema(),
            model_override=model,
        )
        return parse_json_response(resp)
    except (LLMError, ParseError):
        return None


def fetch_job_url(
    url: str,
    cfg: Dict[str, Any],
    *,
    company_hint: str | None = None,
) -> Dict | None:
    """Fetch a single job posting by direct URL.

    Resolution order:
    1. ATS API — for known Greenhouse/Lever single-job URLs (fast, no LLM).
    2. Playwright render + JOB_EXTRACTOR LLM prompt.
    3. LLM repair on broken JSON output.
    4. Retry with fallback model.
    5. HTML salvage — extract <title> tag as job title.

    Returns a canonical job dict or None on failure.
    """
    from pydantic import ValidationError

    from targetfit.ingestion.ats_api import fetch_single_job_via_api
    from targetfit.models import ExtractedJob, Job
    from targetfit.nlp.llm import (
        _load_agent_section, _extract_system_prompt,
        call_ollama, parse_json_response, LLMError, ParseError,
    )

    # Strategy 1: ATS API (instant, no Playwright, no LLM).
    result = fetch_single_job_via_api(url, company_hint)
    if result is not None:
        logger.info("fetch_job_url: ATS API hit for %s", url)
        return result

    # Strategy 2+: Playwright render.
    try:
        html = fetch_rendered_html(url)
    except Exception as exc:
        logger.warning("fetch_job_url: Playwright render failed for %s: %s", url, exc)
        return None

    if not html:
        logger.warning("fetch_job_url: empty HTML for %s", url)
        return None

    cleaned = _clean_html(html)

    try:
        section = _load_agent_section("JOB_EXTRACTOR")
        system_prompt = _extract_system_prompt(section)
    except LLMError as exc:
        logger.error("fetch_job_url: failed to load JOB_EXTRACTOR prompt: %s", exc)
        return None

    extraction_model = cfg.get("extraction_model") or cfg.get("model")
    fallback_model = cfg.get("fallback_model")
    user_prompt = f"Extract the job details from this HTML:\n\n{cleaned[:8000]}"
    extracted_job_schema = ExtractedJob.model_json_schema()

    parsed: Any = None
    raw_resp: str = ""

    # Attempt 1: extraction_model with structured output.
    try:
        raw_resp = call_ollama(
            prompt=user_prompt,
            system=system_prompt,
            config=cfg,
            response_schema=extracted_job_schema,
            model_override=extraction_model,
        )
        raw_parsed = parse_json_response(raw_resp)
        parsed = ExtractedJob.model_validate(raw_parsed).model_dump()
    except (LLMError, ParseError, ValidationError) as exc:
        logger.warning("fetch_job_url: primary extraction failed for %s: %s", url, exc)

    # Attempt 2: LLM repair on broken JSON.
    if parsed is None and raw_resp and raw_resp.strip():
        parsed = _repair_job_json(raw_resp, cfg)
        if parsed is not None:
            logger.info("fetch_job_url: JSON repair succeeded for %s", url)

    # Attempt 3: retry with fallback model directly.
    if parsed is None and fallback_model and fallback_model != extraction_model:
        try:
            raw_resp2 = call_ollama(
                prompt=user_prompt,
                system=system_prompt,
                config=cfg,
                response_schema=extracted_job_schema,
                model_override=fallback_model,
            )
            raw_parsed2 = parse_json_response(raw_resp2)
            parsed = ExtractedJob.model_validate(raw_parsed2).model_dump()
            logger.info("fetch_job_url: fallback model succeeded for %s", url)
        except (LLMError, ParseError, ValidationError) as exc:
            logger.warning("fetch_job_url: fallback model failed for %s: %s", url, exc)

    # Attempt 4: HTML salvage — use <title> tag as job title.
    if parsed is None:
        soup = BeautifulSoup(html, "html.parser")
        title_tag = soup.find("title")
        if title_tag:
            title_text = title_tag.get_text(strip=True)
            parsed = {
                "title": title_text,
                "company": None,
                "location": None,
                "description": None,
                "date_posted": None,
            }
            logger.info("fetch_job_url: HTML salvage recovered title %r for %s", title_text, url)
        else:
            logger.warning("fetch_job_url: all extraction strategies failed for %s", url)
            return None

    if not isinstance(parsed, dict):
        return None

    title = parsed.get("title")
    if not title:
        logger.warning("fetch_job_url: no title extracted for %s", url)
        return None

    return Job(
        company=_resolve_company(parsed.get("company"), company_hint, url),
        title=title,
        location=parsed.get("location"),
        url=url,
        description=parsed.get("description"),
        date_posted=parsed.get("date_posted"),
    ).model_dump()

"""Scrape careers pages and extract structured job listings using ScrapeGraphAI + Ollama.

ScrapeGraphAI combines web scraping and LLM-based extraction into a single step,
so there is no need for a separate reader service or manual LLM extraction call.
Everything runs locally via Ollama — zero external API costs.
"""

import asyncio
from typing import Any, Dict, List
import warnings

# Silence noisy Pydantic v1 + Python 3.14 deprecation warnings from langchain_core.
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    module="langchain_core._api.deprecation",
)

from playwright.async_api import async_playwright
from scrapegraphai.graphs import SmartScraperGraph

from utils import setup_logger


logger = setup_logger(__name__)


class ScrapingError(Exception):
    """Raised when a ScrapeGraphAI scrape fails."""


# ── Playwright renderer ─────────────────────────────────────────────────────

async def _render_page(url: str, extra_wait_ms: int = 3000) -> str:
    """Return fully-rendered HTML after JS execution completes."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(extra_wait_ms)
        html = await page.content()
        await browser.close()
        return html


def fetch_rendered_html(url: str, extra_wait_ms: int = 3000) -> str:
    """Sync wrapper — fetch fully-rendered HTML from *url* using Playwright."""
    return asyncio.run(_render_page(url, extra_wait_ms=extra_wait_ms))


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
Extract ALL job listings from this company careers page.

Return a JSON object with a single key "jobs" containing an array.
Each job object must have exactly these fields:
{
  "title": string,         // exact job title as written on the page
  "location": string,      // city, country or "Remote" — null if not found
  "url": string,           // direct link to the job posting — null if not found
  "date_posted": string,   // ISO date if available — null if not found
  "description": string    // job description text, max 1000 chars
}

Rules:
- Only extract jobs that are explicitly listed on the page. Do NOT invent jobs.
- If a field is missing, set it to null.
- If no jobs are found, return {"jobs": []}.
- Preserve original job titles exactly — do not rephrase or summarize.
- If multiple locations are listed for one role, create one entry per location.
"""


# ── Public API ──────────────────────────────────────────────────────────────

def scrape_and_extract(url: str, company: str, config: Dict[str, Any]) -> List[Dict]:
    """Scrape a single careers page and return structured job dicts.

    Uses ScrapeGraphAI's SmartScraperGraph which:
    1. Fetches the page (handles JS rendering via Playwright if needed)
    2. Passes the content to the local Ollama LLM
    3. Returns structured JSON based on the extraction prompt
    """
    logger.info("Scraping %s (%s)", company, url)
    graph_config = _build_graph_config(config)

    try:
        logger.info("Pre-rendering page with Playwright: %s", url)
        html = fetch_rendered_html(url)
    except Exception as exc:
        raise ScrapingError(f"Playwright render failed for {company} ({url}): {exc}") from exc

    try:
        scraper = SmartScraperGraph(
            prompt=EXTRACT_PROMPT,
            source=html,
            config=graph_config,
        )
        result = scraper.run()
    except Exception as exc:
        raise ScrapingError(
            f"ScrapeGraphAI failed for {company} ({url}): {exc}"
        ) from exc

    if not result:
        logger.warning("Empty result from ScrapeGraphAI for %s", company)
        return []

    # ScrapeGraphAI returns a dict; extract the jobs list.
    raw_jobs = result if isinstance(result, list) else result.get("jobs", [])

    if not isinstance(raw_jobs, list):
        logger.warning("Unexpected result type from ScrapeGraphAI for %s: %s",
                        company, type(raw_jobs))
        return []

    jobs: List[Dict[str, Any]] = []
    for item in raw_jobs:
        if not isinstance(item, dict):
            continue
        job = {
            "company": company,
            "title": item.get("title"),
            "location": item.get("location"),
            "url": item.get("url"),
            "description": item.get("description"),
            "date_posted": item.get("date_posted"),
        }
        jobs.append(job)

    logger.info("Extracted %d jobs for %s (%s)", len(jobs), company, url)
    return jobs


def fetch_all(companies: List[Dict[str, str]], config: Dict) -> List[Dict]:
    """Scrape + extract jobs for all companies in the list.

    Returns a flat list of job dicts ready for saving / indexing.
    """
    all_jobs: List[Dict] = []

    logger.info("Starting fetch for %d companies", len(companies))
    for entry in companies:
        company = entry.get("company")
        url = entry.get("url")
        if not company or not url:
            continue

        try:
            jobs = scrape_and_extract(url, company=company, config=config)
            all_jobs.extend(jobs)
        except ScrapingError as exc:
            logger.warning("Skipping %s: %s", company, exc)

    logger.info("Finished fetch_all: %d total jobs", len(all_jobs))
    return all_jobs

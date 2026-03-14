"""Build search URLs for company careers pages.

Priority order for each company entry:
  1. Explicit ``search_url`` column in companies.csv  (``{query}`` placeholder)
  2. Auto-detection from the base URL's hostname / path (known ATS patterns)
  3. Playwright-assisted: find and fill the search box, return rendered HTML

Call ``resolve_search_url()`` — it returns either:
  - A string URL  (cases 1 and 2): caller should fetch this URL normally.
  - None           (case 3 / unknown): caller must use Playwright to search.

ATS patterns implemented
  Workday, Greenhouse (job-boards & boards), Lever, Ashby,
  SmartRecruiters, iCIMS (via query param), Taleo (basic),
  plus hand-rolled overrides for Google, Microsoft, Amazon,
  Apple, Meta, Nvidia, IBM, Intel, Cisco, Oracle, Palantir,
  Bloomberg, BlackRock, Goldman Sachs, Goldman, and several
  pharma/biotech sites.
"""

from __future__ import annotations

import re
from urllib.parse import ParseResult, quote_plus, urlencode, urljoin, urlparse, urlunparse

from targetfit.log import setup_logger


logger = setup_logger(__name__)


# ── Public entry point ───────────────────────────────────────────────────────

def resolve_search_url(
    base_url: str,
    query: str,
    search_url_template: str | None = None,
    location: str | None = None,
) -> str | None:
    """Return a search results URL for *query*, or None if manual interaction is needed.

    Args:
        base_url:             The careers landing page URL from companies.csv.
        query:                The search string (from cv_parser, already URL-safe).
        search_url_template:  Optional override from the ``search_url`` CSV column;
                              must contain a ``{query}`` placeholder and optionally
                              a ``{location}`` placeholder.
        location:             Location filter (e.g. "Switzerland") from config.yaml.
    """
    q = query.strip()
    if not q:
        return base_url  # nothing to search — return landing page as-is

    loc = (location or "").strip()

    # ── 1. Explicit template from CSV ─────────────────────────────────────
    if search_url_template and "{query}" in search_url_template:
        url = search_url_template.replace("{query}", quote_plus(q))
        if "{location}" in url:
            url = url.replace("{location}", quote_plus(loc) if loc else "")
        logger.debug("url_builder: explicit template → %s", url)
        return url

    # ── 2. Auto-detect from base URL ─────────────────────────────────────
    detected = _autodetect(base_url, q)
    if detected:
        logger.debug("url_builder: auto-detected → %s", detected)
        return detected

    # ── 3. Unknown — caller must use Playwright interaction ───────────────
    logger.info(
        "url_builder: no pattern matched for %s — will use Playwright search", base_url
    )
    return None


# ── Auto-detection logic ─────────────────────────────────────────────────────

def _autodetect(base_url: str, q: str) -> str | None:
    """Try to build a search URL from the base URL using known ATS patterns."""
    parsed = urlparse(base_url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    qq = quote_plus(q)

    # ── Workday ──────────────────────────────────────────────────────────
    # Pattern: {tenant}.wd{n}.myworkdayjobs.com
    if "myworkdayjobs.com" in host:
        # Workday search appends ?q= to the existing path (job site root).
        # Strip any existing query to get the job-site base path.
        base_path = _strip_wd_path(parsed.path)
        return _build(parsed, base_path, {"q": q})

    # ── Greenhouse (job-boards.greenhouse.io) ────────────────────────────
    if host == "job-boards.greenhouse.io":
        return _build(parsed, parsed.path.rstrip("/"), {"q": q})

    # ── Greenhouse (boards.greenhouse.io legacy) ─────────────────────────
    if host == "boards.greenhouse.io":
        return _build(parsed, parsed.path.rstrip("/") + "/jobs", {"q": q})

    # ── Lever ────────────────────────────────────────────────────────────
    if host.endswith(".lever.co") or host == "lever.co":
        return _build(parsed, parsed.path, {"q": q})

    # ── Ashby ────────────────────────────────────────────────────────────
    if "ashbyhq.com" in host:
        return _build(parsed, parsed.path.rstrip("/"), {"search": q})

    # ── SmartRecruiters ──────────────────────────────────────────────────
    if "smartrecruiters.com" in host:
        return _build(parsed, parsed.path, {"q": q})

    # ── Taleo (taleo.net) ────────────────────────────────────────────────
    if "taleo.net" in host:
        # Most Taleo instances use keyWord= for search
        return _build(parsed, parsed.path, {"keyWord": q, "numItems": "25"})

    # ── iCIMS ────────────────────────────────────────────────────────────
    if "icims.com" in host:
        return _build(parsed, parsed.path, {"ss": q, "searchLocation": ""})

    # ── BambooHR ─────────────────────────────────────────────────────────
    if "bamboohr.com" in host:
        return _build(parsed, parsed.path, {"q": q})

    # ── Breezy ───────────────────────────────────────────────────────────
    if "breezy.hr" in host:
        return _build(parsed, parsed.path, {"search": q})

    # ── Teamtailor ──────────────────────────────────────────────────────
    if "teamtailor.com" in host:
        return _build(parsed, "/jobs", {"query": q})

    # ── ────────────────────────────────────────────────────────────────
    # Company-specific overrides (custom ATS / non-standard patterns)
    # ── ────────────────────────────────────────────────────────────────

    # Google / Alphabet
    if host == "careers.google.com":
        return f"https://careers.google.com/jobs/results/?q={qq}"

    # Microsoft (two possible domains)
    if host in ("careers.microsoft.com", "apply.careers.microsoft.com",
                "jobs.careers.microsoft.com"):
        return (
            f"https://jobs.careers.microsoft.com/global/en/search"
            f"?q={qq}&lc=&l=en_US&pgSz=20&o=Relevance"
        )

    # Amazon
    if host in ("www.amazon.jobs", "amazon.jobs"):
        return f"https://www.amazon.jobs/en/search?query={qq}&sort=relevant"

    # Apple
    if host in ("jobs.apple.com", "www.apple.com") and "/careers" in path:
        return f"https://jobs.apple.com/en-us/search?search={qq}&sort=relevance"

    # Meta
    if host in ("www.metacareers.com", "metacareers.com"):
        return f"https://www.metacareers.com/jobs/?q={qq}"

    # Nvidia Workday (specific job site path)
    if "nvidia" in host and "myworkdayjobs.com" in host:
        return (
            f"https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite"
            f"?q={qq}"
        )

    # Intel
    if host in ("jobs.intel.com", "www.intel.com"):
        return f"https://jobs.intel.com/en/search#q={qq}&t=Jobs"

    # IBM
    if "ibm.com" in host and "career" in path:
        return f"https://www.ibm.com/employment/professional?v=1#q={qq}&t=Jobs"

    # Cisco
    if host in ("jobs.cisco.com",):
        return f"https://jobs.cisco.com/jobs/SearchJobs/{qq}"

    # Oracle
    if "oracle.com" in host and "career" in path:
        return f"https://www.oracle.com/careers/search/#{qq}"

    # Palantir
    if "palantir.com" in host:
        return f"https://www.palantir.com/careers/students/jobs/?department=All&q={qq}"

    # Bloomberg
    if "bloomberg.com" in host and "career" in path:
        return f"https://careers.bloomberg.com/job/search?q={qq}"

    # BlackRock
    if "blackrock.com" in host:
        return f"https://careers.blackrock.com/job-search-results/?keyword={qq}"

    # Goldman Sachs
    if "goldmansachs.com" in host:
        return f"https://www.goldmansachs.com/careers/professionals/jobs/search.html?query={qq}"

    # McKinsey
    if "mckinsey.com" in host and "career" in path:
        return f"https://www.mckinsey.com/careers/search-jobs?q={qq}"

    # BCG
    if "bcg.com" in host and "career" in path:
        return f"https://careers.bcg.com/search?q={qq}"

    # Bain
    if "bain.com" in host and "career" in path:
        return f"https://www.bain.com/careers/find-a-role/?q={qq}"

    # Accenture
    if "accenture.com" in host and "career" in path:
        return f"https://www.accenture.com/us-en/careers/jobsearch?jk={qq}"

    # Deloitte
    if "deloitte.com" in host and "career" in path:
        return f"https://apply.deloitte.com/careers/SearchJobs/{qq}"

    # KPMG
    if "kpmg" in host and "career" in path:
        return f"https://careers.kpmg.us/jobs/search?q={qq}"

    # EY
    if "ey.com" in host and "career" in path:
        return f"https://www.ey.com/en_us/careers/job-search?q={qq}"

    # PwC
    if "pwc.com" in host and "career" in path:
        return f"https://www.pwc.com/us/en/careers/job-search.html?q={qq}"

    # Pfizer
    if "pfizer.com" in host and "career" in path:
        return f"https://www.pfizer.com/about/careers/search?q={qq}"

    # AstraZeneca
    if "astrazeneca.com" in host and "career" in path:
        return f"https://careers.astrazeneca.com/search-jobs?q={qq}&location=&country="

    # Novartis
    if "novartis.com" in host and "career" in path:
        return f"https://www.novartis.com/careers/career-search?q={qq}"

    # Roche
    if "roche.com" in host and "career" in path:
        return f"https://careers.roche.com/global/en/search-results.html?q={qq}"

    # Bristol Myers Squibb
    if "bms.com" in host and "career" in path:
        return f"https://careers.bms.com/jobs/search?q={qq}&location=&country="

    # Eli Lilly
    if "lilly.com" in host and "career" in path:
        return f"https://careers.lilly.com/search-jobs?q={qq}&ascf=[%7B%22key%22:%22custom_fields.Country%22,%22value%22:%22%22%7D]"

    # Genentech (uses Roche's system)
    if "gene.com" in host and "career" in path:
        return f"https://careers.gene.com/search-jobs?q={qq}"

    # J&J
    if "jnj.com" in host and "career" in path:
        return f"https://jobs.jnj.com/jobs?query={qq}&country=&location="

    # Boehringer Ingelheim
    if "boehringer-ingelheim.com" in host and "career" in path:
        return f"https://careers.boehringer-ingelheim.com/search?q={qq}"

    # Merck (US — not to be confused with Merck KGaA Germany)
    if "merck.com" in host and "career" in path:
        return f"https://jobs.merck.com/us/en/search-jobs/{qq}/"

    # Novo Nordisk
    if "novonordisk.com" in host and "career" in path:
        return f"https://www.novonordisk.com/careers/find-a-job.html?q={qq}"

    # Bayer
    if "bayer.com" in host and "career" in path:
        return f"https://career.bayer.com/en/careers/?q={qq}"

    # BASF
    if "basf.com" in host and "career" in path:
        return f"https://www.basf.com/global/en/careers/search.html?q={qq}"

    # Syngenta
    if "syngenta.com" in host and "career" in path:
        return f"https://www.syngenta.com/careers/find-a-job?q={qq}"

    # Sandoz
    if "sandoz.com" in host and "career" in path:
        return f"https://www.sandoz.com/careers/search?q={qq}"

    # Recursion
    if "recursion.com" in host and "career" in path:
        return f"https://www.recursion.com/careers#jobs?q={qq}"

    # DeepMind
    if "deepmind.google" in host and "career" in path:
        return f"https://deepmind.google/careers/?q={qq}"

    # Isomorphic Labs
    if "isomorphiclabs.com" in host:
        # Small company — no search, just the jobs listing page
        return base_url

    # Sartorius
    if "sartorius.com" in host and "career" in path:
        return f"https://www.sartorius.com/en/company/careers/job-search?q={qq}"

    # Lonza
    if "lonza.com" in host and "career" in path:
        return f"https://www.lonza.com/careers/job-search?q={qq}"

    # IQVIA
    if "iqvia.com" in host:
        return f"https://jobs.iqvia.com/search/{qq}/Jobs"

    # Agilent
    if "agilent.com" in host:
        return f"https://jobs.agilent.com/jobs?q={qq}"

    # HPE
    if "hpe.com" in host and "career" in path:
        return f"https://careers.hpe.com/us/en/search-results?q={qq}"

    # Ubisoft
    if "ubisoft.com" in host and "career" in path:
        return f"https://www.ubisoft.com/en-us/careers/search#q={qq}"

    # UBS
    if "ubs.com" in host and "career" in path:
        return f"https://www.ubs.com/global/en/careers/job-search.html?q={qq}"

    return None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _build(parsed: ParseResult, path: str, params: dict) -> str:
    """Reconstruct a URL with a new path and query parameters."""
    query_string = urlencode(params, quote_via=quote_plus)
    return urlunparse((parsed.scheme, parsed.netloc, path, "", query_string, ""))


def _strip_wd_path(path: str) -> str:
    """For Workday URLs, keep only the job-site root segment.

    e.g. /en-US/NVIDIAExternalCareerSite/job/...  →  /en-US/NVIDIAExternalCareerSite
    """
    # Workday paths are typically /{locale}/{site}/... — keep up to 3 segments.
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        return "/" + "/".join(parts[:2])
    return "/" + "/".join(parts) if parts else "/"

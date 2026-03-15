"""Direct API fetchers for ATS platforms that expose public job-listing endpoints.

These bypass Playwright rendering and LLM extraction entirely, returning
structured job dicts in the same schema as ``scrape.scrape_and_extract()``.

Supported platforms:
  - Greenhouse  (boards-api.greenhouse.io)
  - Lever       (api.lever.co)
  - Ashby       (api.ashbyhq.com)
  - SmartRecruiters (api.smartrecruiters.com)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests

from targetfit.helpers import truncate
from targetfit.log import setup_logger

logger = setup_logger(__name__)

# Timeout for all ATS API calls (seconds).
_TIMEOUT = 30


# ── ATS detection ────────────────────────────────────────────────────────────

class ATSInfo:
    """Detected ATS platform and the org/board identifier extracted from a URL."""

    def __init__(self, platform: str, org_id: str, base_url: str):
        self.platform = platform
        self.org_id = org_id
        self.base_url = base_url

    def __repr__(self) -> str:
        return f"ATSInfo(platform={self.platform!r}, org_id={self.org_id!r})"


def detect_ats(url: str) -> ATSInfo | None:
    """Detect whether *url* belongs to an ATS with a public API.

    Returns an ``ATSInfo`` if matched, or ``None`` if scraping is needed.
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")

    # ── Greenhouse ────────────────────────────────────────────────────────
    # job-boards.greenhouse.io/{board}  or  boards.greenhouse.io/{board}
    if host in ("job-boards.greenhouse.io", "boards.greenhouse.io"):
        org = path.split("/")[0] if path else None
        if org:
            return ATSInfo("greenhouse", org, url)

    # ── Lever ─────────────────────────────────────────────────────────────
    # jobs.lever.co/{company}
    if host == "jobs.lever.co" or host.endswith(".lever.co"):
        org = path.split("/")[0] if path else None
        if not org and host != "jobs.lever.co":
            org = host.split(".")[0]
        if org:
            return ATSInfo("lever", org, url)

    # ── Ashby ─────────────────────────────────────────────────────────────
    # jobs.ashbyhq.com/{org}
    if "ashbyhq.com" in host:
        org = path.split("/")[0] if path else None
        if org:
            return ATSInfo("ashby", org, url)

    # ── SmartRecruiters ───────────────────────────────────────────────────
    # jobs.smartrecruiters.com/{company}
    if "smartrecruiters.com" in host:
        org = path.split("/")[0] if path else None
        if org:
            return ATSInfo("smartrecruiters", org, url)

    return None


# ── Greenhouse ───────────────────────────────────────────────────────────────

def _fetch_greenhouse(org: str, company: str, query: str | None = None) -> List[Dict]:
    """Fetch jobs from Greenhouse Boards API.

    Endpoint: GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true
    """
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{org}/jobs"
    params: Dict[str, Any] = {"content": "true"}

    try:
        resp = requests.get(api_url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Greenhouse API failed for %s: %s", company, exc)
        return []

    data = resp.json()
    raw_jobs = data.get("jobs", [])

    jobs: List[Dict] = []
    for j in raw_jobs:
        title = j.get("title", "")
        if not title:
            continue

        # Filter by query if provided.
        if query and not _matches_query(title, j.get("content", ""), query):
            continue

        location = _greenhouse_location(j)
        job_url = j.get("absolute_url") or j.get("url")
        content = j.get("content") or ""
        # Strip HTML tags for description.
        description = _strip_html(content)[:1000] if content else None
        updated = (j.get("updated_at") or "")[:10] or None

        jobs.append({
            "company": company,
            "title": title,
            "location": location,
            "url": job_url,
            "description": description,
            "date_posted": updated,
        })

    return jobs


def _greenhouse_location(job: Dict) -> str | None:
    """Extract location string from a Greenhouse job object."""
    loc = job.get("location", {})
    if isinstance(loc, dict):
        return loc.get("name")
    if isinstance(loc, str):
        return loc
    return None


# ── Lever ────────────────────────────────────────────────────────────────────

def _fetch_lever(org: str, company: str, query: str | None = None) -> List[Dict]:
    """Fetch jobs from Lever Postings API.

    Endpoint: GET https://api.lever.co/v0/postings/{company}?mode=json
    """
    api_url = f"https://api.lever.co/v0/postings/{org}"
    params: Dict[str, str] = {"mode": "json"}

    try:
        resp = requests.get(api_url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Lever API failed for %s: %s", company, exc)
        return []

    raw_jobs = resp.json()
    if not isinstance(raw_jobs, list):
        return []

    jobs: List[Dict] = []
    for j in raw_jobs:
        title = j.get("text", "")
        if not title:
            continue

        if query and not _matches_query(title, j.get("descriptionPlain", ""), query):
            continue

        # Location from categories.
        cats = j.get("categories", {})
        location = cats.get("location") if isinstance(cats, dict) else None

        job_url = j.get("hostedUrl") or j.get("applyUrl")
        description = truncate(j.get("descriptionPlain") or "", 1000) or None
        created = j.get("createdAt")
        date_posted = None
        if isinstance(created, int):
            import datetime
            date_posted = datetime.datetime.fromtimestamp(created / 1000).strftime("%Y-%m-%d")

        jobs.append({
            "company": company,
            "title": title,
            "location": location,
            "url": job_url,
            "description": description,
            "date_posted": date_posted,
        })

    return jobs


# ── Ashby ────────────────────────────────────────────────────────────────────

def _fetch_ashby(org: str, company: str, query: str | None = None) -> List[Dict]:
    """Fetch jobs from Ashby Posting API.

    Endpoint: POST https://api.ashbyhq.com/posting-api/job-board/{org}
    """
    api_url = f"https://api.ashbyhq.com/posting-api/job-board/{org}"

    try:
        resp = requests.get(api_url, timeout=_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Ashby API failed for %s: %s", company, exc)
        return []

    data = resp.json()
    raw_jobs = data.get("jobs", [])

    jobs: List[Dict] = []
    for j in raw_jobs:
        title = j.get("title", "")
        if not title:
            continue

        if query and not _matches_query(title, "", query):
            continue

        location = j.get("location") or j.get("locationName")
        job_url = j.get("jobUrl") or j.get("applyUrl")
        published = (j.get("publishedAt") or "")[:10] or None

        jobs.append({
            "company": company,
            "title": title,
            "location": location,
            "url": job_url,
            "description": None,
            "date_posted": published,
        })

    return jobs


# ── SmartRecruiters ──────────────────────────────────────────────────────────

def _fetch_smartrecruiters(org: str, company: str, query: str | None = None) -> List[Dict]:
    """Fetch jobs from SmartRecruiters Public API.

    Endpoint: GET https://api.smartrecruiters.com/v1/companies/{id}/postings
    """
    api_url = f"https://api.smartrecruiters.com/v1/companies/{org}/postings"
    params: Dict[str, Any] = {"limit": 100}
    if query:
        params["q"] = query

    all_jobs: List[Dict] = []
    offset = 0

    while True:
        params["offset"] = offset
        try:
            resp = requests.get(api_url, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("SmartRecruiters API failed for %s: %s", company, exc)
            break

        data = resp.json()
        content = data.get("content", [])
        if not content:
            break

        for j in content:
            title = j.get("name", "")
            if not title:
                continue

            loc = j.get("location", {})
            location = None
            if isinstance(loc, dict):
                parts = [loc.get("city"), loc.get("region"), loc.get("country")]
                location = ", ".join(p for p in parts if p) or None

            job_url = j.get("ref") or j.get("applyUrl")
            created = (j.get("releasedDate") or "")[:10] or None

            all_jobs.append({
                "company": company,
                "title": title,
                "location": location,
                "url": job_url,
                "description": None,
                "date_posted": created,
            })

        # Paginate.
        total = data.get("totalFound", 0)
        offset += len(content)
        if offset >= total:
            break

    return all_jobs


# ── Public API ───────────────────────────────────────────────────────────────

_FETCHERS = {
    "greenhouse": _fetch_greenhouse,
    "lever": _fetch_lever,
    "ashby": _fetch_ashby,
    "smartrecruiters": _fetch_smartrecruiters,
}


def fetch_via_api(
    url: str,
    company: str,
    query: str | None = None,
) -> List[Dict] | None:
    """Try to fetch jobs via a direct ATS API call.

    Returns:
        - A list of job dicts if the URL matches a known ATS API.
        - ``None`` if the URL doesn't match any known ATS (caller should scrape).
    """
    ats = detect_ats(url)
    if ats is None:
        return None

    fetcher = _FETCHERS.get(ats.platform)
    if fetcher is None:
        return None

    logger.info(
        "Using %s API for %s (org=%s)",
        ats.platform.title(), company, ats.org_id,
    )
    jobs = fetcher(ats.org_id, company, query)
    logger.info(
        "%s API returned %d jobs for %s%s",
        ats.platform.title(),
        len(jobs),
        company,
        f" (query={query!r})" if query else "",
    )
    return jobs


# ── Single-job API fetchers ───────────────────────────────────────────────────

def _fetch_greenhouse_single(board: str, job_id: str, company_hint: str | None) -> dict | None:
    """Fetch a single Greenhouse job by board + job ID."""
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"
    try:
        resp = requests.get(api_url, params={"content": "true"}, timeout=_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Greenhouse single-job API failed (%s/%s): %s", board, job_id, exc)
        return None

    j = resp.json()
    title = j.get("title", "")
    if not title:
        return None

    company = company_hint or board.replace("-", " ").title()
    location = _greenhouse_location(j)
    job_url = j.get("absolute_url") or j.get("url")
    content = j.get("content") or ""
    description = _strip_html(content)[:3000] if content else None
    updated = (j.get("updated_at") or "")[:10] or None

    return {
        "company": company,
        "title": title,
        "location": location,
        "url": job_url,
        "description": description,
        "date_posted": updated,
    }


def _fetch_lever_single(org: str, posting_id: str, company_hint: str | None) -> dict | None:
    """Fetch a single Lever posting by org + posting ID."""
    api_url = f"https://api.lever.co/v0/postings/{org}/{posting_id}"
    try:
        resp = requests.get(api_url, timeout=_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Lever single-job API failed (%s/%s): %s", org, posting_id, exc)
        return None

    j = resp.json()
    title = j.get("text", "")
    if not title:
        return None

    company = company_hint or org.replace("-", " ").title()
    cats = j.get("categories", {})
    location = cats.get("location") if isinstance(cats, dict) else None
    job_url = j.get("hostedUrl") or j.get("applyUrl")
    description = truncate(j.get("descriptionPlain") or "", 3000) or None
    created = j.get("createdAt")
    date_posted = None
    if isinstance(created, int):
        import datetime
        date_posted = datetime.datetime.fromtimestamp(created / 1000).strftime("%Y-%m-%d")

    return {
        "company": company,
        "title": title,
        "location": location,
        "url": job_url,
        "description": description,
        "date_posted": date_posted,
    }


def fetch_single_job_via_api(url: str, company_hint: str | None) -> dict | None:
    """Return a job dict if *url* is a known ATS single-job URL, else None."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    parts = parsed.path.strip("/").split("/")

    # Greenhouse: job-boards.greenhouse.io/{board}/jobs/{id}
    if host in ("job-boards.greenhouse.io", "boards.greenhouse.io"):
        if len(parts) >= 3 and parts[1] == "jobs":
            return _fetch_greenhouse_single(parts[0], parts[2], company_hint)

    # Lever: jobs.lever.co/{org}/{posting-id}
    if host == "jobs.lever.co":
        if len(parts) >= 2:
            return _fetch_lever_single(parts[0], parts[1], company_hint)

    return None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    """Remove HTML tags from a string."""
    return re.sub(r"<[^>]+>", " ", html).strip()


def _matches_query(title: str, description: str, query: str) -> bool:
    """Check if a job title or description loosely matches the search query.

    Splits the query into words and requires at least one word to appear
    in either the title or description (case-insensitive).
    """
    words = [w.lower() for w in query.split() if len(w) >= 3]
    if not words:
        return True  # empty query matches everything

    combined = (title + " " + description).lower()
    return any(w in combined for w in words)

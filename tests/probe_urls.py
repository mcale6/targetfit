#!/usr/bin/env python3
"""
URL Probe Script for All Companies

Quickly tests all company search URLs with a lightweight LLM probe to:
- Distinguish broken URLs from URLs with no results
- Produce a categorized TODO list for manual fixing

Run: python tests/probe_urls.py
"""

import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict

import requests

# Add parent to path so we can import targetfit
sys.path.insert(0, str(Path(__file__).parent.parent))

from targetfit.config import PROJECT_ROOT, load_config
from targetfit.ingestion.ats_api import fetch_via_api
from targetfit.ingestion.url_builder import resolve_search_url
from targetfit.log import setup_logger
from targetfit.nlp.llm import call_ollama

logger = setup_logger(__name__)

QUERY = "bioinformatics"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def check_company(
    company: str,
    url: str,
    search_url_template: str,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Check a single company's search URL.

    Returns a dict with:
    - status: one of HAS_JOBS, NO_RESULTS, BROKEN, NO_SEARCH_URL,
              ATS_NO_RESULTS, ATS_HAS_JOBS, JS_RENDERED
    - count: int, number of jobs found (0 if N/A)
    - resolved_url: the actual URL tested, or None
    - note: human-readable message
    """

    # Step 1: Try ATS API (fast, authoritative)
    jobs_via_api = fetch_via_api(url, company, query=QUERY)
    if jobs_via_api is not None:
        if len(jobs_via_api) == 0:
            return {
                "status": "ATS_NO_RESULTS",
                "count": 0,
                "resolved_url": url,
                "note": "ATS API found no matches for 'bioinformatics'",
            }
        else:
            return {
                "status": "ATS_HAS_JOBS",
                "count": len(jobs_via_api),
                "resolved_url": url,
                "note": f"ATS API found {len(jobs_via_api)} jobs",
            }

    # Step 2: Resolve search URL (tries CSV template first, then auto-detection)
    template = search_url_template if search_url_template and "{query}" in search_url_template else None
    resolved_url = resolve_search_url(url, QUERY, template, location="")
    if resolved_url is None:
        return {
            "status": "NO_SEARCH_URL",
            "count": 0,
            "resolved_url": None,
            "note": "No search_url template and no auto-detected pattern",
        }

    # Step 4: HTTP GET
    try:
        resp = requests.get(
            resolved_url,
            timeout=15,
            headers={"User-Agent": USER_AGENT},
        )
        if resp.status_code >= 400:
            return {
                "status": "BROKEN",
                "count": 0,
                "resolved_url": resolved_url,
                "note": f"HTTP {resp.status_code}",
            }
    except requests.RequestException as exc:
        return {
            "status": "BROKEN",
            "count": 0,
            "resolved_url": resolved_url,
            "note": f"Request failed: {type(exc).__name__}",
        }

    # Step 5: Strip HTML and check if page has content
    html_text = resp.text
    visible_text = re.sub(r"<[^>]+>", " ", html_text)
    visible_text = re.sub(r"\s+", " ", visible_text).strip()

    if len(visible_text) < 100:
        return {
            "status": "JS_RENDERED",
            "count": 0,
            "resolved_url": resolved_url,
            "note": "Page is mostly JS-rendered (Playwright needed)",
        }

    # Step 6: Lightweight LLM probe
    sample_text = visible_text[:800]
    prompt = (
        f"Page text:\n{sample_text}\n\n"
        f"Does this page show job search results for '{QUERY}'? "
        f"Reply with valid JSON only: {{\"has_jobs\": bool, \"count_estimate\": int, \"reason\": str}}"
    )
    system = "You check if a web page shows job search results. Reply only with valid JSON."

    try:
        probe_model = config.get("probe_model") or config.get("fallback_model")
        llm_response = call_ollama(
            prompt=prompt,
            system=system,
            config=config,
            json_mode=True,
            model_override=probe_model,
        )
        result = json.loads(llm_response)
        has_jobs = result.get("has_jobs", False)
        count_estimate = result.get("count_estimate", 0)

        if has_jobs:
            return {
                "status": "HAS_JOBS",
                "count": count_estimate,
                "resolved_url": resolved_url,
                "note": f"LLM detected ~{count_estimate} jobs",
            }
        else:
            return {
                "status": "NO_RESULTS",
                "count": 0,
                "resolved_url": resolved_url,
                "note": "URL works but no matching jobs found",
            }
    except Exception as exc:
        logger.warning("LLM probe failed for %s: %s", company, exc)
        return {
            "status": "NO_RESULTS",
            "count": 0,
            "resolved_url": resolved_url,
            "note": f"LLM probe failed: {type(exc).__name__}",
        }


def main():
    """Main entry point."""
    config = load_config()
    companies_csv = PROJECT_ROOT / "data" / "companies.csv"

    if not companies_csv.exists():
        print(f"ERROR: {companies_csv} not found")
        sys.exit(1)

    results = []
    with open(companies_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        companies = list(reader)

    print(f"Probing {len(companies)} companies...\n")

    for row in companies:
        company = (row.get("company") or "").strip()
        url = (row.get("url") or "").strip()
        search_url = (row.get("search_url") or "").strip()

        if not company or not url:
            continue

        try:
            result = check_company(company, url, search_url, config)
        except Exception as exc:
            logger.exception("Error checking %s: %s", company, exc)
            result = {
                "status": "ERROR",
                "count": 0,
                "resolved_url": None,
                "note": f"Error: {type(exc).__name__}",
            }

        result["company"] = company
        results.append(result)

        # Live progress
        status_str = result.get("status", "UNKNOWN")
        count = result.get("count", 0) or 0
        count_str = f" ({count} jobs)" if count > 0 else ""
        note = result.get("note", "")
        print(f"[{status_str:20s}] {company:30s} {note}{count_str}")

    # Group results by status
    grouped = {}
    for result in results:
        status = result["status"]
        if status not in grouped:
            grouped[status] = []
        grouped[status].append(result)

    # Write markdown report
    output_file = PROJECT_ROOT / "data" / "url_probe_results.md"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("# URL Probe Results\n\n")
        f.write(f"Generated for keyword: **{QUERY}**\n\n")

        # Summary counts
        f.write("## Summary\n\n")
        for status in sorted(grouped.keys()):
            count = len(grouped[status])
            f.write(f"- **{status}**: {count}\n")

        f.write(f"\nTotal: {len(results)} companies\n\n")

        # Detailed tables by status
        status_order = [
            "HAS_JOBS",
            "ATS_HAS_JOBS",
            "ATS_NO_RESULTS",
            "NO_RESULTS",
            "JS_RENDERED",
            "BROKEN",
            "NO_SEARCH_URL",
            "ERROR",
        ]

        for status in status_order:
            if status not in grouped:
                continue

            companies_for_status = grouped[status]
            f.write(f"\n## {status}\n\n")

            if status == "HAS_JOBS":
                f.write("✅ **No action needed — jobs found**\n\n")
            elif status == "ATS_HAS_JOBS":
                f.write("✅ **No action needed — ATS API found jobs**\n\n")
            elif status == "NO_RESULTS":
                f.write("🟡 **Check URL format or verify truly no jobs exist**\n\n")
            elif status == "ATS_NO_RESULTS":
                f.write("🟡 **ATS API works but no matching jobs (likely authoritative)**\n\n")
            elif status == "JS_RENDERED":
                f.write("🟡 **Page requires JavaScript (Playwright needed to test)**\n\n")
            elif status == "BROKEN":
                f.write("🔴 **Fix or remove broken URL**\n\n")
            elif status == "NO_SEARCH_URL":
                f.write("🟡 **Research and add search_url or verify not an ATS**\n\n")
            elif status == "ERROR":
                f.write("🔴 **Probe script error — review logs and retry**\n\n")

            f.write("| Company | Note | URL |\n")
            f.write("|---------|------|-----|\n")

            for result in sorted(companies_for_status, key=lambda x: x["company"]):
                company = result["company"]
                note = result["note"]
                url = result["resolved_url"] or result.get("company")
                f.write(f"| {company} | {note} | `{url}` |\n")

    print(f"\n✓ Results written to {output_file}")


if __name__ == "__main__":
    main()

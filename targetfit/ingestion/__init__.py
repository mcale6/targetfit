"""Ingestion — scraping, ATS APIs, and URL construction."""

from targetfit.ingestion.ats_api import ATSInfo, detect_ats, fetch_via_api
from targetfit.ingestion.scrape import ScrapingError, fetch_all, scrape_and_extract
from targetfit.ingestion.url_builder import resolve_search_url

__all__ = [
    "ATSInfo",
    "ScrapingError",
    "detect_ats",
    "fetch_all",
    "fetch_via_api",
    "resolve_search_url",
    "scrape_and_extract",
]

"""File I/O for companies CSV, job JSON, and CV text."""

import csv
import json
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, List

from targetfit.config import PROJECT_ROOT


_DATA_DIR = PROJECT_ROOT / "data"


def load_companies(csv_path: str | None = None) -> List[Dict[str, str]]:
    """Load companies from CSV.

    Expected columns: company, url, search_url (optional).
    ``search_url`` may contain a ``{query}`` placeholder that url_builder
    will substitute at scrape time.  An empty value means auto-detect.
    """
    rows: List[Dict[str, str]] = []
    path = Path(csv_path) if csv_path else _DATA_DIR / "companies.csv"
    if not path.exists():
        return rows

    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            company = (row.get("company") or "").strip()
            url = (row.get("url") or "").strip()
            if company and url:
                entry: Dict[str, str] = {"company": company, "url": url}
                search_url = (row.get("search_url") or "").strip()
                if search_url:
                    entry["search_url"] = search_url
                rows.append(entry)
    return rows


def add_company_to_csv(
    company: str,
    url: str,
    *,
    search_url: str | None = None,
    csv_path: str | None = None,
) -> None:
    """Append a company row to the companies CSV."""
    path = Path(csv_path) if csv_path else _DATA_DIR / "companies.csv"
    path.parent.mkdir(parents=True, exist_ok=True)

    write_header = not path.exists() or path.stat().st_size == 0

    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["company", "url", "search_url"])
        writer.writerow([company.strip(), url.strip(), (search_url or "").strip()])


def remove_company_from_csv(
    company: str,
    *,
    csv_path: str | None = None,
) -> bool:
    """Remove a company from the CSV (case-insensitive match). Returns True if found."""
    csv_path_str = csv_path or str(_DATA_DIR / "companies.csv")
    path = Path(csv_path_str)
    if not path.exists():
        return False

    rows = load_companies(csv_path_str)
    target = company.strip().lower()
    filtered = [r for r in rows if r.get("company", "").lower() != target]

    if len(filtered) == len(rows):
        return False

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["company", "url", "search_url"])
        writer.writeheader()
        for row in filtered:
            writer.writerow({
                "company": row.get("company", ""),
                "url": row.get("url", ""),
                "search_url": row.get("search_url", ""),
            })
    return True


def load_cv(path: str | None = None) -> str:
    """Read raw CV text."""
    p = Path(path) if path else _DATA_DIR / "cv.txt"
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def _dataclass_to_dict(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [_dataclass_to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _dataclass_to_dict(v) for k, v in obj.items()}
    return obj


def save_jobs(jobs: List[Dict[str, Any]], path: str | None = None) -> None:
    """Write jobs list to JSON, pretty printed."""
    p = Path(path) if path else _DATA_DIR / "jobs.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(_dataclass_to_dict(jobs), f, indent=2, ensure_ascii=False)


def load_jobs(path: str | None = None) -> List[Dict[str, Any]]:
    """Read jobs list from JSON."""
    p = Path(path) if path else _DATA_DIR / "jobs.json"
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _slugify_company(name: str) -> str:
    """Turn a company name into a safe filename."""
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "company"


def save_company_jobs(
    company: str, jobs: List[Dict[str, Any]], base_dir: str | None = None
) -> Path:
    """Save jobs for a single company to data/jobs/{company}.json.

    Merges *jobs* into any existing file for this company, deduplicating
    on (title, url) so repeated fetches or multi-query runs accumulate
    results instead of overwriting them.
    """
    slug = _slugify_company(company)
    base = Path(base_dir) if base_dir else _DATA_DIR / "jobs"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{slug}.json"

    existing: List[Dict[str, Any]] = []
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                existing = json.load(f) or []
            if isinstance(existing, dict):
                existing = [existing]
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    seen: set[tuple] = {
        (j.get("title"), j.get("url")) for j in existing if isinstance(j, dict)
    }
    merged = list(existing)
    for job in _dataclass_to_dict(jobs):
        key = (job.get("title"), job.get("url"))
        if key not in seen:
            seen.add(key)
            merged.append(job)

    with path.open("w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    return path


def load_all_company_jobs(base_dir: str | None = None) -> List[Dict[str, Any]]:
    """Load and concatenate jobs from all data/jobs/*.json files."""
    base = Path(base_dir) if base_dir else _DATA_DIR / "jobs"
    if not base.exists():
        return []

    all_jobs: List[Dict[str, Any]] = []
    for path in sorted(base.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as f:
                jobs = json.load(f) or []
        except json.JSONDecodeError:
            continue

        if isinstance(jobs, dict):
            jobs = [jobs]
        if not isinstance(jobs, list):
            continue

        for job in jobs:
            if isinstance(job, dict) and not job.get("company"):
                job["company"] = path.stem
            all_jobs.append(job)

    return all_jobs

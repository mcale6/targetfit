import csv
import json
import logging
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import yaml


def load_config(path: str = "config.yaml") -> Dict[str, Any]:
    """Load YAML configuration file."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_companies(csv_path: str = "data/companies.csv") -> List[Dict[str, str]]:
    """Load companies from CSV with columns: company,url."""
    rows: List[Dict[str, str]] = []
    path = Path(csv_path)
    if not path.exists():
        return rows

    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            company = (row.get("company") or "").strip()
            url = (row.get("url") or "").strip()
            if company and url:
                rows.append({"company": company, "url": url})
    return rows


def load_cv(path: str = "data/cv.txt") -> str:
    """Read raw CV text."""
    p = Path(path)
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


def save_jobs(jobs: List[Dict[str, Any]], path: str = "data/jobs.json") -> None:
    """Write jobs list to JSON, pretty printed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(_dataclass_to_dict(jobs), f, indent=2, ensure_ascii=False)


def load_jobs(path: str = "data/jobs.json") -> List[Dict[str, Any]]:
    """Read jobs list from JSON."""
    p = Path(path)
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
    company: str, jobs: List[Dict[str, Any]], base_dir: str = "data/jobs"
) -> Path:
    """Save jobs for a single company to data/jobs/{company}.json."""
    slug = _slugify_company(company)
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{slug}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(_dataclass_to_dict(jobs), f, indent=2, ensure_ascii=False)
    return path


def load_all_company_jobs(base_dir: str = "data/jobs") -> List[Dict[str, Any]]:
    """Load and concatenate jobs from all data/jobs/*.json files."""
    base = Path(base_dir)
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


class ColorFormatter(logging.Formatter):
    """Logging formatter that adds colors and a compact, readable layout."""

    COLORS = {
        "DEBUG": "\033[36m",  # cyan
        "INFO": "\033[32m",  # green
        "WARNING": "\033[33m",  # yellow
        "ERROR": "\033[31m",  # red
        "CRITICAL": "\033[41m",  # red background
        "RESET": "\033[0m",
    }

    def format(self, record: logging.LogRecord) -> str:
        level_name = record.levelname
        color = self.COLORS.get(level_name, "")
        reset = self.COLORS["RESET"]
        prefix = f"[{self.formatTime(record, datefmt='%H:%M:%S')}] {level_name:<8} {record.name}: "
        message = super().format(record)
        if color:
            return f"{color}{prefix}{message}{reset}"
        return prefix + message


def configure_root_logger(level: int = logging.INFO) -> logging.Logger:
    """Configure and return the process-wide root logger with colored output."""
    logger = logging.getLogger()

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = ColorFormatter("%(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.setLevel(level)
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get a named logger, ensuring the root logger is configured once."""
    configure_root_logger()
    return logging.getLogger(name)


def setup_logger(name: str) -> logging.Logger:
    """Create a module-level logger with consistent, colored formatting."""
    return get_logger(name)


def truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, appending '...' if truncated."""
    if text is None:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3] + "..."


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    va = np.array(a, dtype=float)
    vb = np.array(b, dtype=float)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


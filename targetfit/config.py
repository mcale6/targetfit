"""Configuration loading and project root resolution."""

from pathlib import Path
from typing import Any, Dict

import yaml

# Resolve project root (parent of the targetfit/ package directory).
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | None = None) -> Dict[str, Any]:
    """Load YAML configuration file."""
    config_path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

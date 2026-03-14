"""Logging configuration with coloured output."""

import logging
from typing import Optional


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

    for noisy_logger in (
        "httpx",
        "httpcore",
        "urllib3",
        "openai",
        "LiteLLM",
        "litellm",
    ):
        dependency_logger = logging.getLogger(noisy_logger)
        dependency_logger.setLevel(logging.WARNING)
        dependency_logger.propagate = True

    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get a named logger, ensuring the root logger is configured once."""
    configure_root_logger()
    return logging.getLogger(name)


def setup_logger(name: str) -> logging.Logger:
    """Create a module-level logger with consistent, colored formatting."""
    return get_logger(name)

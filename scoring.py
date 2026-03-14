from typing import Any, Dict, List

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from llm import score_job
from utils import setup_logger


logger = setup_logger(__name__)
_console = Console()


def rank_by_vector(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort jobs by vector_score descending."""
    ranked = sorted(jobs, key=lambda j: j.get("vector_score") or 0.0, reverse=True)
    logger.debug("rank_by_vector: ranked %d jobs", len(ranked))
    return ranked


def rank_by_llm(
    jobs: List[Dict[str, Any]], cv: str, config: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Call LLM scorer for each job, adding llm_score and explanations."""
    logger.info("rank_by_llm: scoring %d jobs with LLM", len(jobs))
    enriched: List[Dict[str, Any]] = []
    for job in jobs:
        enriched.append(score_job(job, cv=cv, config=config))
    return enriched


def combined_score(job: Dict[str, Any], alpha: float = 0.4) -> float:
    """Combine vector_score and llm_score into a final score."""
    vector_score = float(job.get("vector_score") or 0.0)
    llm_score = float(job.get("llm_score") or 0.0)
    return alpha * vector_score + (1.0 - alpha) * llm_score


def apply_combined_scores(
    jobs: List[Dict[str, Any]], alpha: float = 0.4
) -> List[Dict[str, Any]]:
    """Apply combined_score to each job and resort."""
    for job in jobs:
        job["final_score"] = combined_score(job, alpha=alpha)
    ranked = sorted(jobs, key=lambda j: j.get("final_score") or 0.0, reverse=True)
    logger.info("apply_combined_scores: ranked %d jobs with alpha=%.2f", len(ranked), alpha)
    return ranked


def filter_by_threshold(
    jobs: List[Dict[str, Any]], config: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Filter jobs by final_score threshold."""
    threshold = float(config.get("score_threshold", 0.65))
    filtered = [j for j in jobs if float(j.get("final_score") or 0.0) >= threshold]
    logger.info(
        "filter_by_threshold: %d/%d jobs >= %.2f",
        len(filtered),
        len(jobs),
        threshold,
    )
    return filtered


def _score_bar(score: float, width: int = 12) -> Text:
    """Coloured block-bar for a score in [0, 1]."""
    filled = round(score * width)
    empty = width - filled
    if score >= 0.85:
        colour = "bold green"
    elif score >= 0.70:
        colour = "bold yellow"
    elif score >= 0.55:
        colour = "yellow"
    else:
        colour = "red"
    bar = Text()
    bar.append("█" * filled, style=colour)
    bar.append("░" * empty, style="dim")
    bar.append(f"  {score:.2f}", style=colour)
    return bar


def format_results(jobs: List[Dict[str, Any]]) -> str:
    """Render top matches as a rich table and return an empty string.

    Prints directly to the terminal via rich so formatting is preserved.
    The return value is kept as str for CLI compatibility (click.echo ignores "").
    """
    if not jobs:
        _console.print("[yellow]No matching jobs found.[/yellow]")
        return ""

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        expand=True,
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Company", style="bold white", min_width=18, max_width=22)
    table.add_column("Role", min_width=24)
    table.add_column("Location", style="dim", min_width=14, max_width=18)
    table.add_column("Score", min_width=18)

    for idx, job in enumerate(jobs, start=1):
        company  = job.get("company") or "—"
        title    = job.get("title")   or "—"
        location = job.get("location") or "—"
        score    = float(job.get("final_score") or job.get("vector_score") or 0.0)
        table.add_row(str(idx), company, title, location, _score_bar(score))

        reasons = job.get("match_reasons") or []
        gaps    = job.get("gaps")          or []
        summary = job.get("summary")       or ""
        if reasons or gaps or summary:
            detail = Text()
            if summary:
                detail.append("  " + summary + "\n", style="italic dim")
            for r in reasons:
                detail.append("  ✓ ", style="green")
                detail.append(r + "\n", style="dim")
            for g in gaps:
                detail.append("  ✗ ", style="red")
                detail.append(g + "\n", style="dim")
            table.add_row("", "", detail, "", "", end_section=True)

    _console.print(table)
    return ""


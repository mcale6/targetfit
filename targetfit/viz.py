"""Rich terminal visualisation for targetfit job match results.

Usage:
  python viz.py                         # vector-only, top 15
  python viz.py --top 20                # show more results
  python viz.py --llm-score             # enable LLM scoring (slower)
  python viz.py --threshold 0.5         # lower match threshold
  python viz.py --detail                # expand match/gap bullets for every job
"""

import math
import statistics
from collections import Counter
from datetime import date

import click
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from targetfit import scoring
from targetfit.config import load_config
from targetfit.storage import db
from targetfit.storage.io import load_cv


console = Console()


# ── Helpers ─────────────────────────────────────────────────────────────────

def _score_bar(score: float, width: int = 8) -> Text:
    """Return a coloured block-bar for a score in [0, 1]."""
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


def _score_colour(score: float) -> str:
    if score >= 0.85:
        return "bold green"
    if score >= 0.70:
        return "bold yellow"
    if score >= 0.55:
        return "yellow"
    return "red"


def _histogram(scores: list[float], width: int = 40) -> str:
    """Return a simple ASCII histogram for a list of scores."""
    if not scores:
        return "(no data)"
    buckets = 10
    lo, hi = 0.0, 1.0
    step = (hi - lo) / buckets
    counts = [0] * buckets
    for s in scores:
        idx = min(int((s - lo) / step), buckets - 1)
        counts[idx] += 1
    max_count = max(counts) or 1
    bar_height = 5
    lines = []
    for row in range(bar_height, 0, -1):
        line = ""
        for c in counts:
            filled = math.ceil(c / max_count * bar_height)
            line += "█   " if filled >= row else "    "
        lines.append(line)
    axis = "".join(f"{lo + i * step:.1f} " for i in range(buckets))
    lines.append(axis)
    return "\n".join(lines)


# ── Panels ───────────────────────────────────────────────────────────────────

def _render_header(jobs: list[dict], cv_snippet: str) -> None:
    today = date.today().isoformat()
    total = len(jobs)
    companies = len({j.get("company") for j in jobs if j.get("company")})

    scores = [float(j.get("final_score") or j.get("vector_score") or 0) for j in jobs]
    avg = statistics.mean(scores) if scores else 0.0
    top = max(scores) if scores else 0.0

    info = Text()
    info.append(f"  Date       ", style="dim")
    info.append(f"{today}\n", style="cyan")
    info.append(f"  Matches    ", style="dim")
    info.append(f"{total} jobs", style="bold white")
    info.append(f"  across  ", style="dim")
    info.append(f"{companies} companies\n", style="bold white")
    info.append(f"  Best score ", style="dim")
    info.append(f"{top:.2f}", style=_score_colour(top))
    info.append(f"   avg ", style="dim")
    info.append(f"{avg:.2f}\n", style=_score_colour(avg))
    info.append(f"  CV         ", style="dim")
    info.append(cv_snippet[:70] + ("…" if len(cv_snippet) > 70 else ""), style="italic dim")

    console.print(Panel(info, title="[bold cyan]🎯 targetfit[/bold cyan]", border_style="cyan"))


def _render_table(jobs: list[dict], show_detail: bool) -> None:
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
    table.add_column("Score", min_width=14)
    table.add_column("Link", min_width=20, max_width=28)

    for idx, job in enumerate(jobs, start=1):
        company  = job.get("company") or "—"
        title    = job.get("title")   or "—"
        location = job.get("location") or "—"
        url      = job.get("url")
        score    = float(job.get("final_score") or job.get("vector_score") or 0)

        if url:
            from urllib.parse import urlparse
            try:
                domain = urlparse(url).netloc.replace("www.", "") or url[:24]
            except Exception:
                domain = url[:24]
            link_text = Text()
            link_text.append("↗ " + domain[:24], style=f"link {url} cyan")
        else:
            link_text = Text("—", style="dim")
        table.add_row(
            str(idx),
            company,
            title,
            location,
            _score_bar(score),
            link_text,
        )

        if show_detail:
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
                table.add_row("", "", detail, "", "", "", end_section=True)

    console.print(table)


def _render_breakdown(jobs: list[dict]) -> None:
    scores = [float(j.get("final_score") or j.get("vector_score") or 0) for j in jobs]

    # Company breakdown
    by_company: dict[str, list[float]] = {}
    for j in jobs:
        c = j.get("company") or "Unknown"
        s = float(j.get("final_score") or j.get("vector_score") or 0)
        by_company.setdefault(c, []).append(s)

    company_table = Table(box=box.SIMPLE, header_style="dim", show_header=True, expand=False)
    company_table.add_column("Company", style="bold white", min_width=20)
    company_table.add_column("Roles", justify="right", style="cyan", width=5)
    company_table.add_column("Best match", min_width=18)

    for company, sc_list in sorted(by_company.items(), key=lambda kv: -max(kv[1])):
        company_table.add_row(company, str(len(sc_list)), _score_bar(max(sc_list), width=10))

    # Gap frequency
    all_gaps: list[str] = []
    for j in jobs:
        all_gaps.extend(j.get("gaps") or [])
    gap_counts = Counter(all_gaps).most_common(8)

    gap_table = Table(box=box.SIMPLE, header_style="dim", show_header=True, expand=False)
    gap_table.add_column("Common skill gap", style="white", min_width=28)
    gap_table.add_column("Frequency", justify="right", style="red", width=9)
    for gap, cnt in gap_counts:
        gap_table.add_row(gap, str(cnt))

    console.print(Rule("[dim]Breakdown[/dim]", style="dim"))
    if gap_counts:
        console.print(Columns([company_table, gap_table], equal=False, expand=True))
    else:
        console.print(company_table)

    # Score histogram
    hist_text = Text("\n" + _histogram(scores), style="dim")
    console.print(Panel(hist_text, title="[dim]Score distribution[/dim]", border_style="dim"))


# ── CLI entry point ──────────────────────────────────────────────────────────

@click.command()
@click.option("--top", default=15, show_default=True, help="Number of matches to show.")
@click.option("--threshold", default=None, type=float, help="Override score_threshold from config.")
@click.option("--llm-score", "use_llm_score", is_flag=True, default=False,
              help="Enable LLM scoring for richer match details (slower).")
@click.option("--detail", is_flag=True, default=False,
              help="Show match reasons and gaps inline in the table.")
@click.option("--breakdown/--no-breakdown", default=True, show_default=True,
              help="Show company breakdown and score histogram.")
def main(top: int, threshold: float | None, use_llm_score: bool,
         detail: bool, breakdown: bool) -> None:
    """Display job match results in a rich terminal layout."""
    config = load_config()
    cv_text = load_cv()

    if not cv_text:
        console.print("[red]CV not found at data/cv.txt. Add your CV first.[/red]")
        raise SystemExit(1)

    if threshold is not None:
        config = dict(config)
        config["score_threshold"] = threshold
    config = dict(config)
    config["top_k"] = top * 2  # fetch extra candidates before filtering

    with console.status("[cyan]Querying database…[/cyan]", spinner="dots"):
        candidates = db.query_similar_jobs(cv_text, config=config)

    if not candidates:
        console.print("[yellow]No candidates found. Run [bold]python cli.py index[/bold] first.[/yellow]")
        raise SystemExit(0)

    ranked = scoring.rank_by_vector(candidates)

    if use_llm_score:
        with console.status(f"[cyan]LLM scoring top {top} candidates…[/cyan]", spinner="dots"):
            top_vec = ranked[:top]
            scored = scoring.rank_by_llm(top_vec, cv=cv_text, config=config)
            ranked = scoring.apply_combined_scores(scored)
    else:
        for j in ranked:
            j["final_score"] = j.get("vector_score") or 0.0

    filtered = scoring.filter_by_threshold(ranked, config=config)[:top]

    if not filtered:
        console.print(
            f"[yellow]No jobs above threshold {config.get('score_threshold')}. "
            f"Try [bold]--threshold 0.5[/bold] to lower it.[/yellow]"
        )
        raise SystemExit(0)

    # ── render ──────────────────────────────────────────────────────────────
    cv_snippet = cv_text.strip().splitlines()[0] if cv_text.strip() else ""
    _render_header(filtered, cv_snippet)
    _render_table(filtered, show_detail=detail or use_llm_score)
    if breakdown:
        _render_breakdown(filtered)


if __name__ == "__main__":
    main()

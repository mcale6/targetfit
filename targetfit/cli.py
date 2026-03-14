import click

from targetfit import scoring
from targetfit.config import load_config
from targetfit.ingestion import scrape
from targetfit.ingestion.ats_api import detect_ats
from targetfit.log import setup_logger
from targetfit.nlp import cv_parser
from targetfit.storage import db
from targetfit.storage.io import (
    add_company_to_csv,
    load_all_company_jobs,
    load_companies,
    load_cv,
    save_company_jobs,
)
from targetfit.viz import main as viz_main


logger = setup_logger(__name__)


@click.group()
def cli() -> None:
    """targetfit CLI."""


@cli.command()
@click.option(
    "--companies",
    default=None,
    help="Path to CSV file with columns: company, url, search_url (optional)",
)
@click.option(
    "--company",
    "company_filters",
    multiple=True,
    help="Only scrape these companies (by name); can be passed multiple times.",
)
@click.option(
    "--query",
    "query_override",
    multiple=True,
    help="Search query to use (can be passed multiple times; e.g. --query 'data scientist' --query 'ML engineer').",
)
@click.option(
    "--no-cv-parse",
    "skip_cv_parse",
    is_flag=True,
    default=False,
    help="Skip CV parsing and scrape landing pages without a search query.",
)
def fetch(
    companies: str | None,
    company_filters: tuple[str, ...],
    query_override: tuple[str, ...],
    skip_cv_parse: bool,
) -> None:
    """Scrape careers pages and write per-company JSON files under data/jobs/.

    Before scraping, the CV is analysed by Ollama to extract the best search
    query.  That query is used with each company's ATS to hit real results pages
    instead of generic landing pages.  Pass --no-cv-parse to skip this step.
    """
    config = load_config()
    company_list = load_companies(companies)
    logger.info("Running fetch from %s with %d companies", companies or "(default)", len(company_list))

    if not company_list:
        click.echo("No companies found in CSV.")
        return

    # Optionally filter by specific company names.
    if company_filters:
        filters = {c.lower() for c in company_filters}
        logger.info("Applying company filters: %s", ", ".join(sorted(filters)))
        company_list = [
            c for c in company_list if c.get("company", "").lower() in filters
        ]

    if not company_list:
        click.echo("No companies matched the requested filters.")
        return

    # ── Extract search terms from CV ─────────────────────────────────────
    search_terms = None
    if not skip_cv_parse:
        cv_text = load_cv()
        if not cv_text:
            click.echo(
                "Warning: data/cv.txt not found — scraping landing pages without search query.\n"
                "Add your CV to data/cv.txt for targeted search, or use --no-cv-parse to silence this."
            )
        else:
            if query_override:
                # Use manual queries (optionally combined with CV analysis later).
                search_terms = cv_parser.SearchTerms(
                    job_titles=list(query_override),
                    queries=list(query_override),
                )
                logger.info(
                    "Using %d manual query override(s): %s",
                    len(query_override),
                    ", ".join(repr(q) for q in query_override),
                )
            else:
                click.echo("Analysing CV to extract search terms…")
                search_terms = cv_parser.extract_search_terms(cv_text, config)

            if search_terms:
                click.echo(
                    f"Search queries ({len(search_terms.queries)}): "
                    f"{', '.join(repr(q) for q in search_terms.queries)}"
                )
    elif query_override:
        # --no-cv-parse but explicit queries given — use them directly.
        search_terms = cv_parser.SearchTerms(
            job_titles=list(query_override),
            queries=list(query_override),
        )

    # ── Scrape ────────────────────────────────────────────────────────────
    all_jobs = scrape.fetch_all(company_list, config=config, search_terms=search_terms)

    # Persist jobs split by company.
    by_company: dict[str, list[dict]] = {}
    for job in all_jobs:
        c = (job.get("company") or "Unknown").strip()
        by_company.setdefault(c, []).append(job)

    for company, jobs in by_company.items():
        path = save_company_jobs(company, jobs)
        logger.info("Wrote %d jobs for %s to %s", len(jobs), company, path)

    logger.info("Fetch completed: %d companies, %d jobs extracted", len(company_list), len(all_jobs))
    click.echo(f"Fetched {len(company_list)} companies, extracted {len(all_jobs)} jobs into data/jobs/*.json.")


@cli.command()
def index() -> None:
    """Embed and index jobs + CV into DuckDB."""
    config = load_config()
    jobs = load_all_company_jobs()
    cv_text = load_cv()

    if not jobs:
        click.echo("No jobs found in data/jobs/*.json. Run 'fetch' first.")
        logger.warning("index: no jobs found in data/jobs/*.json")
        return
    if not cv_text:
        click.echo("CV text not found in data/cv.txt.")
        logger.warning("index: CV text not found in data/cv.txt")
        return

    logger.info("Indexing %d jobs into %s", len(jobs), config.get("db_path"))
    db.upsert_jobs(jobs, config=config)
    db.upsert_cv(cv_text, config=config)
    logger.info("Index completed")
    click.echo(f"Indexed {len(jobs)} jobs into {config.get('db_path')}.")


@cli.command()
@click.option(
    "--llm-score",
    "use_llm_score",
    is_flag=True,
    default=False,
    help="Enable slower but richer LLM scoring.",
)
@click.option(
    "--top",
    default=10,
    show_default=True,
    help="Number of results to show.",
)
def match(use_llm_score: bool, top: int) -> None:
    """Retrieve best-matching jobs for the current CV."""
    config = load_config()
    cv_text = load_cv()
    if not cv_text:
        click.echo("CV text not found in data/cv.txt.")
        return

    logger.info("Running match (top=%d, llm_score=%s)", top, use_llm_score)

    # override top_k for this run
    config = dict(config)
    config["top_k"] = top

    candidates = db.query_similar_jobs(cv_text, config=config)
    if not candidates:
        click.echo("No candidates found in database. Run 'index' first.")
        logger.warning("match: no candidates found in database")
        return

    ranked = scoring.rank_by_vector(candidates)
    logger.info("match: %d candidates after vector ranking", len(ranked))

    if use_llm_score:
        top_vec = ranked[:top]
        logger.info("match: running LLM scoring for top %d candidates", len(top_vec))
        scored = scoring.rank_by_llm(top_vec, cv=cv_text, config=config)
        ranked = scoring.apply_combined_scores(scored)
    else:
        # when using vector only, final_score == vector_score
        for j in ranked:
            j["final_score"] = j.get("vector_score") or 0.0

    filtered = scoring.filter_by_threshold(ranked, config=config)
    logger.info(
        "match: %d jobs above threshold %.2f",
        len(filtered),
        float(config.get("score_threshold", 0.65)),
    )
    output = scoring.format_results(filtered)
    click.echo(output)


@cli.command()
def inspect() -> None:
    """Print all jobs in DB as a simple table."""
    config = load_config()
    conn = db.get_connection(config)
    db.init_schema(conn, config)
    jobs = db.get_all_jobs(conn)

    if not jobs:
        click.echo("No jobs in database.")
        return

    lines = []
    for job in jobs:
        lines.append(
            f"{job.get('company','')} | {job.get('title','')} | "
            f"{job.get('location','')} | {job.get('inserted_at')}"
        )
    click.echo("\n".join(lines))


@cli.command("add")
@click.argument("company")
@click.argument("url")
@click.option(
    "--search-url",
    default=None,
    help="Optional search URL template with {query} placeholder.",
)
@click.option(
    "--companies",
    "csv_path",
    default=None,
    help="Path to companies CSV file.",
)
def add_company(company: str, url: str, search_url: str | None, csv_path: str | None) -> None:
    """Add a company to the companies CSV.

    Automatically detects if the URL uses a known ATS platform with a
    free API (Greenhouse, Lever, Ashby, SmartRecruiters) and reports it.

    \b
    Examples:
        targetfit add "Lila Sciences" "https://job-boards.greenhouse.io/lilasciences"
        targetfit add "CuspAI" "https://jobs.ashbyhq.com/cuspai"
        targetfit add "Recursion" "https://www.recursion.com/careers"
    """
    existing = load_companies(csv_path)
    for entry in existing:
        if entry.get("company", "").lower() == company.lower():
            click.echo(f"'{company}' already exists.")
            return

    ats = detect_ats(url)
    if ats:
        click.echo(
            f"Detected {ats.platform.title()} ATS (org: {ats.org_id}) "
            f"— will use fast API fetch instead of scraping."
        )
    else:
        click.echo("No known ATS API detected — will use Playwright scraping.")

    add_company_to_csv(company, url, search_url=search_url, csv_path=csv_path)
    click.echo(f"Added '{company}' -> {url}")

    updated = load_companies(csv_path)
    click.echo(f"Total companies: {len(updated)}")


@cli.command("companies")
@click.option(
    "--companies",
    "csv_path",
    default=None,
    help="Path to companies CSV file.",
)
@click.option("--ats-only", is_flag=True, help="Show only companies with a detected ATS API.")
def list_companies(csv_path: str | None, ats_only: bool) -> None:
    """List all companies in the companies CSV."""
    entries = load_companies(csv_path)
    if not entries:
        click.echo("No companies found.")
        return

    lines: list[str] = []
    for entry in entries:
        name = entry.get("company", "")
        url = entry.get("url", "")
        ats = detect_ats(url)
        tag = f" [{ats.platform}]" if ats else ""

        if ats_only and not ats:
            continue

        lines.append(f"  {name:<30} {url}{tag}")

    if not lines:
        click.echo("No matching companies found.")
        return

    header = f"{'Company':<32} URL"
    click.echo(header)
    click.echo("-" * len(header))
    click.echo("\n".join(lines))
    click.echo(f"\n{len(lines)} companies listed.")


@cli.command("remove")
@click.argument("company")
@click.option(
    "--companies",
    "csv_path",
    default=None,
    help="Path to companies CSV file.",
)
def remove_company(company: str, csv_path: str | None) -> None:
    """Remove a company from the companies CSV."""
    from targetfit.storage.io import remove_company_from_csv

    removed = remove_company_from_csv(company, csv_path=csv_path)
    if removed:
        click.echo(f"Removed '{company}'.")
    else:
        click.echo(f"'{company}' not found.")


# Re-export the rich visualisation from viz.py as a subcommand:
cli.add_command(viz_main, "viz")


if __name__ == "__main__":
    cli()

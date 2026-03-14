import click

import db
import scoring
import scrape
from utils import (
    load_companies,
    load_config,
    load_cv,
    load_all_company_jobs,
    save_company_jobs,
    setup_logger,
)
from viz import main as viz_main


logger = setup_logger(__name__)


@click.group()
def cli() -> None:
    """targetfit CLI."""


@cli.command()
@click.option(
    "--companies",
    default="data/companies.csv",
    help="Path to CSV file with columns: company,url",
)
@click.option(
    "--company",
    "company_filters",
    multiple=True,
    help="Only scrape these companies (by name) from the CSV; can be passed multiple times.",
)
def fetch(companies: str, company_filters: tuple[str, ...]) -> None:
    """Scrape careers pages and write per-company JSON files under data/jobs/.

    Uses ScrapeGraphAI + Ollama to scrape each careers page and extract
    structured job listings in a single pass — fully local, zero API cost.
    """
    config = load_config()
    company_list = load_companies(companies)
    logger.info("Running fetch from %s with %d companies", companies, len(company_list))

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

    # ScrapeGraphAI handles both scraping AND extraction in one step.
    all_jobs = scrape.fetch_all(company_list, config=config)

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


# Re-export the rich visualisation from viz.py as a subcommand:
cli.add_command(viz_main, "viz")


if __name__ == "__main__":
    cli()

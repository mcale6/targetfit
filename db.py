import hashlib
from typing import Any, Dict, List

import duckdb

from llm import get_embedding
from utils import setup_logger


logger = setup_logger(__name__)


def get_connection(config: Dict[str, Any]) -> duckdb.DuckDBPyConnection:
    """Connect to DuckDB database and load VSS extension."""
    db_path = config.get("db_path", "data/targetfit.duckdb")
    logger.info("Connecting to DuckDB at %s", db_path)
    conn = duckdb.connect(db_path)
    try:
        conn.execute("LOAD vss;")
    except duckdb.Error as exc:
        logger.warning("Failed to load vss extension: %s", exc)
    return conn


def init_schema(conn: duckdb.DuckDBPyConnection, config: Dict[str, Any]) -> None:
    """Create schema if not exists."""
    dims = int(config.get("embedding_dims", 768))
    logger.debug("Initializing schema with embedding_dims=%d", dims)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id          VARCHAR PRIMARY KEY,
            company     VARCHAR,
            title       VARCHAR,
            location    VARCHAR,
            url         VARCHAR,
            description TEXT,
            date_posted VARCHAR,
            inserted_at TIMESTAMP DEFAULT now()
        );
        """
    )

    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS embeddings (
            job_id      VARCHAR PRIMARY KEY REFERENCES jobs(id),
            embedding   FLOAT[{dims}]
        );
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cv (
            id          VARCHAR PRIMARY KEY,
            embedding   FLOAT[768]
        );
        """
    )

    # HNSW index (ignore if it already exists)
    try:
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS emb_idx
            ON embeddings USING hnsw(embedding)
            WITH (metric = 'cosine');
            """
        )
    except duckdb.Error as exc:
        logger.warning("Failed to create HNSW index: %s", exc)


def job_id(job: Dict[str, Any]) -> str:
    """Deterministic ID based on company, title, and url."""
    key = f"{job.get('company','')}|{job.get('title','')}|{job.get('url','')}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return digest[:16]


def upsert_job(
    conn: duckdb.DuckDBPyConnection, job: Dict[str, Any], embedding: List[float]
) -> None:
    """Upsert a single job and its embedding."""
    jid = job_id(job)

    conn.execute(
        """
        INSERT OR REPLACE INTO jobs (
            id, company, title, location, url, description, date_posted
        ) VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        [
            jid,
            job.get("company"),
            job.get("title"),
            job.get("location"),
            job.get("url"),
            job.get("description"),
            job.get("date_posted"),
        ],
    )

    conn.execute(
        "INSERT OR REPLACE INTO embeddings (job_id, embedding) VALUES (?, ?);",
        [jid, embedding],
    )


def upsert_jobs(jobs: List[Dict[str, Any]], config: Dict[str, Any]) -> None:
    """Embed and upsert a batch of jobs in a single transaction."""
    if not jobs:
        logger.info("No jobs to upsert.")
        return

    conn = get_connection(config)
    init_schema(conn, config)

    logger.info("Upserting %d jobs into database", len(jobs))
    with conn:
        for job in jobs:
            desc = job.get("description") or ""
            embedding = get_embedding(desc, config=config)
            upsert_job(conn, job, embedding)

    logger.info("Inserted/updated %d jobs into %s", len(jobs), config.get("db_path"))


def upsert_cv(cv_text: str, config: Dict[str, Any]) -> None:
    """Embed CV text and store in cv table."""
    if not cv_text:
        logger.warning("CV text is empty; skipping upsert_cv")
        return

    conn = get_connection(config)
    init_schema(conn, config)

    logger.info("Upserting CV embedding")
    embedding = get_embedding(cv_text, config=config)
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO cv (id, embedding) VALUES ('main', ?);",
            [embedding],
        )


def query_similar_jobs(cv_text: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Query jobs most similar to the CV via HNSW ANN."""
    if not cv_text:
        return []

    top_k = int(config.get("top_k", 10))
    conn = get_connection(config)
    init_schema(conn, config)

    logger.info("Querying top %d similar jobs", top_k)
    cv_embedding = get_embedding(cv_text, config=config)

    query = """
        SELECT
            j.id,
            j.company,
            j.title,
            j.location,
            j.url,
            j.description,
            j.date_posted,
            array_cosine_similarity(e.embedding, ?::FLOAT[768]) AS vector_score
        FROM embeddings e
        JOIN jobs j ON e.job_id = j.id
        ORDER BY vector_score DESC
        LIMIT ?;
    """
    result = conn.execute(query, [cv_embedding, top_k]).fetchall()
    cols = [c[0] for c in conn.description]

    jobs: List[Dict[str, Any]] = []
    for row in result:
        job = dict(zip(cols, row))
        jobs.append(job)
    logger.info("Query returned %d jobs", len(jobs))
    return jobs


def get_all_jobs(conn: duckdb.DuckDBPyConnection) -> List[Dict[str, Any]]:
    """Return all jobs ordered by insertion time."""
    rows = conn.execute(
        "SELECT * FROM jobs ORDER BY inserted_at DESC;"
    ).fetchall()
    cols = [c[0] for c in conn.description]
    jobs = [dict(zip(cols, r)) for r in rows]
    logger.info("Loaded %d jobs from database", len(jobs))
    return jobs


def drop_all(conn: duckdb.DuckDBPyConnection) -> None:
    """Drop all tables, allowing full re-index from scratch."""
    logger.warning("Dropping all tables (embeddings, jobs, cv)")
    conn.execute("DROP TABLE IF EXISTS embeddings;")
    conn.execute("DROP TABLE IF EXISTS jobs;")
    conn.execute("DROP TABLE IF EXISTS cv;")


"""Storage — DuckDB vector store and file I/O."""

from targetfit.storage.db import (
    drop_all,
    get_all_jobs,
    get_connection,
    init_schema,
    query_similar_jobs,
    upsert_cv,
    upsert_jobs,
)
from targetfit.storage.io import (
    add_company_to_csv,
    load_all_company_jobs,
    load_companies,
    load_cv,
    remove_company_from_csv,
    save_company_jobs,
    save_jobs,
)

__all__ = [
    "add_company_to_csv",
    "drop_all",
    "get_all_jobs",
    "get_connection",
    "init_schema",
    "load_all_company_jobs",
    "load_companies",
    "load_cv",
    "query_similar_jobs",
    "remove_company_from_csv",
    "save_company_jobs",
    "save_jobs",
    "upsert_cv",
    "upsert_jobs",
]

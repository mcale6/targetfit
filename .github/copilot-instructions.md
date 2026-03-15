## Quick Onboarding for AI Coding Agents

This project (targetfit) is a local, Ollama-backed CV → job matching toolkit.
Read these concise cues to be immediately productive and make safe, useful edits.

- **Big picture**: `data/companies.csv` → scrape (ATS or Playwright) → save `data/jobs/*.json` → `targetfit index` embeds jobs + CV into `data/targetfit.duckdb` (DuckDB + VSS/HNSW) → `targetfit match` finds candidates and optionally re-scores with an LLM.

- **Key files to read first**: `README.md`, `targetfit/cli.py` (CLI entrypoints and flags), `targetfit/config.py` (config loader, `PROJECT_ROOT`), `prompts.md` (LLM agent prompts), `targetfit/nlp/llm.py` (Ollama wrapper & parsing logic), `targetfit/nlp/cv_parser.py` (CV→SearchTerms), `targetfit/storage/db.py` (DuckDB schema + embeddings), `targetfit/ingestion/scrape.py` (scraping flow).

- **LLM integration specifics**:
  - Uses a local Ollama instance (default `http://localhost:11434`). Endpoints: `/api/generate` and `/api/embeddings` (see `llm.call_ollama` and `llm.get_embedding`).
  - `prompts.md` contains agent sections titled `## [TAG]`; code extracts the system prompt by section name (example: `[SCORER]` used in `llm.score_job`).
  - Many LLM calls use `json_mode=True` to request strict JSON, but the code robustly handles non-JSON (see `parse_json_response`, `_salvage_score_payload`, and repair fallback via a smaller model).

- **Embedding & DB patterns**:
  - Embeddings dims configured in `config.yaml` (`embedding_dims`) and enforced/normalised in `llm.get_embedding`.
  - DuckDB schema created in `targetfit/storage/db.py`. The HNSW index is named `emb_idx` and VSS is loaded at runtime (`LOAD vss;`). Use the `job_id()` deterministic 16-char hash to identify jobs.
  - `embedding_text_for_job()` concatenates title/company/location/description — patch fixes should preserve that stable text format to avoid changing search semantics.

- **CV parsing & search-term generation**:
  - `targetfit/nlp/cv_parser.py` returns a `SearchTerms` dataclass with `job_titles`, `domains`, `skills`, `queries`. `url_builder` expects `queries` to be URL-friendly short strings.
  - Fallback: if the LLM fails, `_DEFAULT_TERMS` is used so pipeline continues.

- **CLI developer workflows**:
  - Typical local run: `python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]" && playwright install chromium`.
  - Ensure Ollama models are pulled and Ollama is running (see `README.md` commands). Common CLI commands:
    - `targetfit fetch` (scrape all companies; uses CV unless `--no-cv-parse`)
    - `targetfit index` (embed jobs + CV into DuckDB)
    - `targetfit match --top N [--llm-score]` (vector search ± LLM re-score)

- **Patterns & conventions to follow**:
  - Prefer using `load_config()` to access configuration values (never hard-code paths).
  - Respect graceful fallbacks: many functions catch LLM/IO errors and return defaults — preserve those flows.
  - CLI uses `click` and prints user-facing messages with `click.echo()`; non-user logs go through `targetfit.log.setup_logger`.
  - Data files: `data/cv.txt` (user CV), `data/companies.csv` (managed via `targetfit add`), `data/jobs/*.json` (scraped jobs), `data/targetfit.duckdb` (database). These are intentionally local and git-ignored.

- **Testing & debugging tips**:
  - To reproduce LLM parsing issues, run `cv_parser.extract_search_terms()` with a sample `data/cv.txt` and observe `parse_json_response` behaviour.
  - DuckDB issues: confirm VSS extension loads in `targetfit/storage/db.py` and that `hnsw_enable_experimental_persistence` is set. Use `duckdb.connect()` logs to debug.
  - Logs: increase verbosity via `targetfit.log.setup_logger(__name__)` settings (see `targetfit/log.py`).

- **When changing prompts or agents**:
  - Edit `prompts.md` sections. The code extracts the System prompt block using the heading `## [TAG]` and the fenced code block labeled `System prompt:` — keep that structure.

- **Safe edit checklist for PRs**:
  - Run `targetfit fetch` (or targeted `fetch --company`) only when Playwright and Ollama are available locally.
  - Run `targetfit index` after fetch to regenerate embeddings; be explicit about expected embedding dims if you change `config.yaml`.
  - Preserve JSON repair and salvage logic in `nlp/llm.py` when changing scoring prompts — it's critical for robustness.

If anything here is unclear or you want a shorter/longer variant (or examples added), tell me which sections to expand and I’ll iterate.

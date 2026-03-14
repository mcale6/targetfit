### targetfit

High-throughput screening for your next role.

targetfit lets you maintain a list of target companies, scrape their careers
pages, index all roles into a local DuckDB + vector index, and match your CV
against the entire job set using fast vector similarity plus optional LLM scoring.

Everything runs locally via **Ollama** — zero external API costs.

---

### Features

- **Company-centric pipeline**: manage your target list via `data/companies.csv` or the `add` / `remove` CLI commands.
- **ATS-aware fetching**: auto-detects Greenhouse, Lever, Ashby, and SmartRecruiters boards and hits their public APIs directly — fast and structured, no browser needed.
- **Playwright pagination**: for other career sites, renders pages in a headless browser, clicks through pagination (Next / Load More), and dismisses cookie overlays automatically.
- **Dual extraction**: tries structured HTML attributes first (`data-ph-at-*` / Phenom People), falls back to ScrapeGraphAI + Ollama LLM extraction.
- **CV-driven search**: parses your CV with Ollama to build targeted search queries so you hit real results pages, not generic landing pages.
- **Vector + LLM scoring**: fast cosine similarity via DuckDB HNSW, with optional richer LLM-based re-scoring.
- **Rich terminal UI**: colour-coded tables, score histograms, and per-company breakdowns via `viz`.
- **Fully local**: all LLM inference runs on your Ollama instance. No data leaves your machine.

---

### Repository layout

```text
targetfit/
├── config.yaml                        # model + DB configuration
├── prompts.md                         # LLM agent prompts (scorer, CV parser)
├── pyproject.toml                     # project metadata + dependencies
├── data/
│   ├── companies.csv                  # input: company, url, search_url
│   ├── cv.txt                         # your CV (plain text)
│   ├── jobs/                          # per-company JSON (e.g. roche.json)
│   └── targetfit.duckdb               # DuckDB database (git-ignored)
├── targetfit/                         # Python package
│   ├── __init__.py
│   ├── __main__.py                    # python -m targetfit
│   ├── cli.py                         # Click CLI (fetch, index, match, …)
│   ├── config.py                      # load_config(), PROJECT_ROOT
│   ├── log.py                         # coloured logger
│   ├── helpers.py                     # truncate()
│   ├── scoring.py                     # ranking, thresholding, formatting
│   ├── viz.py                         # Rich terminal dashboard
│   ├── ingestion/
│   │   ├── scrape.py                  # Playwright + ScrapeGraphAI
│   │   ├── ats_api.py                 # Greenhouse / Lever / Ashby / SmartRecruiters
│   │   └── url_builder.py             # search URL construction for 40+ ATS platforms
│   ├── nlp/
│   │   ├── llm.py                     # Ollama wrapper (scoring + embeddings)
│   │   └── cv_parser.py               # CV → SearchTerms
│   └── storage/
│       ├── db.py                      # DuckDB schema, upsert, vector search
│       └── io.py                      # CSV / JSON / CV file helpers
└── tests/
    └── __init__.py
```

---

### End-to-end flow

```text
             +----------------------+
             |  data/companies.csv  |
             +----------+-----------+
                        |
                        v
          ┌─────────────────────────────┐
          │  ATS detected?              │
          │  yes → ats_api (API call)   │
          │  no  → Playwright + LLM     │
          └─────────────┬───────────────┘
                        |
                        v
           save_company_jobs()  ──>  data/jobs/*.json
                        |
            +-----------+-----------+
            |                       |
            v                       v
   llm.get_embedding()    llm.get_embedding()
   (job descriptions)     (CV text from data/cv.txt)
            |                       |
            v                       v
     db.upsert_jobs()        db.upsert_cv()
            |                       |
            +-----------+-----------+
                        v
             data/targetfit.duckdb
     (jobs table + embeddings + HNSW index)
                        |
                        v
              db.query_similar_jobs()
                        |
                        v
              scoring.rank_by_vector()
                        |
       +----------------+------------------+
       |                                   |
       | --llm-score                       | vector-only
       v                                   v
 scoring.rank_by_llm()              final_score = vector_score
 scoring.apply_combined_scores()
       |                                   |
       +----------------+------------------+
                        v
            scoring.filter_by_threshold()
                        |
                        v
             Terminal output / viz dashboard
```

---

### Installation

```bash
git clone <repo-url> && cd targetfit
python -m venv .venv
source .venv/bin/activate      # macOS / Linux
pip install -e ".[dev]"        # installs the package + dev tools (pytest, ruff)
playwright install chromium    # headless browser for non-ATS career sites
```

You also need **Ollama** running locally with the models configured in `config.yaml`:

```bash
# Extraction + scoring
ollama pull gpt-oss:20b

# Fallback model
ollama pull gemma3:27b

# Embedding model
ollama pull snowflake-arctic-embed2
```

DuckDB is installed as a Python dependency; the VSS extension is loaded at runtime.

---

### Configuration

Edit `config.yaml` at the project root:

```yaml
extraction_model: gpt-oss:20b        # LLM for ScrapeGraphAI extraction
scoring_model: gpt-oss:20b           # LLM for CV-to-job scoring
fallback_model: gemma3:27b           # secondary model for robustness
ollama_url: http://localhost:11434
embedding_model: snowflake-arctic-embed2
embedding_dims: 768
db_path: data/targetfit.duckdb
score_threshold: 0.65                 # minimum final_score to display
top_k: 20                            # vector candidates before re-scoring
max_description_chars: 4000
headless: true                        # run Playwright headless
llm_max_tokens: 8192
location: Switzerland                 # used for search URL templates
```

---

### Typical session

```bash
# 1. Add your CV
cp ~/cv.txt data/cv.txt

# 2. Add companies (ATS platforms are auto-detected)
targetfit add "Lila Sciences" "https://job-boards.greenhouse.io/lilasciences"
targetfit add "Roche" "https://careers.roche.com/global/en/c/research-development-jobs"
targetfit add "CuspAI" "https://jobs.ashbyhq.com/cuspai"

# 3. Scrape + extract jobs → data/jobs/*.json
targetfit fetch

# 4. Scrape a single company
targetfit fetch --company Roche --no-cv-parse

# 5. Embed + index into DuckDB
targetfit index

# 6. Fast match (vector only)
targetfit match --top 15

# 7. Rich match (vector + LLM scoring)
targetfit match --top 15 --llm-score

# 8. Visual dashboard
targetfit viz --top 20 --detail
```

---

### CLI reference

| Command | Description |
|---|---|
| `targetfit fetch` | Scrape careers pages and write per-company JSON files under `data/jobs/`. Parses your CV to build search queries unless `--no-cv-parse` is passed. Use `--company` to target specific companies and `--query` to override search terms. |
| `targetfit index` | Embed all jobs and your CV via Ollama, upsert into DuckDB with HNSW vector index. |
| `targetfit match` | Retrieve best-matching jobs for your CV. Add `--llm-score` for LLM re-ranking, `--top N` to control result count. |
| `targetfit viz` | Rich terminal dashboard with colour-coded table, score histogram, and company breakdown. Supports `--detail`, `--llm-score`, `--threshold`. |
| `targetfit inspect` | Print all jobs in the database as a simple table. |
| `targetfit add COMPANY URL` | Add a company to `data/companies.csv`. Auto-detects ATS platform. |
| `targetfit remove COMPANY` | Remove a company from the CSV. |
| `targetfit companies` | List all companies. Use `--ats-only` to filter to those with a detected API. |

---

### Example output

See [example.md](example.md) for full terminal output from a real run, including:

- `targetfit fetch` — scraping 99 jobs from Roche with Playwright pagination
- `targetfit viz` — vector-only dashboard (fast)
- `targetfit viz --llm-score` — LLM-scored dashboard with match reasons and gaps per job

---

### Privacy and data

- Your **CV** and all **jobs** stay local (`data/cv.txt`, `data/jobs/*.json`, `data/targetfit.duckdb`).
- **No external API calls**: pages are fetched directly, all LLM inference runs on your local Ollama instance.
- `.gitignore` excludes your CV, the DuckDB file, and scraped job JSON.

### targetfit

High-throughput screening for your next role.

targetfit lets you maintain a small list of target companies, scrape their careers
pages, index all roles into a local DuckDB + vector index, and then match your CV
against the entire job set using fast vector similarity plus optional LLM scoring.

Everything runs locally via **Ollama** — zero external API costs.

---

### Features

- **Company-centric pipeline**: You control the list of companies via `data/companies.csv`.
- **Fully local**: Uses ScrapeGraphAI + Ollama for scraping and extraction, DuckDB + VSS for vector search.
- **Zero external APIs**: No external hosted LLM APIs. Everything is open source and runs locally.
- **Structured extraction**: Careers pages are scraped and turned into clean JSON job objects in one step.
- **Vector + LLM scoring**: Fast cosine similarity plus optional richer LLM-based assessment.
- **Single-file database**: Everything lives in `data/targetfit.duckdb`.

---

### Repository layout

```text
targetfit/
├── data/
│   ├── companies.csv          # input: company,url
│   ├── cv.txt                 # your CV (plain text)
│   ├── jobs/                  # per-company JSON files, e.g. google.json, microsoft.json
│   └── targetfit.duckdb       # DuckDB database (jobs + embeddings, ignored by git)
├── scrape.py                  # ScrapeGraphAI + Ollama: fetch + extract in one step
├── llm.py                     # Ollama wrapper (scoring + embeddings)
├── db.py                      # DuckDB + VSS schema and queries
├── scoring.py                 # ranking, thresholding, pretty printing
├── cli.py                     # command-line interface
├── utils.py                   # shared helpers (config, logging, IO)
├── config.yaml                # model + DB configuration
├── requirements.txt           # Python dependencies
└── AGENTS.md                  # prompts for LLM scoring
```

---

### End-to-end flow

1. **You specify companies** in `data/companies.csv`.
2. **ScrapeGraphAI scrapes + extracts** job listings from each careers page using your local Ollama model — scraping and structured extraction happen in a single pass, and results are written to `data/jobs/{company}.json`.
3. **Jobs + your CV are embedded** via Ollama and stored in DuckDB with a vector index.
4. **Matching**: your CV embedding is used to retrieve, (optionally) re-score, and display the best roles.

```text
              +----------------------+
              |  data/companies.csv  |
              +----------+-----------+
                         |
                         v
              scrape.fetch_all()
     (ScrapeGraphAI + Ollama — local)
                         |
                         v
      utils.save_company_jobs()  --->  data/jobs/*.json
                         |
                         v
   +---------------------+------------------------+
   |                                               |
   |                                  +------------+------------+
   |                                  |    data/cv.txt (your   |
   |                                  |    CV as plain text)   |
   |                                  +------------+-----------+
   |                                               |
   v                                               v
llm.get_embedding()                      llm.get_embedding()
(jobs descriptions)                      (CV text)
   |                                               |
   v                                               v
db.upsert_jobs()                           db.upsert_cv()
   |                                               |
   +------------------------+----------------------+
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
       +--------------------+----------------------+
       |                                           |
       | if --llm-score enabled                    |
       v                                           v
scoring.rank_by_llm()                     (vector-only path)
scoring.apply_combined_scores()
       |
       v
scoring.filter_by_threshold()
       |
       v
scoring.format_results()
       |
       v
               Terminal output
```

---

### Installation

```bash
python -m venv .venv
source .venv/bin/activate  # on macOS/Linux
pip install -r requirements.txt
playwright install          # needed by ScrapeGraphAI for JS-rendered pages
```

You also need:

- **Ollama** running locally with the models you configured in `config.yaml`:
  ```bash
  # Extraction + scoring models
  ollama pull gpt-oss:20b

  # Optional fallback model for scoring
  ollama pull llama3.2:3b

  # Embedding model
  ollama pull snowflake-arctic-embed2
  ```
- **DuckDB** is pulled as a Python dependency; the VSS extension is loaded at runtime.

---

### Configuration

The default `config.yaml`:

```yaml
extraction_model: gpt-oss:20b
scoring_model: gpt-oss:20b
fallback_model: llama3.2:3b
ollama_url: http://localhost:11434
embedding_model: snowflake-arctic-embed2
embedding_dims: 768  # Verify dims if you switch to Arctic!
db_path: data/targetfit.duckdb
score_threshold: 0.65
top_k: 10
max_description_chars: 4000
headless: true
llm_max_tokens: 8192
```

- **extraction_model**: LLM used by ScrapeGraphAI to extract structured jobs from careers pages.
- **scoring_model**: LLM used by the SCORER agent (`llm.score_job`) for CV-to-job matching.
- **fallback_model**: optional secondary model you can use in the future for robustness (currently just documented).
- **embedding_model / embedding_dims**: embedding model + output dimension.
- **llm_max_tokens**: approximate context window size for the extraction model; passed to ScrapeGraphAI as `model_tokens` to silence warnings.
- **score_threshold**: minimum `final_score` for a job to be shown.
- **top_k**: number of vector candidates retrieved from DuckDB before any LLM re-scoring.
- **headless**: whether ScrapeGraphAI runs the browser in headless mode.

---

### Typical session

```bash
# 1. Populate companies
nano data/companies.csv
# company,url
# ACME Corp,https://acme.com/careers

# 2. Add your CV
nano data/cv.txt

# 3. Scrape + extract jobs → data/jobs/*.json
python cli.py fetch

# 4. Embed + index into DuckDB
python cli.py index

# 5. Inspect what was indexed
python cli.py inspect

# 6. Fast match (vector only)
python cli.py match --top 15

# 7. Rich match (vector + LLM scoring)
python cli.py match --top 15 --llm-score
```

---

### CLI commands

- **`python cli.py fetch`**:
  Loads `config.yaml` and `data/companies.csv`, scrapes each careers page
  via ScrapeGraphAI + Ollama, extracts structured jobs, and writes per-company files
  under `data/jobs/*.json`.

- **`python cli.py index`**:
  Loads `config.yaml`, all `data/jobs/*.json`, and `data/cv.txt`, embeds each job description
  and your CV, and upserts everything into `data/targetfit.duckdb`.

- **`python cli.py match [--llm-score] [--top N]`**:
  Loads your CV and config, runs a vector similarity query in DuckDB, optionally
  re-scores top candidates with `llm.score_job`, applies the combined score and
  threshold, and prints formatted matches.

- **`python cli.py inspect`**:
  Prints a simple table of all jobs in the DuckDB database
  (`company | title | location | inserted_at`).

---

### Privacy and data

- Your **CV** and all **jobs** are stored locally only (`data/cv.txt`, `data/jobs/*.json`,
  and `data/targetfit.duckdb`).
- **Zero external API calls**: ScrapeGraphAI fetches pages directly (no proxy service),
  and all LLM inference runs on your local Ollama instance.
- The repository `.gitignore` excludes your CV, the DuckDB file, and generated jobs JSON.

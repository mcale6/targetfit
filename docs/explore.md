# targetfit — Exploration Notes

A running document covering architecture decisions, scraping internals, vector search math, and future directions discussed during development.

---

## 1. ScrapeGraphAI — What It Is and How It Works

### Role in targetfit

ScrapeGraphAI is used as the **last-resort fallback** in the extraction pipeline inside `ingestion/scrape.py`. The resolution order for any company's careers page is:

1. Direct ATS JSON API (Greenhouse, Lever, Ashby, SmartRecruiters) — fastest, zero LLM cost
2. Phenom People `data-*` HTML attribute extraction — fast, zero LLM cost
3. **ScrapeGraphAI `SmartScraperGraph`** — slowest, LLM cost, but handles anything

Only `SmartScraperGraph` is used. The other three ScrapeGraphAI graph types (`SearchGraph`, `SpeechGraph`, `ScriptCreatorGraph`) are not currently wired in.

### How ScrapeGraphAI works internally

ScrapeGraphAI builds a **pipeline of nodes** (a "graph") where each node handles one step:

**Step 1 — HTML cleaning (rule-based, hardcoded)**
BeautifulSoup strips `<script>`, `<style>`, `<nav>`, `<footer>`, hidden elements, and HTML comments. Attributes like `class`, `id`, and `style` are removed. The output is compressed plain text or minimal HTML. This step is entirely deterministic — no LLM involved.

**Step 2 — Chunking**
If the cleaned text exceeds the model's context window (`llm_max_tokens` in `config.yaml`, default 8192), it splits on natural boundaries (paragraphs, newlines) using a sliding window with overlap to avoid losing context at chunk edges.

**Step 3 — LLM extraction**
Each chunk is sent to Ollama with the `EXTRACT_PROMPT` defined in `scrape.py`. The LLM reads the plain text the way a human would and returns structured JSON. Because all HTML markup is already stripped, the model is doing reading comprehension, not HTML parsing — which is why it's resilient to site redesigns.

**Step 4 — Merge (if chunked)**
Partial results from each chunk are merged into one combined jobs list.

The key insight: ScrapeGraphAI is essentially a managed wrapper around clean → chunk → prompt → parse. The actual intelligence is in the LLM reading the visible text, not in any clever HTML analysis.

### Current configuration (`_build_graph_config`)

```
model:           extraction_model from config.yaml (default gpt-oss:20b)
embedding_model: embedding_model from config.yaml
base_url:        ollama_url (default http://localhost:11434)
temperature:     0
format:          json
headless:        true
```

Everything runs locally via Ollama — no external API calls.

### One rough edge

ScrapeGraphAI produces verbose console output that bleeds into the terminal. The codebase works around this with `contextlib.redirect_stdout` / `redirect_stderr` — a sign this is a somewhat unruly dependency.

---

## 2. Planned Improvements — Option 2 + Option 3

### Option 3: Pydantic structured output schema

**Problem**: `SmartScraperGraph` returns free-form JSON that occasionally breaks. The existing multi-stage JSON repair logic in `nlp/llm.py` handles this for the scoring pipeline, but the extraction path has no equivalent safety net.

**Solution**: Define a Pydantic schema and pass it to ScrapeGraphAI. ScrapeGraphAI natively supports Pydantic schemas — when provided, it enforces the output shape rather than free-form JSON.

```python
from pydantic import BaseModel

class JobListing(BaseModel):
    title: str
    location: str | None = None
    url: str | None = None
    date_posted: str | None = None
    description: str | None = None

class JobListings(BaseModel):
    jobs: list[JobListing]
```

This schema gets passed to `SmartScraperGraph(schema=JobListings, ...)`. Output is always validated against the model — no repair needed. This is a small, self-contained change and should be implemented first.

### Option 2: ScriptCreatorGraph cache layer

**Problem**: Every time a company's careers page is scraped via LLM fallback, it pays the full LLM extraction cost even if the site hasn't changed since the last run.

**Idea**: Use `ScriptCreatorGraph` to **generate a reusable BeautifulSoup scraping script once**, cache it per company, and re-run that script on subsequent fetches — no LLM needed on repeat visits.

**Cache location**: `data/scrape_scripts/{company_slug}.py`

**New extraction flow in `_extract_with_llm()`**:

```
1. Check cache: data/scrape_scripts/{company_slug}.py
   ├── exists → run cached script on current HTML
   │   ├── success → return jobs  ✓  (fast path, no LLM)
   │   └── fails  → delete stale cache, continue
   │
2. ScriptCreatorGraph (generate + cache)
   ├── success → save script → execute it → return jobs  ✓
   └── fails   → continue
   │
3. SmartScraperGraph (current behavior, unchanged fallback)
   ├── success → return jobs  ✓
   └── fails   → return []
```

SmartScraperGraph stays as the **final fallback** — nothing is removed, only a layer added on top.

**Script execution** uses `exec()` on the generated Python with a sandboxed namespace. Output is validated against `JobListings` (from Option 3) before being returned.

**Staleness handling**: if the cached script throws any exception on new HTML (site redesigned), the cache file is deleted and the pipeline falls through to regenerate. An optional `--clear-cache` CLI flag could force regeneration.

**Files to change**:

| File | Change |
|------|--------|
| `targetfit/ingestion/scrape.py` | Add Pydantic models; new functions `_get_cached_script`, `_save_script`, `_run_cached_script`, `_generate_script`; modify `_extract_with_llm` signature to accept `company_slug` |
| `targetfit/config.py` | Add `SCRAPE_SCRIPTS_DIR` path constant |
| `config.yaml` | Add `use_script_cache: true` toggle |

**One API change**: `_extract_with_llm(html, config)` → `_extract_with_llm(html, config, company_slug)`. The caller `scrape_and_extract()` already has the company name — just needs to slugify and pass it through.

### Test plan

**Test A — ScriptCreatorGraph vs SmartScraperGraph**:
- Take 3–4 companies scraped via LLM fallback (not ATS API)
- Capture their raw HTML
- Run both extraction paths on the same HTML
- Compare: job count, field completeness, first-run time, cached re-run time

**Test B — Pydantic schema vs free-form JSON**:
- Same HTML samples
- Run `SmartScraperGraph` with and without `schema=JobListings`
- Check: does the schema version ever fail? Does free-form ever produce invalid JSON the schema version wouldn't?

**Unit tests** (`tests/test_script_cache.py`):

```
test_generate_and_cache_script     — generates script, saves, verifies file exists
test_run_cached_script_valid       — runs saved script on known HTML, checks output schema
test_run_cached_script_stale       — different HTML, should fail gracefully and delete cache
test_fallback_to_smart_scraper     — when ScriptCreator fails, SmartScraper kicks in
test_pydantic_schema_validation    — output always matches JobListings model
```

**Risks**:

| Risk | Mitigation |
|------|-----------|
| ScriptCreatorGraph generates broken Python | Catch all exceptions, fall through to SmartScraperGraph |
| Cached scripts become stale on site redesign | On failure, delete cache and regenerate automatically |
| `exec()` is a security surface | Scripts are self-generated and stored locally — same trust model as the rest of the pipeline |

---

## 3. DuckDB Indexing — How It Works

### Schema

Three tables:

```sql
jobs        — raw metadata: id, company, title, location, url, description, date_posted
embeddings  — one FLOAT[1024] vector per job, FK → jobs.id
cv          — single row keyed 'main', holds the CV embedding
```

The `id` for each job is `SHA256(company|title|url)[:16]` — deterministic, so re-indexing the same job is an `INSERT OR REPLACE` rather than a duplicate insert.

### Embedding text construction

The text sent to Ollama for embedding is:

```
{title}
{company}
{location}
{description}
```

All four fields concatenated. This means the vector captures the full semantic fingerprint of the role, not just the title. Missing fields are silently dropped.

### HNSW index

On top of the `embeddings` table:

```sql
CREATE INDEX emb_idx ON embeddings USING hnsw(embedding)
WITH (metric = 'cosine');
```

The `hnsw_enable_experimental_persistence = true` flag makes DuckDB persist the graph structure to disk. Without it, the HNSW graph would be rebuilt from raw vectors on every connection — correct, but slow at scale.

### Query

At match time:

```sql
SELECT j.*, array_cosine_similarity(e.embedding, ?::FLOAT[1024]) AS vector_score
FROM embeddings e
JOIN jobs j ON e.job_id = j.id
ORDER BY vector_score DESC
LIMIT ?;
```

The CV is embedded at query time, then cosine similarity is computed across all job embeddings. The HNSW index makes this approximate nearest neighbor search rather than a full table scan.

---

## 4. The Math Behind HNSW

### Cosine similarity

```
similarity(A, B) = (A · B) / (‖A‖ × ‖B‖)
```

Measures the angle between two vectors. Score of 1.0 = identical direction (perfect semantic match), 0 = orthogonal (no relation), -1 = opposite meaning. For job matching this is correct: you care about semantic alignment, not vector magnitude.

### HNSW graph structure

HNSW builds a layered graph:

- **Layer 0**: every vector is a node, each connected to its `M` nearest neighbors (default M=16)
- **Layer 1**: a random ~37% subset of layer 0 nodes, same connectivity
- **Layer 2**: ~37% of layer 1
- ...exponentially thinning upward

The probability of a node appearing in layer `l`:

```
P(node in layer l) = e^(-l × mL)    where mL = 1 / ln(M)
```

This gives a highway system: sparse high layers for fast long-distance jumps, dense bottom layer for precise local search.

### Query traversal

1. Enter at the **top layer** with a single entry point
2. Greedily navigate to whichever neighbor is closer to the query vector
3. Drop down to the next layer using the local minimum as entry point
4. Repeat until reaching layer 0
5. At layer 0, do a beam search with a priority queue of `ef` candidates

Complexity: approximately **O(log N)** vs brute-force **O(N)**.

The "approximate" part: HNSW can miss the true nearest neighbor if it gets trapped in a local minimum. The `ef` parameter controls the trade-off between accuracy and speed at query time.

---

## 5. DuckDB VSS vs ChromaDB

Both use HNSW under the hood. The differences are in what surrounds it:

| Aspect | DuckDB VSS | ChromaDB |
|--------|-----------|----------|
| **Data model** | Relational — vectors are just another column, full SQL available | Vector-native — metadata is a dictionary, not a schema |
| **Filtering** | Post-filter via SQL JOIN/WHERE after ANN | Pre-filter metadata before ANN (hurts recall on small subsets) |
| **Persistence** | Always file-backed, ACID-compliant | In-memory or SQLite-backed |
| **Concurrency** | Single-writer | Multi-client server |
| **Scale sweet spot** | Up to ~hundreds of thousands of vectors | Millions of vectors |
| **Integration** | Embedded in-process, no separate service | Can run as a server |

For targetfit — a local CLI tool scanning a few thousand jobs — DuckDB is the right fit. No separate process, no network overhead, SQL expressiveness for future filtering (by company, date, location), and a single `.duckdb` file as the only artifact.

---

## 6. Research Directions — Vector Embedding in Job Matching

### Asymmetric retrieval with instruction prefixes (highest impact, lowest effort)

`snowflake-arctic-embed2` (the model targetfit uses) was trained for asymmetric retrieval — it expects different instruction prefixes for queries vs documents. Currently targetfit passes raw text to both. Adding the correct prefixes when calling Ollama could meaningfully improve vector scores with zero architectural change:

```python
# For job embeddings (documents):
"Represent this job posting: " + job_text

# For CV embedding (query):
"Represent this candidate profile for job matching: " + cv_text
```

### Hybrid search — dense + sparse (BM25 + cosine)

Pure dense vector search misses exact keyword matches — domain-specific terms like `"patch-seq"`, `"dbt"`, or `"Kubernetes"` may not embed reliably. Combining with BM25 (term frequency ranking) consistently outperforms either approach alone.

Merge strategy: **Reciprocal Rank Fusion (RRF)**:

```
RRF_score(job) = Σ  1 / (k + rank_i(job))
```

where `k=60` is a smoothing constant and `rank_i` is the position in each ranked list. DuckDB has a full-text search extension that can run BM25 alongside VSS in the same query.

### Matryoshka embeddings — two-stage retrieval

`snowflake-arctic-embed2` supports Matryoshka representations: the first 256 dimensions of the 1024-dim vector are themselves a meaningful embedding. This enables a two-stage search:

1. Coarse ANN at 256 dims — retrieve top 200 candidates cheaply
2. Re-rank those 200 at full 1024 dims — precise scoring

Same model, same database, significantly faster for large job sets.

### Multi-vector representations

Instead of one vector per job, embed different components separately — `title_vector`, `skills_vector`, `location_vector` — then compute a weighted combination at query time. This would let users express preferences like "weight skills 80%, location 20%". DuckDB would store multiple `FLOAT[]` columns per job and compute the combined score in SQL.

### Contextual chunking for long job descriptions

Long job descriptions produce averaged-out vectors that lose specific requirements. Research suggests chunking into sections (requirements, responsibilities, benefits) and embedding each chunk separately. A job's score becomes `max(chunk_similarities)` or a weighted sum — surface matches in any section, not just the average.

### Cross-encoder re-ranking

The current LLM scoring step (40% vector + 60% LLM) is doing this conceptually, but general LLMs are slow for re-ranking. A purpose-trained **cross-encoder** (takes job + CV as a single concatenated input, outputs a relevance score) is faster and more accurate for this specific task. For local inference: models like `cross-encoder/ms-marco-MiniLM-L-6-v2` via a small local server.

### Graph-augmented retrieval

Build a graph where nodes are jobs and edges connect jobs sharing skills, companies, or seniority levels. After ANN retrieval, do a short graph walk to expand the candidate set — surfacing jobs that are adjacent in skill space but wouldn't rank in top-K on vector similarity alone (e.g., a slightly different title but identical technical requirements).

---

## 7. Summary of Current Pipeline

```
targetfit fetch
  └── For each company in companies.csv:
      1. ATS API (Greenhouse/Lever/Ashby/SmartRecruiters) → JSON directly
      2. Phenom People data-* attribute extraction → fast DOM parse
      3. ScrapeGraphAI SmartScraperGraph → LLM reads cleaned page text
      → data/jobs/{company}.json

targetfit index
  └── For each job JSON:
      1. Build embedding text (title + company + location + description)
      2. Ollama /api/embeddings → FLOAT[1024] vector
      3. INSERT OR REPLACE into DuckDB (jobs + embeddings tables)
      → data/targetfit.duckdb (HNSW index on embeddings)

targetfit match --top 10 --llm-score
  └── 1. Embed CV → query HNSW → top_k candidates (vector_score)
      2. LLM scorer: score_job() per candidate → llm_score
      3. final_score = 0.4 × vector_score + 0.6 × llm_score
      4. Filter by score_threshold (default 0.65)
      → Rich terminal table
```

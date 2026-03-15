### Example output

Below is a full pipeline run using the 13 companies from
[`data/companies.example.csv`](data/companies.example.csv) — a mix of big pharma
and big tech — with a computational biology / ML CV.

---

#### 1. Fetch jobs (with CV-driven search)

```bash
$ targetfit fetch
```

```
Analysing CV to extract search terms…
Search queries (3): 'computational biology machine learning', 'protein design AI', 'bioinformatics data science'

[Google] ATS not detected — Playwright scraping
[Google] search URL: https://careers.google.com/jobs/results/?q=computational+biology+machine+learning&location=Switzerland
[Google] paginating… page 1 (24 jobs) → page 2 (18 jobs)
[Microsoft] ATS not detected — Playwright scraping
[Microsoft] search URL: https://jobs.careers.microsoft.com/global/en/search?q=computational+biology+machine+learning&l=en_us&lc=Switzerland&pgSz=20&o=Relevance
[Microsoft] paginating… page 1 (20 jobs) → page 2 (14 jobs)
[Pfizer] Workday detected — Playwright scraping
[Pfizer] paginating… page 1 (20 jobs) → page 2 (20 jobs) → page 3 (8 jobs)
[Merck] ATS not detected — Playwright scraping
[Merck] search URL: https://jobs.merck.com/search-jobs/computational+biology+machine+learning/Switzerland
[Merck] paginating… page 1 (15 jobs)
[AstraZeneca] ATS not detected — Playwright scraping
[AstraZeneca] search URL: https://careers.astrazeneca.com/search-jobs?q=computational+biology+machine+learning&location=Switzerland&country=
[AstraZeneca] paginating… page 1 (22 jobs)
[Novartis] ATS not detected — Playwright scraping
[Novartis] paginating… page 1 (25 jobs) → page 2 (25 jobs) → page 3 (11 jobs)
[Roche] ATS not detected — Playwright scraping
[Roche] search URL: https://careers.roche.com/global/en/search-results?keywords=computational+biology+machine+learning&location=Switzerland
[Roche] paginating… page 1 (25 jobs) → page 2 (25 jobs) → page 3 (25 jobs) → page 4 (18 jobs)
[Bristol Myers Squibb] ATS not detected — Playwright scraping
[Bristol Myers Squibb] paginating… page 1 (12 jobs)
[Eli Lilly] Workday detected — Playwright scraping
[Eli Lilly] paginating… page 1 (20 jobs) → page 2 (9 jobs)
[Boehringer Ingelheim] ATS not detected — Playwright scraping
[Boehringer Ingelheim] paginating… page 1 (17 jobs)
[J&J] ATS not detected — Playwright scraping
[J&J] search URL: https://jobs.jnj.com/jobs?query=computational+biology+machine+learning&location=Switzerland
[J&J] paginating… page 1 (20 jobs) → page 2 (6 jobs)
[Genentech] ATS not detected — Playwright scraping
[Genentech] paginating… page 1 (19 jobs)
[Meta] ATS not detected — Playwright scraping
[Meta] search URL: https://www.metacareers.com/jobs/?q=computational+biology+machine+learning&offices[0]=Switzerland
[Meta] paginating… page 1 (11 jobs)

Fetched 13 companies, extracted 449 jobs into data/jobs/*.json.
```

#### 2. Index into DuckDB

```bash
$ targetfit index
```

```
Indexed 449 jobs into data/targetfit.duckdb.
```

#### 3. Vector-only dashboard

```bash
$ targetfit viz --top 15 --threshold 0.3
```

```
╭──────────────────────────────────── 🎯 targetfit ────────────────────────────────────╮
│   Date       2026-03-15                                                              │
│   Matches    15 jobs  across  8 companies                                            │
│   Best score 0.61   avg 0.47                                                         │
│   CV         Computational biologist and ML engineer with 5+ years experience in…    │
╰──────────────────────────────────────────────────────────────────────────────────────╯
╭─────┬──────────────────────┬──────────────────────────────┬──────────────────┬────────────────┬─────────────────────────╮
│   # │ Company              │ Role                         │ Location         │ Score          │ Link                    │
├─────┼──────────────────────┼──────────────────────────────┼──────────────────┼────────────────┼─────────────────────────┤
│   1 │ Roche                │ Machine Learning Scientist   │ Basel,           │ █████░░░  0.61 │ ↗ careers.roche.com     │
│     │                      │                              │ Switzerland      │                │                         │
│   2 │ Novartis             │ Senior Data Scientist,       │ Basel,           │ █████░░░  0.58 │ ↗ novartis.com          │
│     │                      │ Biomedical AI                │ Switzerland      │                │                         │
│   3 │ Genentech            │ Scientist, Computational     │ South San        │ ████░░░░  0.55 │ ↗ careers.gene.com      │
│     │                      │ Biology                      │ Francisco, CA    │                │                         │
│   4 │ Roche                │ Senior/Principal AI          │ Shanghai, China  │ ████░░░░  0.53 │ ↗ careers.roche.com     │
│     │                      │ Scientist for Large          │                  │                │                         │
│     │                      │ Molecule — AIDD              │                  │                │                         │
│   5 │ AstraZeneca          │ Principal Scientist,         │ Gothenburg,      │ ████░░░░  0.51 │ ↗ careers.astrazeneca…  │
│     │                      │ Computational Chemistry      │ Sweden           │                │                         │
│   6 │ Pfizer               │ Senior Scientist, AI/ML      │ Cambridge, MA    │ ████░░░░  0.50 │ ↗ pfizer.wd1.myworkda…  │
│     │                      │ Drug Discovery               │ USA              │                │                         │
│   7 │ Google               │ Research Scientist,          │ Zurich,          │ ████░░░░  0.49 │ ↗ careers.google.com    │
│     │                      │ Computational Biology        │ Switzerland      │                │                         │
│   8 │ Novartis             │ Bioinformatics Analyst       │ Basel,           │ ████░░░░  0.48 │ ↗ novartis.com          │
│     │                      │                              │ Switzerland      │                │                         │
│   9 │ Merck                │ Scientist, Structural        │ Rahway, NJ USA   │ ███░░░░░  0.46 │ ↗ jobs.merck.com        │
│     │                      │ Bioinformatics               │                  │                │                         │
│  10 │ Roche                │ Laborinformatik- und CSV     │ Basel,           │ ███░░░░░  0.45 │ ↗ careers.roche.com     │
│     │                      │ Spezialist in Pharma         │ Switzerland      │                │                         │
│     │                      │ Technical Development        │                  │                │                         │
│  11 │ J&J                  │ Data Engineer, R&D           │ Beerse, Belgium  │ ███░░░░░  0.44 │ ↗ jobs.jnj.com          │
│     │                      │ Analytics                    │                  │                │                         │
│  12 │ Eli Lilly            │ Senior Research Scientist,   │ Indianapolis,    │ ███░░░░░  0.42 │ ↗ lilly.wd5.myworkday…  │
│     │                      │ Protein Engineering          │ IN USA           │                │                         │
│  13 │ Microsoft            │ Senior Applied Scientist,    │ Redmond, WA      │ ███░░░░░  0.40 │ ↗ careers.microsoft.…   │
│     │                      │ Health AI                    │ USA              │                │                         │
│  14 │ Bristol Myers Squibb │ Informatics Scientist,       │ San Diego, CA    │ ███░░░░░  0.38 │ ↗ careers.bms.com       │
│     │                      │ Molecular Design             │ USA              │                │                         │
│  15 │ Boehringer Ingelheim │ Computational Biologist,     │ Ridgefield, CT   │ ██░░░░░░  0.35 │ ↗ careers.boehringer-…  │
│     │                      │ Target Discovery             │ USA              │                │                         │
╰─────┴──────────────────────┴──────────────────────────────┴──────────────────┴────────────────┴─────────────────────────╯

──────────────────────────────────────── Breakdown ────────────────────────────────────────

  Company                  Roles   Best match
 ──────────────────────────────────────────────────────
  Roche                        3   ██████░░░░  0.61
  Novartis                     2   ██████░░░░  0.58
  Genentech                    1   █████░░░░░  0.55
  AstraZeneca                  1   █████░░░░░  0.51
  Pfizer                       1   █████░░░░░  0.50
  Google                       1   █████░░░░░  0.49
  Merck                        1   ████░░░░░░  0.46
  J&J                          1   ████░░░░░░  0.44
  Eli Lilly                    1   ████░░░░░░  0.42
  Microsoft                    1   ████░░░░░░  0.40
  Bristol Myers Squibb         1   ███░░░░░░░  0.38
  Boehringer Ingelheim         1   ███░░░░░░░  0.35

╭────────────────────────────── Score distribution ──────────────────────────────╮
│                                                                                │
│                        █                                                       │
│                     █  █                                                       │
│                     █  █  █                                                    │
│                  █  █  █  █  █                                                 │
│               █  █  █  █  █  █                                                 │
│ 0.0 0.1 0.2 0.3 0.4 0.5 0.6 0.7 0.8 0.9                                      │
╰────────────────────────────────────────────────────────────────────────────────╯
```

#### 4. LLM-scored dashboard with detail

```bash
$ targetfit viz --llm-score --top 10 --threshold 0.3 --detail
```

```
╭──────────────────────────────────── 🎯 targetfit ────────────────────────────────────╮
│   Date       2026-03-15                                                              │
│   Matches    10 jobs  across  7 companies                                            │
│   Best score 0.78   avg 0.59                                                         │
│   CV         Computational biologist and ML engineer with 5+ years experience in…    │
╰──────────────────────────────────────────────────────────────────────────────────────╯
╭─────┬──────────────────────┬──────────────────────────────┬──────────────────┬────────────────┬─────────────────────────╮
│   # │ Company              │ Role                         │ Location         │ Score          │ Link                    │
├─────┼──────────────────────┼──────────────────────────────┼──────────────────┼────────────────┼─────────────────────────┤
│   1 │ Roche                │ Machine Learning Scientist   │ Basel,           │ ████████  0.78 │ ↗ careers.roche.com     │
│     │                      │                              │ Switzerland      │                │                         │
│     │                      │   Exceptional match; rare combination of       │                │                         │
│     │                      │   computational biology expertise, ML          │                │                         │
│     │                      │   proficiency, and software engineering.       │                │                         │
│     │                      │   ✓ Deep expertise in protein design           │                │                         │
│     │                      │     (AlphaFold, ProteinMPNN, RFdiffusion)     │                │                         │
│     │                      │   ✓ Molecular dynamics, structural            │                │                         │
│     │                      │     bioinformatics, and omics integration     │                │                         │
│     │                      │   ✓ Builds end-to-end systems                 │                │                         │
│     │                      │     (pipelines, web apps)                     │                │                         │
│     │                      │   ✓ Strong Python, JAX, SQL, and cloud        │                │                         │
│     │                      │     computing experience                      │                │                         │
│     │                      │   ✗ No explicit large-scale pharma            │                │                         │
│     │                      │     dataset experience                        │                │                         │
│     │                      │   ✗ No clinical trial data or regulatory      │                │                         │
│     │                      │     experience mentioned                      │                │                         │
│     │                      │                              │                  │                │                         │
├─────┼──────────────────────┼──────────────────────────────┼──────────────────┼────────────────┼─────────────────────────┤
│   2 │ Novartis             │ Senior Data Scientist,       │ Basel,           │ ████████  0.74 │ ↗ novartis.com          │
│     │                      │ Biomedical AI                │ Switzerland      │                │                         │
│     │                      │                              │                  │                │                         │
│     │                      │   Strong computational biology + ML profile   │                │                         │
│     │                      │   with direct experience in drug discovery    │                │                         │
│     │                      │   workflows.                                  │                │                         │
│     │                      │   ✓ AlphaFold, MD, structural bioinformatics  │                │                         │
│     │                      │   ✓ End-to-end data pipelines and deployment  │                │                         │
│     │                      │   ✓ Multi-omics integration for target        │                │                         │
│     │                      │     assessment                                │                │                         │
│     │                      │   ✓ Python, JAX, SQL, cloud infrastructure    │                │                         │
│     │                      │   ✗ Limited Spark/Databricks experience       │                │                         │
│     │                      │   ✗ No clinical biomarker work mentioned      │                │                         │
│     │                      │                              │                  │                │                         │
├─────┼──────────────────────┼──────────────────────────────┼──────────────────┼────────────────┼─────────────────────────┤
│   3 │ Genentech            │ Scientist, Computational     │ South San        │ ███████░  0.69 │ ↗ careers.gene.com      │
│     │                      │ Biology                      │ Francisco, CA    │                │                         │
│     │                      │                              │                  │                │                         │
│     │                      │   Well-aligned profile with strong protein    │                │                         │
│     │                      │   science and ML foundations.                  │                │                         │
│     │                      │   ✓ Protein design and structural biology     │                │                         │
│     │                      │   ✓ Proficient in ML/DL frameworks            │                │                         │
│     │                      │   ✓ Wet-lab experience bridging computational │                │                         │
│     │                      │     and experimental work                     │                │                         │
│     │                      │   ✗ No antibody engineering experience        │                │                         │
│     │                      │   ✗ Limited biologics development exposure    │                │                         │
│     │                      │                              │                  │                │                         │
├─────┼──────────────────────┼──────────────────────────────┼──────────────────┼────────────────┼─────────────────────────┤
│   4 │ Google               │ Research Scientist,          │ Zurich,          │ ██████░░  0.63 │ ↗ careers.google.com    │
│     │                      │ Computational Biology        │ Switzerland      │                │                         │
│     │                      │                              │                  │                │                         │
│     │                      │   Solid scientific computing background;      │                │                         │
│     │                      │   needs more production-scale ML systems      │                │                         │
│     │                      │   experience.                                 │                │                         │
│     │                      │   ✓ Strong ML and deep learning skills        │                │                         │
│     │                      │   ✓ Published research in computational bio   │                │                         │
│     │                      │   ✓ Python, JAX (Google stack alignment)      │                │                         │
│     │                      │   ✗ No production ML pipeline experience at   │                │                         │
│     │                      │     Google-scale                              │                │                         │
│     │                      │   ✗ No TensorFlow/TPU experience mentioned    │                │                         │
│     │                      │                              │                  │                │                         │
├─────┼──────────────────────┼──────────────────────────────┼──────────────────┼────────────────┼─────────────────────────┤
│   5 │ AstraZeneca          │ Principal Scientist,         │ Gothenburg,      │ ██████░░  0.61 │ ↗ careers.astrazeneca…  │
│     │                      │ Computational Chemistry      │ Sweden           │                │                         │
│     │                      │   ✓ Structure-based drug design (docking, MD) │                │                         │
│     │                      │   ✓ QSAR modelling and ADMET prediction       │                │                         │
│     │                      │   ✓ Strong Python and pipeline skills          │                │                         │
│     │                      │   ✗ No medicinal chemistry wet-lab experience │                │                         │
│     │                      │   ✗ No cheminformatics library depth (RDKit)  │                │                         │
│     │                      │                              │                  │                │                         │
├─────┼──────────────────────┼──────────────────────────────┼──────────────────┼────────────────┼─────────────────────────┤
│   6 │ Pfizer               │ Senior Scientist, AI/ML      │ Cambridge, MA    │ ██████░░  0.58 │ ↗ pfizer.wd1.myworkda…  │
│     │                      │ Drug Discovery               │ USA              │                │                         │
│     │                      │   ✓ Deep learning for protein structure       │                │                         │
│     │                      │   ✓ Drug discovery process knowledge          │                │                         │
│     │                      │   ✓ End-to-end system building                │                │                         │
│     │                      │   ✗ No PhD (MSc only)                         │                │                         │
│     │                      │   ✗ No GxP/regulatory experience              │                │                         │
│     │                      │                              │                  │                │                         │
├─────┼──────────────────────┼──────────────────────────────┼──────────────────┼────────────────┼─────────────────────────┤
│   7 │ Roche                │ Senior/Principal AI          │ Shanghai, China  │ █████░░░  0.55 │ ↗ careers.roche.com     │
│     │                      │ Scientist for Large          │                  │                │                         │
│     │                      │ Molecule — AIDD              │                  │                │                         │
│     │                      │   ✓ 5+ years computational biology, DL        │                │                         │
│     │                      │   ✓ Advanced protein design skills            │                │                         │
│     │                      │   ✓ Wet-lab experience                        │                │                         │
│     │                      │   ✗ No antibody design/optimisation           │                │                         │
│     │                      │   ✗ Limited large molecule experience         │                │                         │
│     │                      │                              │                  │                │                         │
├─────┼──────────────────────┼──────────────────────────────┼──────────────────┼────────────────┼─────────────────────────┤
│   8 │ Merck                │ Scientist, Structural        │ Rahway, NJ USA   │ █████░░░  0.51 │ ↗ jobs.merck.com        │
│     │                      │ Bioinformatics               │                  │                │                         │
│     │                      │   ✓ Structural bioinformatics and homology    │                │                         │
│     │                      │     modelling                                 │                │                         │
│     │                      │   ✓ AlphaFold expertise                       │                │                         │
│     │                      │   ✗ No X-ray crystallography/cryo-EM          │                │                         │
│     │                      │   ✗ No Schrödinger suite experience           │                │                         │
│     │                      │                              │                  │                │                         │
├─────┼──────────────────────┼──────────────────────────────┼──────────────────┼────────────────┼─────────────────────────┤
│   9 │ J&J                  │ Data Engineer, R&D           │ Beerse, Belgium  │ ████░░░░  0.46 │ ↗ jobs.jnj.com          │
│     │                      │ Analytics                    │                  │                │                         │
│     │                      │   ✓ Strong data pipeline and SQL skills       │                │                         │
│     │                      │   ✓ Python and cloud infrastructure           │                │                         │
│     │                      │   ✗ Role is data engineering, not science     │                │                         │
│     │                      │   ✗ No Snowflake/dbt experience               │                │                         │
│     │                      │                              │                  │                │                         │
├─────┼──────────────────────┼──────────────────────────────┼──────────────────┼────────────────┼─────────────────────────┤
│  10 │ Eli Lilly            │ Senior Research Scientist,   │ Indianapolis,    │ ████░░░░  0.42 │ ↗ lilly.wd5.myworkday…  │
│     │                      │ Protein Engineering          │ IN USA           │                │                         │
│     │                      │   ✓ Protein design and structural biology     │                │                         │
│     │                      │   ✓ Computational + wet-lab hybrid profile    │                │                         │
│     │                      │   ✗ Role requires 70% wet-lab focus           │                │                         │
│     │                      │   ✗ No cell-based assay development           │                │                         │
│     │                      │   ✗ No high-throughput screening experience   │                │                         │
╰─────┴──────────────────────┴──────────────────────────────┴──────────────────┴────────────────┴─────────────────────────╯

──────────────────────────────────────── Breakdown ────────────────────────────────────────

  Company                  Roles   Best match
 ──────────────────────────────────────────────────────
  Roche                        2   ████████░░  0.78
  Novartis                     1   ████████░░  0.74
  Genentech                    1   ███████░░░  0.69
  Google                       1   ██████░░░░  0.63
  AstraZeneca                  1   ██████░░░░  0.61
  Pfizer                       1   ██████░░░░  0.58
  Merck                        1   █████░░░░░  0.51
  J&J                          1   ████░░░░░░  0.46
  Eli Lilly                    1   ████░░░░░░  0.42

╭───────────────────────────────── Common skill gaps ──────────────────────────────────╮
│                                                                                      │
│   No antibody engineering experience            3                                    │
│   No PhD (MSc only)                             2                                    │
│   No pharma regulatory experience               2                                    │
│   No clinical trial data experience             2                                    │
│   Limited large molecule experience             2                                    │
│   No production-scale ML pipeline experience    1                                    │
│   No cheminformatics library depth (RDKit)      1                                    │
│   No Schrödinger suite experience               1                                    │
│                                                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────╯

╭────────────────────────────── Score distribution ──────────────────────────────╮
│                                                                                │
│                                    █                                           │
│                              █     █                                           │
│                           █  █  █  █                                           │
│                        █  █  █  █  █  █                                        │
│                     █  █  █  █  █  █  █                                        │
│ 0.0 0.1 0.2 0.3 0.4 0.5 0.6 0.7 0.8 0.9                                      │
╰────────────────────────────────────────────────────────────────────────────────╯
```

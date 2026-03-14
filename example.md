### Example output

Below are example outputs from a real run against Roche, Lila Sciences, and Novartis
with ~100 indexed jobs.

---

#### 1. Fetch jobs

```bash
$ targetfit fetch --company Roche --no-cv-parse
```

```
Fetched 1 companies, extracted 99 jobs into data/jobs/*.json.
```

#### 2. Index into DuckDB

```bash
$ targetfit index
```

```
Indexed 99 jobs into data/targetfit.duckdb.
```

#### 3. Vector-only match

```bash
$ targetfit viz --top 10 --threshold 0.3
```

```
╭──────────────────────────────── targetfit ────────────────────────────────╮
│   Date       2026-03-14                                                      │
│   Matches    10 jobs  across  3 companies                                    │
│   Best score 0.49   avg 0.45                                                 │
│   CV         ALESSIO D'ADDIO                                                 │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─────┬────────────────────┬──────────────────────────┬────────────────┬────────
│   # │ Company            │ Role                     │ Location       │ Score
├─────┼────────────────────┼──────────────────────────┼────────────────┼────────
│   1 │ Lila Sciences      │ Scientist I, Expression  │ Cambridge, MA  │ ██████░
│     │                    │ Platform, Mammalian      │ USA            │   0.49
│     │                    │ Cells                    │                │
│   2 │ Lila Sciences      │ Senior Principal /       │ Cambridge, MA  │ ██████░
│     │                    │ Associate Director,      │ USA            │   0.48
│     │                    │ Scientific ML for Drug   │                │
│     │                    │ Discovery                │                │
│   3 │ Roche              │ Laborinformatik- und CSV │ Basel,         │ ██████░
│     │                    │ Spezialist in Pharma     │ Basel-City,    │   0.47
│     │                    │ Technical Development    │ Switzerland    │
│   4 │ Roche              │ Senior/Principal AI      │ Shanghai,      │ ██████░
│     │                    │ Scientist for Large      │ Shanghai,      │   0.47
│     │                    │ Molecule - AIDD          │ China          │
│   5 │ Lila Sciences      │ Director, AI for Protein │ San Francisco, │ ██████░
│     │                    │ Engineering              │ CA USA         │   0.46
│   6 │ Lila Sciences      │ Senior Research          │ Cambridge, MA  │ █████░░
│     │                    │ Associate, Protein       │ USA            │   0.44
│     │                    │ Science Developability   │                │
│   7 │ Roche              │ Section Lead Process     │ Basel,         │ █████░░
│     │                    │ Science and Data Flow    │ Basel-City,    │   0.44
│     │                    │                          │ Switzerland    │
│   8 │ Roche              │ Machine Learning         │ Basel,         │ █████░░
│     │                    │ Scientist                │ Basel-City,    │   0.44
│     │                    │                          │ Switzerland    │
│   9 │ Roche              │ Senior Science and       │ Penzberg,      │ █████░░
│     │                    │ People Lead in           │ Bavaria,       │   0.43
│     │                    │ Bioconjugation and       │ Germany        │
│     │                    │ Protein Engineering      │                │
│  10 │ Novartis           │ Data Analytics &         │ Bogota         │ █████░░
│     │                    │ Platforms Associate      │                │   0.43
╰─────┴────────────────────┴──────────────────────────┴────────────────┴────────

──────────────────────────────── Breakdown ─────────────────────────────────

  Company                Roles   Best match
 ───────────────────────────────────────────────
  Lila Sciences              4   █████░░░░░  0.49
  Roche                      5   █████░░░░░  0.47
  Novartis                   1   ████░░░░░░  0.43

╭───────────────────────── Score distribution ──────────────────────────────╮
│       █                                                                   │
│       █                                                                   │
│       █                                                                   │
│       █                                                                   │
│       █                                                                   │
│ 0.0 0.1 0.2 0.4 0.5 0.6 0.8 0.9                                          │
╰───────────────────────────────────────────────────────────────────────────╯
```

#### 4. LLM-scored match with detail

```bash
$ targetfit viz --llm-score --top 10 --threshold 0.3
```

```
╭──────────────────────────────── targetfit ────────────────────────────────╮
│   Date       2026-03-14                                                      │
│   Matches    9 jobs  across  3 companies                                     │
│   Best score 0.72   avg 0.58                                                 │
│   CV         ALESSIO D'ADDIO                                                 │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─────┬────────────────────┬──────────────────────────┬────────────────┬────────
│   # │ Company            │ Role                     │ Location       │ Score
├─────┼────────────────────┼──────────────────────────┼────────────────┼────────
│   1 │ Roche              │ Machine Learning         │ Basel,         │ ████████
│     │                    │ Scientist                │ Switzerland    │   0.72
│     │                    │                          │                │
│     │                    │   This is an exceptional match; the       │
│     │                    │   candidate possesses a rare combination  │
│     │                    │   of computational biology expertise,     │
│     │                    │   machine learning proficiency, and       │
│     │                    │   practical software engineering skills.  │
│     │                    │   ✓ Deep expertise in protein design      │
│     │                    │     (AlphaFold, ProteinMPNN, RFdiffusion) │
│     │                    │   ✓ Molecular dynamics, structural        │
│     │                    │     bioinformatics, and omics integration │
│     │                    │   ✓ Prior internship at Roche; builds     │
│     │                    │     end-to-end systems (pipelines, apps)  │
│     │                    │   ✓ Strong Python, JAX, SQL, and cloud    │
│     │                    │     computing experience                  │
│     │                    │   ✗ No explicit large-scale pharma        │
│     │                    │     dataset experience                    │
│     │                    │   ✗ Prior food-delivery industry role     │
│     │                    │     may need adaptation to drug discovery │
│     │                    │   ✗ No clinical trial data or regulatory  │
│     │                    │     experience mentioned                  │
│     │                    │                          │                │
├─────┼────────────────────┼──────────────────────────┼────────────────┼────────
│   2 │ Lila Sciences      │ Senior Principal /       │ Cambridge, MA  │ ████████
│     │                    │ Associate Director,      │ USA            │   0.70
│     │                    │ Scientific ML for Drug   │                │
│     │                    │ Discovery                │                │
│     │                    │                          │                │
│     │                    │   Highly skilled computational biologist  │
│     │                    │   with strong technical foundation and    │
│     │                    │   demonstrated ability to build impactful │
│     │                    │   data-driven solutions for drug          │
│     │                    │   discovery.                              │
│     │                    │   ✓ Structure-based drug design           │
│     │                    │     (AlphaFold, docking), QSAR, and MD   │
│     │                    │   ✓ End-to-end system building: pipelines │
│     │                    │     to web app deployment                 │
│     │                    │   ✓ Hands-on JAX, Python, SQL, cloud     │
│     │                    │   ✓ Drug discovery process knowledge      │
│     │                    │     (target assessment, ADMET, PK/PD)    │
│     │                    │   ✗ Limited team-scaling experience       │
│     │                    │   ✗ More research-focused than commercial │
│     │                    │     drug discovery program experience     │
│     │                    │   ✗ Synthesis planning not mentioned      │
│     │                    │                          │                │
├─────┼────────────────────┼──────────────────────────┼────────────────┼────────
│   3 │ Novartis           │ Data Analytics &         │ Bogota         │ ████████
│     │                    │ Platforms Associate      │                │   0.68
│     │                    │                          │                │
│     │                    │   Highly qualified hybrid profile with    │
│     │                    │   strong technical foundation in          │
│     │                    │   computational biology, data eng, and    │
│     │                    │   software development.                   │
│     │                    │   ✓ AlphaFold, MD, Python, SQL, JAX      │
│     │                    │   ✓ End-to-end data pipelines and        │
│     │                    │     dashboard deployment                  │
│     │                    │   ✓ Biochemistry and structural biology   │
│     │                    │     background                            │
│     │                    │   ✓ Multi-omics data integration for      │
│     │                    │     drug target assessment                │
│     │                    │   ✗ Limited cloud engineering depth       │
│     │                    │   ✗ Research-heavy, no pharma analytics   │
│     │                    │     team experience                       │
│     │                    │   ✗ Missing Tableau/PowerBI experience    │
│     │                    │                          │                │
├─────┼────────────────────┼──────────────────────────┼────────────────┼────────
│   4 │ Roche              │ Laborinformatik- und CSV │ Basel,         │ ████████
│     │                    │ Spezialist in Pharma     │ Switzerland    │   0.65
│     │                    │ Technical Development    │                │
│     │                    │   ✓ Prior Roche internship               │
│     │                    │   ✓ Data integration and pipeline skills  │
│     │                    │   ✓ Structural bioinformatics and MD     │
│     │                    │   ✗ No CSV (Computer System Validation)   │
│     │                    │   ✗ No LIMS/MES experience                │
│     │                    │   ✗ No pharma regulatory experience       │
│     │                    │                          │                │
├─────┼────────────────────┼──────────────────────────┼────────────────┼────────
│   5 │ Roche              │ Senior/Principal AI      │ Shanghai,      │ ████████
│     │                    │ Scientist for Large      │ China          │   0.63
│     │                    │ Molecule - AIDD          │                │
│     │                    │   ✓ 5+ years computational biology, DL   │
│     │                    │   ✓ Advanced protein design skills        │
│     │                    │   ✓ Wet-lab experience                    │
│     │                    │   ✗ No PhD (MSc only)                     │
│     │                    │   ✗ No antibody design/optimisation       │
│     │                    │   ✗ Limited large molecule experience     │
│     │                    │                          │                │
├─────┼────────────────────┼──────────────────────────┼────────────────┼────────
│   6 │ Lila Sciences      │ Director, AI for Protein │ San Francisco  │ ██████░░
│     │                    │ Engineering              │                │   0.55
│     │                    │   ✓ Strong technical expertise            │
│     │                    │   ✓ Generative protein design experience  │
│     │                    │   ✓ Data pipeline building                │
│     │                    │   ✗ Lack of senior leadership experience  │
│     │                    │   ✗ No team-building track record         │
│     │                    │   ✗ Limited antibody/enzyme depth         │
│     │                    │                          │                │
├─────┼────────────────────┼──────────────────────────┼────────────────┼────────
│   7 │ Roche              │ Section Lead Process     │ Basel,         │ ██████░░
│     │                    │ Science and Data Flow    │ Switzerland    │   0.51
│     │                    │   ✓ Process science experience            │
│     │                    │   ✓ Data flow experience                  │
│     │                    │   ✓ Some leadership experience            │
│     │                    │   ✗ No manufacturing process knowledge    │
│     │                    │   ✗ No pharma regulatory experience       │
│     │                    │   ✗ Too junior for likely senior role     │
│     │                    │                          │                │
├─────┼────────────────────┼──────────────────────────┼────────────────┼────────
│   8 │ Lila Sciences      │ Scientist I, Expression  │ Cambridge, MA  │ █████░░░
│     │                    │ Platform, Mammalian      │ USA            │   0.45
│     │                    │ Cells                    │                │
│     │                    │   ✓ Computational expertise bridging bio  │
│     │                    │   ✓ Expression/purification & assay exp.  │
│     │                    │   ✓ Strong data pipelines                 │
│     │                    │   ✗ No mammalian cell culture experience  │
│     │                    │   ✗ No single-cell sequencing workflows   │
│     │                    │   ✗ No multiomic assay development        │
│     │                    │                          │                │
├─────┼────────────────────┼──────────────────────────┼────────────────┼────────
│   9 │ Lila Sciences      │ Senior Research          │ Cambridge, MA  │ █████░░░
│     │                    │ Associate, Protein       │ USA            │   0.42
│     │                    │ Science Developability   │                │
╰─────┴────────────────────┴──────────────────────────┴────────────────┴────────

──────────────────────────────── Breakdown ─────────────────────────────────

  Company                Roles   Best match
 ───────────────────────────────────────────────
  Roche                      4   ████████░░  0.72
  Lila Sciences              4   ████████░░  0.70
  Novartis                   1   ████████░░  0.68

╭───────────────────────── Score distribution ──────────────────────────────╮
│           █                                                               │
│         █ █                                                               │
│       █ █ █                                                               │
│       █ █ █                                                               │
│       █ █ █                                                               │
│ 0.0 0.1 0.2 0.4 0.5 0.6 0.8 0.9                                          │
╰───────────────────────────────────────────────────────────────────────────╯
```

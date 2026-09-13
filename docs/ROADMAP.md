# Opportunity Detection Radar - POC segment plan (S1-S4)

This POC is split into four segments. Each segment is a self-contained slice with its own
**implementation -> validation -> testing** loop, so we can take each one to "it works" before
moving on. The segments also stack: S1's output is S2's input, and so on. You can either drive
straight down (finish S1, then S2, ...) or build a thin first version of all four and then
optimise each in a second pass. The recommendation is **depth-first through S1-S3, then S4**,
because the dashboard (S4) is only worth building once there is a real score to show.

Traceability note: FR-xx / NFR-xx tags map to the Requirements Specification; the pipeline
steps map to §4 of the Technical Design.

---

## S1 - Data foundation: ingestion, normalization, storage  ✅ implemented

**Goal.** Turn a public seed list of target companies into a clean, queryable local database of
companies + business events, each with full provenance (where it came from, when we fetched it).
This is the ground truth everything else is scored on.

**What it covers.** FR-01 (company ingestion), FR-02 (enrichment), FR-03 (event collection),
FR-04 (source provenance), FR-05 (entity resolution / mention verification), FR-12 (export),
NFR-01/02 (external isolation, no SIX data), NFR-03 (reproducibility), NFR-05 (modular design).

**How it's built.**
- Seed list of 121 real financial-sector companies (`data/seed/companies.csv`).
- Four independent public-source connectors: Wikidata + Wikipedia (enrichment), Google News RSS
  + GDELT (events). Using two event sources reduces single-source bias (a BRD risk control).
- A shared **Fetcher** with polite crawling (max 1 request/second/host), retries with
  exponential backoff, and two modes: **live** (real HTTP, every response saved to `data/raw`
  with URL + timestamp) and **offline** (replays recorded fixtures, no network).
- **Normalization + entity resolution**: legal-form-aware name cleaning and fuzzy matching, so
  "Partners Group Holding AG" and "PARTNERS GROUP" resolve to one company, and an article about
  the wrong company is dropped (mention verification).
- **DuckDB** storage (a single-file analytical database) with idempotent upserts, so re-running
  the pipeline never duplicates rows.
- A provisional keyword event-tagger fills `event_type` at low confidence purely so the demo is
  readable; it is explicitly a placeholder for the S2 classifier.

**Validation (what "works" means).**
- `radar ingest --offline` populates companies, events and sources with zero errors.
- Every event links to a source and carries a collection timestamp; every source has a URL and
  retrieval time.
- Re-running produces identical row counts (idempotent).

**Testing.** `tests/` (15 tests): normalization + resolution, each connector parsing its
fixture, storage idempotency/export, and a full offline pipeline run asserting the acceptance
criteria (>=100 companies processed, provenance complete, multiple sources per company).

**Known gaps to close later.** Country/industry Q-ids from Wikidata are stored raw, not resolved
to labels (saves rate budget); real labelled fixtures come from a live `--record` run once
network access is available.

---

## S2 - Signals & features: event classification + feature engineering  ⏳ next

**Goal.** Convert raw events and company attributes into **model-ready features** (a feature is a
single numeric input a model reads, e.g. "number of acquisition events in the last 90 days").

**What it covers.** FR-03 (proper event typing), FR-06 (feature engineering), and populates the
`FeatureSnapshot` table already defined in the data model.

**Planned build.**
- Replace the keyword tagger with an NLP classifier: spaCy for entity/keyword extraction and
  `sentence-transformers` embeddings (vector embeddings = numeric representations of text that
  capture meaning) for semantic event typing. Deterministic extraction stays separate from any
  LLM layer (Technical Design §6.3).
- Feature families: **event intensity** (counts by type), **recency/momentum** (how recent and
  accelerating the signals are), **company fit** (segment, size, listed status), and
  **similarity-to-target-profile** (cosine similarity of the company's embedding to a defined
  "ideal customer" profile).
- Write one `FeatureSnapshot` row per (company, snapshot_date, feature) for reproducibility.

**Validation.** Feature table is dense (no all-null features), snapshots are dated, and the
same input reproduces the same features. Spot-check that high-activity companies score higher on
intensity/recency than quiet ones.

**Testing.** Unit tests per feature transformer; a golden-file test on the sample companies.

---

## S3 - Scoring, ranking & product fit + explainability  ⏳

**Goal.** Produce the 0-100 opportunity score, the ranked list, the relevant SIX product
family, and a human-readable explanation with evidence.

**What it covers.** FR-07 (scoring), FR-08 (ranking), FR-09 (product relevance), FR-10
(explanation), FR-11 (evidence), FR-13 (baseline vs ML comparison).

**Planned build.**
- **Baseline** (transparent, business-readable): weighted-rule score + cosine similarity to the
  target profile. This is the benchmark that answers "does ML actually add value?".
- **ML model**: logistic regression as an interpretable benchmark, then gradient-boosted trees
  (XGBoost / LightGBM) as the advanced model. In the external POC these train on **proxy
  labels** or a defined relevance benchmark, not real SIX conversions - clearly flagged as such.
- **Product-relevance layer**: map detected signals to a small controlled taxonomy (Reference
  Data, Market Data, Funds Data, Corporate Actions, Regulatory/Tax, ESG).
- **Explainability**: global feature importance + local SHAP-style explanations, plus the
  evidence list (the actual public sources behind each flagged signal). LLM explanations, if
  used, must be grounded in stored evidence (anti-hallucination control).
- **Evaluation framework**: baseline vs ML, with vs without events, static vs temporal,
  structured vs NLP-enriched - using ranking metrics (Precision@K, and ROC/PR-AUC once real
  labels exist).

**Validation.** Flagged companies are demonstrably more relevant than a random sample; top-ranked
companies show stronger target characteristics than bottom-ranked; every high score has evidence.

**Testing.** Deterministic scoring on the sample set; a regression test pinning expected ranks;
model-vs-baseline comparison reported by a `radar evaluate` command.

---

## S4 - Radar UI & management demo  ⏳

**Goal.** A simple interface a non-technical sales manager understands in a few minutes
(NFR-08): pick a company, see its score, signals, product relevance, explanation and evidence.

**What it covers.** FR-12 (dashboard/export), the "Demo" acceptance criterion, and the pitch
deliverable (Technical Design P6).

**Planned build.**
- **Streamlit** app (Python-native web UI, no front-end code) reading straight from DuckDB:
  a ranked radar table, a company detail view matching the "Example Output Object" in the
  Technical Design, and filters by segment/country/score.
- Polished CSV/XLSX export and a short "limitations + internal-pilot proposal" section.

**Validation.** A manager can select a company and inspect score, signals and product relevance
without understanding the model. The whole thing runs offline from the local database.

**Testing.** Smoke tests on the data-access layer behind the UI; manual demo-script walkthrough.

---

## How the segments connect

```
S1 companies + events + provenance
      -> S2 features (intensity, recency, fit, similarity)
            -> S3 score + rank + product fit + explanation + evidence
                  -> S4 radar dashboard + management demo
```

Everything stays **external and public-data only** until management approves an internal pilot,
at which point CRM metadata and real outcome labels (the `OutcomeLabel` fields already reserved
in S1) become the bridge to supervised learning.

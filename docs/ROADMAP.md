# Opportunity Detection Radar - POC segment plan

This POC is split into segments. Each segment is a self-contained slice with its own
**implementation -> validation -> testing** loop, so we can take each one to "it works" before
moving on. The segments also stack: S1's output is S2's input, and so on. You can either drive
straight down (finish S1, then S2, ...) or build a thin first version of all of them and then
optimise each in a second pass. The recommendation is **depth-first through S1-S3, then S4**,
because the dashboard (S4) is only worth building once there is a real score to show.

Alongside the S1-S4 opportunity-scoring track, the tool also has a **monitoring/alerting** track:
the Insights layer (below) turns the collected events into distinct, deduplicated insights and
flags the new ones. This is what makes the tool useful *day to day* (watch my companies, tell me
what changed) rather than only as a one-off ranking exercise. The two tracks reinforce each other:
once S3 scoring exists, insights carry an opportunity score and the Daily Insights view can lead
with the high-opportunity ones, which is the cure for notification fatigue.

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
- Independent public-source connectors: Wikidata + Wikipedia (enrichment), and Google News RSS,
  GDELT, Yahoo Finance and SEC EDGAR (events). Using several event sources reduces single-source
  bias (a BRD risk control) and is what the Insights layer deduplicates across.
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

**Testing.** `tests/` covers normalization + resolution, each connector parsing its fixture,
storage idempotency/export, and a full offline pipeline run asserting the acceptance criteria
(>=100 companies processed, provenance complete, multiple sources per company).

**Known gaps to close later.** Country/industry Q-ids from Wikidata are stored raw, not resolved
to labels (saves rate budget); real labelled fixtures come from a live `--record` run once
network access is available.

---

## Insights layer - deduplication + Daily Insights  ✅ implemented

**Goal.** Turn raw events into **distinct insights** and flag the new ones, so the tool can be run
on a schedule and answer "what changed with my companies?". This is the monitoring/alerting track.

**What it covers.** FR-03 (multi-source events), the deduplication + "distinct insights with their
sources" requirement, and the in-app Daily Insights surface (notification channel chosen: in-app).

**How it's built.**
- Four event connectors: **Google News RSS, GDELT, Yahoo Finance, SEC EDGAR** (SEC covers
  US-listed companies only). All go through the shared Fetcher, so offline replay and provenance
  are uniform.
- **Deduplication** (`src/radar/insights.py`): within each company, events are greedily clustered
  by fuzzy title similarity within a time window. Each cluster becomes one Insight with a canonical
  title, the earliest date, the distinct connectors, and one InsightSource row per reporting
  article. So one acquisition reported by three sources is one insight listing three sources.
- **New detection**: an insight's id is content-derived and stable across runs, so an insight not
  seen on a previous run is flagged `is_new` - the basis of `radar insights --new`.
- **View**: `radar insights` (add `--new`, `--company`) is the in-app Daily Insights surface;
  the S4 dashboard will read the same tables.

**Validation.** The same story from Google News + GDELT + Yahoo collapses to one insight with
three sources; genuinely different stories stay separate; two filings far apart in time stay
separate; a second run flags zero new insights.

**Testing.** `tests/test_insights.py`: the two new connectors' parsing, the clustering logic in
isolation (merge / keep-separate / time-window), end-to-end cross-source dedup, the new-flag
reset on a second run, and an id-collision regression test.

**Known limits.** Matching is fuzzy title + time window, so it misses same-meaning-different-words
duplicates ("buys" vs "completes acquisition of"). The planned upgrade is *semantic* dedup using
sentence-embeddings (see S2). Yahoo Finance and SEC EDGAR live response shapes are coded to the
documented formats but were not executed from the build sandbox (no internet); confirm on the
first live run. Notification is in-app only for now; email/Slack/desktop are straightforward to
add behind the same insight data.

---

## S2 - Signals & features: feature engineering  ✅ implemented

**Goal.** Convert raw events and company attributes into **model-ready features** (a feature is a
single numeric input a model reads, e.g. "number of acquisition events in the last 90 days").

**What it covers.** FR-06 (feature engineering); populates the `FeatureSnapshot` table.

**How it's built** (`src/radar/features.py`). For every company, one `FeatureSnapshot` row per
feature (14 features x 121 companies = ~1,700 values), versioned `s2-v1` and dated for
reproducibility (NFR-03/07). Feature families:
- **intensity**: `events_total`, `insights_total`, `relevant_event_count` (acquisition / expansion
  / product launch / funding / partnership).
- **recency / momentum**: `events_90d`, `events_180d`, `days_since_last_event`, and
  `recency_score` (each event weighted by a 45-day half-life, so recent signals count for more).
- **corroboration**: `sources_max`, `sources_mean` (how many independent sources back the
  company's insights - the dedup source counts, reused as a feature).
- **diversity**: `distinct_event_types`.
- **fit**: `size_rank`, `is_listed`, `has_description`.
- **profile_similarity**: TF-IDF cosine of the company's public text (segment + description)
  against a target-customer profile. Fully offline, deterministic, transparent.

`radar features --company "<name>"` shows one company's vector; `radar features --by <feature>`
ranks companies by it.

**Offline substitution (important).** The Technical Design floated spaCy + sentence-transformer
embeddings for this segment. Those need pretrained models downloaded from the internet, which the
build sandbox blocks, so S2 ships **TF-IDF** similarity instead: same question ("does this company
read like our ideal customer?"), simpler maths, no model download. Swapping in embeddings on a
networked machine is localized to `tfidf_cosine_to_target` and would also upgrade the Insights
layer's dedup from fuzzy-title to semantic. Deeper event *classification* beyond the provisional
keyword tagger is deferred until there are labels to learn from (the external POC has none yet).

**Validation.** Feature table is dense (every company has every feature), snapshots are dated and
versioned, features reproduce exactly on a re-run, `profile_similarity` stays in 0-1, and companies
with events outrank quiet ones on `recency_score`.

**Testing.** `tests/test_features.py`: TF-IDF ranking, density + dating, signal-tracks-reality,
and a determinism check.

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
      |
      +-- Insights layer: dedup across sources -> distinct insights + Daily Insights view
      |
      -> S2 features (intensity, recency, fit, similarity)
            -> S3 score + rank + product fit + explanation + evidence
                  -> S4 radar dashboard + management demo
                        (and: insights carry the S3 score, so alerts lead with high-opportunity ones)
```

Everything stays **external and public-data only** until management approves an internal pilot,
at which point CRM metadata and real outcome labels (the `OutcomeLabel` fields already reserved
in S1) become the bridge to supervised learning.

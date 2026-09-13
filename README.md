# Opportunities Radar

> Repository for the **AI Opportunity Detection Radar** — external, public-data proof of concept.

A sales-intelligence prototype for SIX Financial Information. It collects **public** information
about a list of target companies, detects business events (acquisitions, expansion, product
launches, hiring, regulatory developments), deduplicates the same story across sources into
distinct **insights**, and surfaces the new ones in a Daily Insights view. Later segments score
each company's opportunity relevance and explain *why* it was flagged, with the evidence behind it.

The whole POC runs **outside** the SIX corporate environment and uses public data only.
See `docs/ROADMAP.md` for the segment plan and the current status.

## Quick start

```bash
uv venv && uv pip install -e ".[dev]"      # or: python -m venv .venv && pip install -e ".[dev]"
source .venv/bin/activate

radar init-db                              # create the local database (DuckDB)
radar ingest --offline                     # run the pipeline on the recorded sample data
radar insights                             # the Daily Insights view (distinct, deduplicated)
radar insights --new                       # only insights first seen on the latest run
radar features --company "Partners Group"  # S2 model-ready feature vector for one company
radar features --by recency_score          # rank companies by a feature
radar status                               # what is in the database now
radar company "Partners Group"             # drill into one company
radar export                               # CSV files under data/exports/
```

Drop `--offline` (or pass `--live`) to collect real data from the public sources. Live collection
needs internet access and respects the polite-crawling settings in `src/radar/config.py`.

## Sources (connectors)

Enrichment (company profile): **Wikidata**, **Wikipedia**.
Insight sources (business events): **Google News RSS**, **GDELT**, **Yahoo Finance**, **SEC EDGAR**.

All are public and need no API key. Which insight sources run is controlled by `RADAR_CONNECTORS`
(or `connectors` in `src/radar/config.py`). SEC EDGAR covers US-listed companies only.

## Insights and deduplication

Raw events from different sources are collapsed into **distinct insights**: when Google News,
GDELT and Yahoo all report the same acquisition, that is one insight listing all three sources,
not three notifications. Insights first seen on the most recent run are flagged as new. See
`radar insights` and the "Insights layer" section of `docs/ROADMAP.md` for how the matching works
and its limits.

## Offline vs live

Offline mode replays recorded sample responses (*fixtures*) so the pipeline and the tests run
deterministically with no internet. The sample fixtures under `data/fixtures/` are **synthetic**
(clearly labelled, not real scraped data) and cover six companies, including a story duplicated
across sources so the deduplication is demonstrable. Live mode collects the real public data.
Regenerate the sample fixtures with `python scripts/make_sample_fixtures.py`.

## Run the tests

```bash
pytest
ruff check src tests
```

## Layout

```
data/seed/companies.csv     the target-company seed list (FR-01)
data/fixtures/              recorded public-source responses used for offline runs and tests
data/raw/                   every live response, as retrieved, with its URL and timestamp (NFR-03)
data/db/radar.duckdb        local analytical database (created by `radar init-db`)
src/radar/models.py         the data model (Company, Source, Event, Insight, ... see docs/DATA_MODEL.md)
src/radar/storage.py        database schema and load/save helpers
src/radar/ingest/           one connector per public source + the ingest orchestrator
src/radar/insights.py       cross-source deduplication into distinct insights
src/radar/normalize/        company-name normalization and entity resolution (FR-05)
src/radar/cli.py            the `radar` command-line tool
tests/                      automated tests (run offline, no internet needed)
```

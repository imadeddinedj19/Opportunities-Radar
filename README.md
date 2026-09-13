# Opportunities Radar

> Repository for the **AI Opportunity Detection Radar** — external, public-data proof of concept.

A sales-intelligence prototype for SIX Financial Information. It collects **public** information
about a list of target companies, detects business events (acquisitions, expansion, product
launches, hiring, regulatory developments), scores each company's potential relevance as a sales
opportunity, and explains *why* a company was flagged, with the evidence behind it.

The whole POC runs **outside** the SIX corporate environment and uses public data only.
See `docs/ROADMAP.md` for the segment plan (S1–S4) and the current status.

## Quick start

```bash
cd opportunity-radar
uv venv && uv pip install -e ".[dev]"      # or: python -m venv .venv && pip install -e ".[dev]"
source .venv/bin/activate

radar init-db                              # create the local database (DuckDB)
radar ingest --offline                     # run the pipeline on the recorded sample data
radar status                               # what is in the database now
radar export                               # CSV files under data/exports/
```

Drop `--offline` to collect live data from the public sources (Wikidata, Wikipedia, Google News
RSS, GDELT). Live collection needs internet access and respects the polite-crawling settings in
`src/radar/config.py`.

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
src/radar/models.py         the data model (Company, Source, Event, Score, ... see docs/DATA_MODEL.md)
src/radar/storage.py        database schema and load/save helpers
src/radar/ingest/           one connector per public source + the ingest orchestrator
src/radar/normalize/        company-name normalization and entity resolution (FR-05)
src/radar/cli.py            the `radar` command-line tool
tests/                      automated tests (run offline, no internet needed)
```

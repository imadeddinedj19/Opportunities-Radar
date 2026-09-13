"""Local analytical storage: DuckDB tables with Parquet export.

DuckDB is an embedded analytical database (a single file, no server) that is fast for the
column-oriented queries we run in feature engineering and evaluation. All writes go through
``upsert`` so re-running any pipeline step is idempotent: same input, same rows, no duplicates.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

import duckdb
import pandas as pd
from pydantic import BaseModel

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    company_id VARCHAR PRIMARY KEY,
    canonical_name VARCHAR NOT NULL,
    normalized_name VARCHAR NOT NULL,
    aliases VARCHAR[],
    domain VARCHAR,
    country VARCHAR,
    industry VARCHAR,
    segment VARCHAR,
    size_band VARCHAR,
    employees INTEGER,
    listed BOOLEAN,
    description VARCHAR,
    region VARCHAR,
    strategic BOOLEAN,
    wikidata_id VARCHAR,
    enrichment_confidence DOUBLE,
    seed_source VARCHAR,
    updated_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS sources (
    source_id VARCHAR PRIMARY KEY,
    connector VARCHAR NOT NULL,
    publisher VARCHAR,
    url VARCHAR NOT NULL,
    query VARCHAR,
    retrieved_at TIMESTAMPTZ NOT NULL,
    from_fixture BOOLEAN
);
CREATE TABLE IF NOT EXISTS events (
    event_id VARCHAR PRIMARY KEY,
    company_id VARCHAR NOT NULL,
    event_type VARCHAR NOT NULL,
    event_date DATE,
    title VARCHAR NOT NULL,
    text VARCHAR,
    url VARCHAR,
    publisher VARCHAR,
    language VARCHAR,
    source_id VARCHAR NOT NULL,
    match_method VARCHAR,
    match_confidence DOUBLE,
    mention_verified BOOLEAN,
    classification_confidence DOUBLE,
    collected_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS insights (
    insight_id VARCHAR PRIMARY KEY,
    company_id VARCHAR NOT NULL,
    insight_type VARCHAR NOT NULL,
    canonical_title VARCHAR NOT NULL,
    event_date DATE,
    source_count INTEGER,
    connectors VARCHAR[],
    first_seen_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ,
    is_new BOOLEAN,
    opportunity_score DOUBLE
);
CREATE TABLE IF NOT EXISTS insight_sources (
    insight_id VARCHAR NOT NULL,
    connector VARCHAR NOT NULL,
    publisher VARCHAR,
    url VARCHAR,
    event_id VARCHAR NOT NULL,
    event_date DATE,
    PRIMARY KEY (insight_id, event_id)
);
CREATE TABLE IF NOT EXISTS feature_snapshots (
    company_id VARCHAR NOT NULL,
    snapshot_date DATE NOT NULL,
    feature_name VARCHAR NOT NULL,
    value DOUBLE,
    feature_version VARCHAR,
    PRIMARY KEY (company_id, snapshot_date, feature_name, feature_version)
);
CREATE TABLE IF NOT EXISTS scores (
    company_id VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    score DOUBLE NOT NULL,
    confidence DOUBLE,
    score_date TIMESTAMPTZ,
    rank INTEGER,
    PRIMARY KEY (company_id, model_version)
);
CREATE TABLE IF NOT EXISTS product_relevance (
    company_id VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    product_family VARCHAR NOT NULL,
    relevance_score DOUBLE NOT NULL,
    evidence VARCHAR,
    PRIMARY KEY (company_id, model_version, product_family)
);
CREATE TABLE IF NOT EXISTS explanations (
    company_id VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    supporting_features VARCHAR[],
    source_ids VARCHAR[],
    PRIMARY KEY (company_id, model_version)
);
CREATE TABLE IF NOT EXISTS outcome_labels (
    company_id VARCHAR PRIMARY KEY,
    opportunity_created BOOLEAN,
    opportunity_stage VARCHAR,
    won BOOLEAN,
    product_family VARCHAR,
    value DOUBLE,
    conversion_date DATE,
    label_source VARCHAR
);
"""

TABLES: Sequence[str] = (
    "companies",
    "sources",
    "events",
    "insights",
    "insight_sources",
    "feature_snapshots",
    "scores",
    "product_relevance",
    "explanations",
    "outcome_labels",
)


class Store:
    """Thin wrapper around a DuckDB connection with the POC schema applied."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(self.db_path))
        self.con.execute(SCHEMA)

    # -- lifecycle ------------------------------------------------------------------------
    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- writes ---------------------------------------------------------------------------
    def upsert(self, table: str, records: Iterable[BaseModel]) -> int:
        """Insert-or-replace validated records. Returns the number of rows written."""
        rows = [r.model_dump(mode="python") for r in records]
        if not rows:
            return 0
        if table not in TABLES:
            raise ValueError(f"unknown table {table!r}")
        df = pd.DataFrame(rows)
        cols = [c for c in self.columns(table) if c in df.columns]
        df = df[cols]
        self.con.register("_incoming", df)
        col_list = ", ".join(cols)
        self.con.execute(
            f"INSERT OR REPLACE INTO {table} ({col_list}) SELECT {col_list} FROM _incoming"
        )
        self.con.unregister("_incoming")
        return len(df)

    # -- reads ----------------------------------------------------------------------------
    def columns(self, table: str) -> list[str]:
        rows = self.con.execute(f"DESCRIBE {table}").fetchall()
        return [r[0] for r in rows]

    def df(self, sql: str, params: Sequence | None = None) -> pd.DataFrame:
        return self.con.execute(sql, params or []).df()

    def count(self, table: str) -> int:
        return self.con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def counts(self) -> dict[str, int]:
        return {t: self.count(t) for t in TABLES}

    # -- export ---------------------------------------------------------------------------
    def export(self, out_dir: Path, fmt: str = "csv", tables: Sequence[str] = TABLES) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for t in tables:
            path = out_dir / f"{t}.{fmt}"
            if fmt == "csv":
                self.con.execute(f"COPY {t} TO '{path}' (HEADER, DELIMITER ',')")
            elif fmt == "parquet":
                self.con.execute(f"COPY {t} TO '{path}' (FORMAT PARQUET)")
            else:
                raise ValueError("fmt must be 'csv' or 'parquet'")
            written.append(path)
        return written

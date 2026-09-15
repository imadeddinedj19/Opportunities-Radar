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
    tier VARCHAR,
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
CREATE TABLE IF NOT EXISTS score_history (
    company_id VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    run_at TIMESTAMPTZ NOT NULL,
    score DOUBLE NOT NULL,
    rank INTEGER,
    PRIMARY KEY (company_id, model_version, run_at)
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
    "score_history",
    "product_relevance",
    "explanations",
    "outcome_labels",
)

# Conflict keys for INSERT-or-REPLACE style upserts (used by the Postgres backend's ON CONFLICT;
# the DuckDB backend uses INSERT OR REPLACE and does not need them).
PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "companies": ("company_id",),
    "sources": ("source_id",),
    "events": ("event_id",),
    "insights": ("insight_id",),
    "insight_sources": ("insight_id", "event_id"),
    "feature_snapshots": ("company_id", "snapshot_date", "feature_name", "feature_version"),
    "scores": ("company_id", "model_version"),
    "score_history": ("company_id", "model_version", "run_at"),
    "product_relevance": ("company_id", "model_version", "product_family"),
    "explanations": ("company_id", "model_version"),
    "outcome_labels": ("company_id",),
}


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

    def execute(self, sql: str, params: Sequence | None = None) -> None:
        """Run a statement (DDL/DELETE/UPDATE) - backend-agnostic entry point."""
        self.con.execute(sql, params or [])

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


# --------------------------------------------------------------------------------------------
# Postgres / Supabase backend
# --------------------------------------------------------------------------------------------
#
# Same method surface as the DuckDB Store, so the rest of the app is backend-agnostic. Selected
# by open_store() when settings.db_url is set. NOTE: this backend is code-complete but has not
# been executed against a live Postgres in the build sandbox (no database, no network) - validate
# on the target Supabase instance. DuckDB remains the default and is the tested path.

# Postgres flavour of the schema (DuckDB VARCHAR[]/DOUBLE -> TEXT[]/DOUBLE PRECISION).
PG_SCHEMA = (
    SCHEMA.replace("VARCHAR[]", "TEXT[]")
    .replace("DOUBLE PRECISION", "DOUBLE")  # guard against double-substitution
    .replace("DOUBLE", "DOUBLE PRECISION")
)


def _pg_placeholders(sql: str) -> str:
    """Translate DuckDB-style ``?`` params to Postgres ``%s`` (our SQL has no literal ?)."""
    return sql.replace("?", "%s")


class PostgresStore:
    """Postgres/Supabase-backed store with the same interface as the DuckDB Store."""

    def __init__(self, db_url: str):
        import psycopg  # imported lazily so the DuckDB path never needs the driver

        self.conn = psycopg.connect(db_url, autocommit=True)
        for stmt in filter(str.strip, PG_SCHEMA.split(";")):
            self.conn.execute(stmt)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> PostgresStore:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def execute(self, sql: str, params: Sequence | None = None) -> None:
        self.conn.execute(_pg_placeholders(sql), list(params) if params else None)

    def df(self, sql: str, params: Sequence | None = None) -> pd.DataFrame:
        cur = self.conn.execute(_pg_placeholders(sql), list(params) if params else None)
        cols = [d.name for d in cur.description] if cur.description else []
        return pd.DataFrame(cur.fetchall(), columns=cols)

    def columns(self, table: str) -> list[str]:
        cur = self.conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s ORDER BY ordinal_position",
            [table],
        )
        return [r[0] for r in cur.fetchall()]

    def upsert(self, table: str, records: Iterable[BaseModel]) -> int:
        rows = [r.model_dump(mode="python") for r in records]
        if not rows:
            return 0
        if table not in TABLES:
            raise ValueError(f"unknown table {table!r}")
        cols = [c for c in self.columns(table) if c in rows[0]]
        pk = PRIMARY_KEYS[table]
        updates = [c for c in cols if c not in pk]
        set_clause = (
            ", ".join(f"{c} = EXCLUDED.{c}" for c in updates)
            or f"{pk[0]} = EXCLUDED.{pk[0]}"
        )
        placeholders = "(" + ", ".join(["%s"] * len(cols)) + ")"
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES {placeholders} "
            f"ON CONFLICT ({', '.join(pk)}) DO UPDATE SET {set_clause}"
        )
        with self.conn.cursor() as cur:
            cur.executemany(sql, [[row.get(c) for c in cols] for row in rows])
        return len(rows)

    def count(self, table: str) -> int:
        return self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def counts(self) -> dict[str, int]:
        return {t: self.count(t) for t in TABLES}

    def export(self, out_dir: Path, fmt: str = "csv", tables: Sequence[str] = TABLES) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for t in tables:
            path = out_dir / f"{t}.{fmt}"
            frame = self.df(f"SELECT * FROM {t}")
            if fmt == "csv":
                frame.to_csv(path, index=False)
            elif fmt == "parquet":
                frame.to_parquet(path, index=False)
            else:
                raise ValueError("fmt must be 'csv' or 'parquet'")
            written.append(path)
        return written


def open_store(settings) -> Store | PostgresStore:
    """Return the storage backend for these settings: Postgres if db_url is set, else DuckDB."""
    if getattr(settings, "db_url", None):
        return PostgresStore(settings.db_url)
    return Store(settings.resolved_db_path)

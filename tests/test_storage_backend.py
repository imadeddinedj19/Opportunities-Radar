"""Storage backend selection and Postgres SQL translation (unit level, no live Postgres)."""

from radar.config import get_settings
from radar.storage import Store, _pg_placeholders, open_store


def test_open_store_defaults_to_duckdb(tmp_path):
    settings = get_settings(db_path=tmp_path / "t.duckdb")  # no db_url
    store = open_store(settings)
    try:
        assert isinstance(store, Store)  # DuckDB backend
    finally:
        store.close()


def test_pg_placeholder_translation():
    assert _pg_placeholders("WHERE a = ? AND b = ?") == "WHERE a = %s AND b = %s"


def test_pg_schema_is_postgres_flavoured():
    from radar.storage import PG_SCHEMA
    assert "TEXT[]" in PG_SCHEMA          # DuckDB VARCHAR[] -> Postgres TEXT[]
    assert "DOUBLE PRECISION" in PG_SCHEMA
    assert "VARCHAR[]" not in PG_SCHEMA

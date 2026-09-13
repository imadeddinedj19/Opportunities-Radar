"""Tests for sales-region classification and manual company lookup."""

from pathlib import Path

from radar.config import get_settings
from radar.ingest.pipeline import ingest_one, run
from radar.regions import REGIONS, geo_region, resolve_region
from radar.storage import Store

DATA = Path(__file__).resolve().parents[1] / "data"


def _settings(tmp_path):
    return get_settings(offline=True, data_dir=DATA, db_path=tmp_path / "t.duckdb")


def test_geo_region_mapping():
    assert geo_region("GB") == "UK"
    assert geo_region("US") == "US"
    assert geo_region("SG") == "Asia"
    assert geo_region("JP") == "Asia"
    assert geo_region("CH") == "EMEA"
    assert geo_region("AE") == "EMEA"
    assert geo_region(None) == "EMEA"


def test_strategic_overrides_geography():
    assert resolve_region("US", strategic=True) == "Strategic Accounts"
    assert resolve_region("US", strategic=False) == "US"
    assert "Strategic Accounts" in REGIONS


def test_pipeline_assigns_regions_and_strategic(tmp_path):
    settings = _settings(tmp_path)
    run(settings)
    with Store(settings.resolved_db_path) as store:
        regions = set(store.df("SELECT DISTINCT region FROM companies")["region"])
        assert regions.issubset(set(REGIONS))
        # every company has a region in the five buckets
        n_null = store.df("SELECT count(*) n FROM companies WHERE region IS NULL").iloc[0]["n"]
        assert n_null == 0
        # a seed-flagged strategic account lands in the Strategic Accounts bucket
        strat = store.df(
            "SELECT region FROM companies WHERE canonical_name LIKE 'Partners Group%'"
        ).iloc[0]["region"]
        assert strat == "Strategic Accounts"


def test_lookup_preserves_existing_attributes(tmp_path):
    settings = _settings(tmp_path)
    run(settings)
    # look up a company already in the seed without passing hints
    cid = ingest_one(settings, "Amundi SA")
    with Store(settings.resolved_db_path) as store:
        row = store.df(
            "SELECT segment, country FROM companies WHERE company_id = ?", [cid]
        ).iloc[0]
        # its seed attributes survive the lookup (not wiped to null)
        assert row["segment"] == "asset_manager"
        assert row["country"] == "FR"
        # it is scored and ranked among the full set
        n = store.df("SELECT count(*) n FROM scores WHERE company_id = ?", [cid]).iloc[0]["n"]
        assert n == 1

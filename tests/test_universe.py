"""Tests for the GLEIF universe importer and tiered ingest."""

import shutil
from pathlib import Path

from radar.config import get_settings
from radar.ingest.pipeline import run
from radar.regions import GEO_REGIONS
from radar.storage import Store
from radar.universe import import_universe, read_gleif

DATA = Path(__file__).resolve().parents[1] / "data"
SAMPLE = DATA / "fixtures" / "gleif" / "sample.csv"


def test_read_gleif_filters_inactive_and_maps_regions():
    rows, rep = read_gleif(SAMPLE)
    assert rep.read == 8
    assert rep.skipped_inactive == 2          # one INACTIVE, one LAPSED registration
    assert rep.kept == 6
    regions = {r["region"] for r in rows}
    assert regions.issubset(set(GEO_REGIONS))
    uk = [r for r in rows if r["country"] == "GB"][0]
    assert uk["region"] == "UK"


def test_import_merges_and_dedupes(tmp_path):
    seed = tmp_path / "companies.csv"
    shutil.copy(DATA / "seed" / "companies.csv", seed)
    before = sum(1 for _ in seed.open()) - 1
    rep = import_universe(SAMPLE, seed, per_region=1200)
    after = sum(1 for _ in seed.open()) - 1
    # Partners Group is already in the seed -> deduped, not added twice
    assert rep.skipped_dupe >= 1
    assert after == before + rep.added
    # imported rows carry tier cold and seed_source gleif
    import csv
    rows = list(csv.DictReader(seed.open()))
    imported = [r for r in rows if r.get("seed_source") == "gleif"]
    assert imported and all(r["tier"] == "cold" for r in imported)


def test_tier_filter_limits_ingest(tmp_path):
    # build a tiny data dir with a 2-tier seed
    ddir = tmp_path / "data"
    (ddir / "seed").mkdir(parents=True)
    shutil.copytree(DATA / "fixtures", ddir / "fixtures")
    seed = ddir / "seed" / "companies.csv"
    seed.write_text(
        "seed_name,country,segment,homepage,notes,strategic,tier,seed_source\n"
        "Partners Group Holding AG,CH,private_markets,,x,1,hot,manual_seed\n"
        "Cold Co,GB,,,,0,cold,gleif\n",
        encoding="utf-8",
    )
    settings = get_settings(offline=True, data_dir=ddir, db_path=tmp_path / "t.duckdb")
    run(settings, tiers={"hot"})
    with Store(settings.resolved_db_path) as store:
        names = set(store.df("SELECT canonical_name FROM companies")["canonical_name"])
    assert any("Partners Group" in n for n in names)
    assert "Cold Co" not in names          # cold tier filtered out

from pathlib import Path

from radar.config import get_settings
from radar.ingest import gdelt, news, wikidata, wikipedia
from radar.ingest.client import Fetcher

DATA = Path(__file__).resolve().parents[1] / "data"


def _fetcher():
    return Fetcher(get_settings(offline=True, data_dir=DATA))


def test_news_connector_parses_fixture():
    items = news.collect(_fetcher(), "Partners Group Holding AG")
    assert len(items) >= 3
    first = items[0]
    assert first["title"] and first["url"]
    assert first["event_date"] is not None       # FR-04: every signal carries its date
    assert first["publisher"]


def test_gdelt_connector_parses_fixture():
    items = gdelt.collect(_fetcher(), "Amundi SA")
    assert len(items) >= 1
    assert all(i["title"] for i in items)


def test_wikidata_enrichment_from_fixture():
    enr = wikidata.enrich(_fetcher(), "BlackRock Inc")
    assert enr.get("employees") == 19800
    assert enr.get("listed") is True
    assert enr.get("wikidata_id") == "Q219635"


def test_wikipedia_description_from_fixture():
    desc = wikipedia.describe(_fetcher(), "Schroders plc")
    assert "asset management" in desc["description"].lower()


def test_offline_miss_returns_empty():
    # A company with no fixture yields no events, no crash (graceful degradation).
    assert news.collect(_fetcher(), "Nonexistent Company XYZ") == []

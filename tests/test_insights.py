"""Tests for cross-source deduplication into distinct insights."""

from datetime import date
from pathlib import Path

from radar.config import get_settings
from radar.ingest import sec_edgar, yahoo_finance
from radar.ingest.client import Fetcher
from radar.insights import _cluster_company_events
from radar.storage import Store

DATA = Path(__file__).resolve().parents[1] / "data"


def _fetcher():
    return Fetcher(get_settings(offline=True, data_dir=DATA))


# ---- new connectors parse their fixtures --------------------------------------------------


def test_yahoo_connector_parses_fixture():
    items = yahoo_finance.collect(_fetcher(), "Partners Group Holding AG")
    assert len(items) >= 1
    assert items[0]["title"] and items[0]["url"]
    assert items[0]["event_date"] is not None


def test_edgar_connector_parses_fixture():
    items = sec_edgar.collect(_fetcher(), "Partners Group Holding AG")
    assert len(items) >= 1
    assert all(i["publisher"] == "SEC EDGAR" for i in items)
    assert any("8-K" in i["title"] or "10-K" in i["title"] for i in items)


# ---- the clustering logic in isolation ----------------------------------------------------


def _ev(eid, title, day, connector):
    return {
        "event_id": eid, "title": title, "event_type": "acquisition",
        "event_date": date(2026, 8, day), "url": f"http://x/{eid}",
        "publisher": connector, "connector": connector,
    }


def test_same_story_from_three_sources_is_one_cluster():
    events = [
        _ev("a", "Acme acquires Beta Corp for 500m", 10, "google_news_rss"),
        _ev("b", "Acme acquires Beta Corp for 500m", 11, "gdelt"),
        _ev("c", "Acme acquires Beta Corp", 10, "yahoo_finance"),
    ]
    clusters = _cluster_company_events(events, sim_threshold=82.0, window_days=10)
    assert len(clusters) == 1
    assert {e["connector"] for e in clusters[0]} == {"google_news_rss", "gdelt", "yahoo_finance"}


def test_different_stories_stay_separate():
    events = [
        _ev("a", "Acme acquires Beta Corp", 10, "google_news_rss"),
        _ev("b", "Acme launches new ESG fund range", 10, "gdelt"),
    ]
    clusters = _cluster_company_events(events, sim_threshold=82.0, window_days=10)
    assert len(clusters) == 2


def test_same_title_far_apart_in_time_stays_separate():
    events = [
        _ev("a", "Acme files quarterly report", 1, "sec_edgar"),
        _ev("b", "Acme files quarterly report", 28, "sec_edgar"),
    ]
    clusters = _cluster_company_events(events, sim_threshold=82.0, window_days=10)
    assert len(clusters) == 2


# ---- end-to-end dedup on the offline sample -----------------------------------------------


def _settings(tmp_path):
    return get_settings(offline=True, data_dir=DATA, db_path=tmp_path / "t.duckdb")


def test_end_to_end_dedup_merges_across_connectors(tmp_path):
    from radar.ingest.pipeline import run
    settings = _settings(tmp_path)
    run(settings)
    with Store(settings.resolved_db_path) as store:
        # The Partners Group acquisition is reported by three connectors -> one insight, 3 sources.
        acq = store.df(
            """
            SELECT i.insight_id, i.source_count, i.connectors
            FROM insights i JOIN companies c USING (company_id)
            WHERE c.canonical_name LIKE 'Partners Group%' AND i.insight_type = 'acquisition'
            """
        )
        assert len(acq) == 1
        assert acq.iloc[0]["source_count"] == 3
        assert set(acq.iloc[0]["connectors"]) == {"google_news_rss", "gdelt", "yahoo_finance"}
        # And that insight lists all three source rows with their provenance.
        srcs = store.df(
            "SELECT connector, url FROM insight_sources WHERE insight_id = ?",
            [acq.iloc[0]["insight_id"]],
        )
        assert len(srcs) == 3
        assert srcs["url"].notna().all()


def test_new_flag_is_false_on_second_run(tmp_path):
    from radar.ingest.pipeline import run
    settings = _settings(tmp_path)
    first = run(settings)
    assert first.insights_new > 0
    second = run(settings)
    assert second.insights_new == 0
    assert second.insights_total == first.insights_total
    with Store(settings.resolved_db_path) as store:
        assert store.df("SELECT count(*) n FROM insights WHERE is_new").iloc[0]["n"] == 0


def test_insight_ids_do_not_collide_on_shared_prefix(tmp_path):
    """Regression: two SEC filings sharing a long title prefix must be distinct insights."""
    from radar.ingest.pipeline import run
    settings = _settings(tmp_path)
    run(settings)
    with Store(settings.resolved_db_path) as store:
        edgar = store.df(
            """
            SELECT i.insight_id FROM insights i JOIN companies c USING (company_id)
            WHERE c.canonical_name LIKE 'Partners Group%'
              AND list_contains(i.connectors, 'sec_edgar')
            """
        )
        assert len(edgar) == 2
        assert edgar["insight_id"].nunique() == 2

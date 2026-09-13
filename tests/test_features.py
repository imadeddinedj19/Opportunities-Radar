"""Tests for S2 feature engineering."""

from pathlib import Path

from radar.config import get_settings
from radar.features import FEATURE_VERSION, build_features, tfidf_cosine_to_target
from radar.ingest.pipeline import run
from radar.storage import Store

DATA = Path(__file__).resolve().parents[1] / "data"


def _settings(tmp_path):
    return get_settings(offline=True, data_dir=DATA, db_path=tmp_path / "t.duckdb")


def test_tfidf_prefers_financial_text():
    docs = [
        "swiss private markets asset manager funds acquisition expansion",
        "a neighbourhood bakery selling bread and pastries",
    ]
    sims = tfidf_cosine_to_target(docs, "asset manager funds market data acquisition")
    assert 0.0 <= sims[1] <= sims[0] <= 1.0
    assert sims[0] > sims[1]


def test_features_written_for_every_company(tmp_path):
    settings = _settings(tmp_path)
    run(settings)
    report = build_features(settings)
    with Store(settings.resolved_db_path) as store:
        n_companies = store.count("companies")
        n_features = store.df(
            "SELECT count(DISTINCT feature_name) n FROM feature_snapshots"
        ).iloc[0]["n"]
        total = store.count("feature_snapshots")
        assert report.companies == n_companies
        assert total == n_companies * n_features   # dense: every company has every feature
        # snapshots are dated and versioned
        bad = store.df(
            "SELECT count(*) n FROM feature_snapshots WHERE snapshot_date IS NULL "
            "OR feature_version <> ?",
            [FEATURE_VERSION],
        ).iloc[0]["n"]
        assert bad == 0


def test_signal_features_track_reality(tmp_path):
    settings = _settings(tmp_path)
    run(settings)
    with Store(settings.resolved_db_path) as store:
        # A company with events (Partners Group) outscores a company without on recency.
        pg = store.df(
            """SELECT value FROM feature_snapshots f JOIN companies c USING(company_id)
               WHERE c.canonical_name LIKE 'Partners Group%' AND f.feature_name='recency_score'"""
        ).iloc[0]["value"]
        assert pg > 0
        # profile_similarity is bounded 0..1 for all companies
        sim = store.df(
            "SELECT min(value) lo, max(value) hi FROM feature_snapshots "
            "WHERE feature_name='profile_similarity'"
        ).iloc[0]
        assert 0.0 <= sim["lo"] and sim["hi"] <= 1.0


def test_features_are_deterministic(tmp_path):
    settings = _settings(tmp_path)
    run(settings)
    first = build_features(settings)
    with Store(settings.resolved_db_path) as store:
        snap1 = store.df(
            "SELECT company_id, feature_name, value FROM feature_snapshots ORDER BY 1,2"
        )
    second = build_features(settings)
    with Store(settings.resolved_db_path) as store:
        snap2 = store.df(
            "SELECT company_id, feature_name, value FROM feature_snapshots ORDER BY 1,2"
        )
    assert first.features_written == second.features_written
    assert snap1.equals(snap2)

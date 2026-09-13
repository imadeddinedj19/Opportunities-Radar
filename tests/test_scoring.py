"""Tests for S3 scoring + product compatibility."""

from pathlib import Path

from radar.config import get_settings
from radar.ingest.pipeline import run
from radar.models import ProductFamily as PF
from radar.products import best_product, product_relevance_raw, to_display
from radar.scoring import MODEL_VERSION, run_scoring
from radar.storage import Store

DATA = Path(__file__).resolve().parents[1] / "data"


def _settings(tmp_path):
    return get_settings(offline=True, data_dir=DATA, db_path=tmp_path / "t.duckdb")


# ---- product compatibility -----------------------------------------------------------------


def test_asset_manager_maps_to_funds_data():
    raw = product_relevance_raw("asset_manager", ["product_launch"], "launches new fund and ETF")
    assert best_product(raw)[0] == PF.FUNDS_DATA


def test_insurer_maps_to_regulatory():
    raw = product_relevance_raw("insurer", [], "insurance group")
    assert best_product(raw)[0] == PF.REGULATORY_TAX


def test_exchange_maps_to_market_data():
    raw = product_relevance_raw("exchange", ["expansion"], "operates regulated markets")
    assert best_product(raw)[0] == PF.MARKET_DATA


def test_display_normalizes_top_to_one():
    raw = product_relevance_raw("asset_manager", ["product_launch"], "new fund")
    disp = to_display(raw)
    assert abs(max(disp.values()) - 1.0) < 1e-9
    assert all(0.0 <= v <= 1.0 for v in disp.values())


# ---- end-to-end scoring --------------------------------------------------------------------


def test_scoring_ranks_all_companies(tmp_path):
    settings = _settings(tmp_path)
    run(settings)
    report = run_scoring(settings)
    with Store(settings.resolved_db_path) as store:
        n = store.count("companies")
        assert report.scored == n
        # every company has a product-relevance row per family and an explanation
        assert store.count("product_relevance") == n * len(list(PF))
        assert store.count("explanations") == n
        # ranks are a unique 1..n sequence
        ranks = store.df("SELECT rank FROM scores ORDER BY rank")["rank"].tolist()
        assert ranks == list(range(1, n + 1))
        # scores are within 0..100
        mm = store.df("SELECT min(score) lo, max(score) hi FROM scores").iloc[0]
        assert 0.0 <= mm["lo"] and mm["hi"] <= 100.0


def test_companies_with_signals_outrank_quiet_ones(tmp_path):
    settings = _settings(tmp_path)
    run(settings)
    run_scoring(settings)
    with Store(settings.resolved_db_path) as store:
        pg_rank = store.df(
            """SELECT s.rank FROM scores s JOIN companies c USING(company_id)
               WHERE c.canonical_name LIKE 'Partners Group%'"""
        ).iloc[0]["rank"]
        # a seed company with no collected events should rank well below it
        quiet_rank = store.df(
            """SELECT s.rank FROM scores s JOIN companies c USING(company_id)
               WHERE c.canonical_name LIKE 'Allianz SE%'"""
        ).iloc[0]["rank"]
        assert pg_rank < quiet_rank
        # the top-ranked company is one of the signal-rich fixtures
        top = store.df(
            "SELECT c.canonical_name n FROM scores s JOIN companies c USING(company_id) "
            "WHERE s.rank = 1"
        ).iloc[0]["n"]
        assert top in {
            "Partners Group Holding AG", "Amundi SA", "BlackRock Inc",
            "Schroders plc", "Euronext NV", "Julius Baer Group Ltd",
        }


def test_top_company_has_product_and_explanation(tmp_path):
    settings = _settings(tmp_path)
    run(settings)
    run_scoring(settings)
    with Store(settings.resolved_db_path) as store:
        row = store.df(
            """
            SELECT c.company_id, e.reason,
                   (SELECT p.product_family FROM product_relevance p
                    WHERE p.company_id = c.company_id ORDER BY p.relevance_score DESC LIMIT 1) fam
            FROM scores s JOIN companies c USING(company_id)
            JOIN explanations e USING(company_id)
            WHERE s.rank = 1
            """
        ).iloc[0]
        assert row["fam"]                      # a product is recommended
        assert "product fit" in row["reason"].lower()


def test_scoring_is_deterministic(tmp_path):
    settings = _settings(tmp_path)
    run(settings)
    a = run_scoring(settings)
    with Store(settings.resolved_db_path) as store:
        s1 = store.df("SELECT company_id, score, rank FROM scores ORDER BY rank")
    b = run_scoring(settings)
    with Store(settings.resolved_db_path) as store:
        s2 = store.df("SELECT company_id, score, rank FROM scores ORDER BY rank")
    assert a.scored == b.scored
    assert s1.equals(s2)
    assert MODEL_VERSION == "s3-baseline-v1"

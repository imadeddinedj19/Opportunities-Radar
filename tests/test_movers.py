"""Test the movers (what-changed) comparison across two scoring runs."""

import time
from pathlib import Path

from radar.config import get_settings
from radar.ingest.pipeline import run
from radar.movers import compute_movers
from radar.scoring import run_scoring
from radar.storage import Store

DATA = Path(__file__).resolve().parents[1] / "data"


def _settings(tmp_path):
    return get_settings(offline=True, data_dir=DATA, db_path=tmp_path / "t.duckdb")


def test_one_run_has_nothing_to_compare(tmp_path):
    settings = _settings(tmp_path)
    run(settings)
    rep = compute_movers(settings)
    assert rep.runs_available == 1
    assert rep.movers == []


def test_detects_a_riser_between_runs(tmp_path):
    settings = _settings(tmp_path)
    run(settings)
    # give a quiet company a burst of signal, then re-score -> a second history point
    with Store(settings.resolved_db_path) as store:
        cid = store.df(
            "SELECT company_id FROM companies WHERE canonical_name LIKE 'Man Group%'"
        ).iloc[0]["company_id"]
        for feat, val in (("relevant_event_count", 6), ("recency_score", 8), ("sources_max", 3)):
            store.con.execute(
                "UPDATE feature_snapshots SET value=? WHERE company_id=? AND feature_name=?",
                [val, cid, feat],
            )
    time.sleep(1.05)
    run_scoring(settings)
    rep = compute_movers(settings)
    assert rep.runs_available == 2
    names = {m.name for m in rep.risers}
    assert any("Man Group" in n for n in names)
    top = max(rep.risers, key=lambda m: m.delta)
    assert top.delta > 10 and top.previous is not None

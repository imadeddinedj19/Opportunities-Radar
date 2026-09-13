"""Test the proxy evaluation: the score should beat random on the proxy target."""

from pathlib import Path

from radar.config import get_settings
from radar.evaluate import run_evaluation
from radar.ingest.pipeline import run

DATA = Path(__file__).resolve().parents[1] / "data"


def _settings(tmp_path):
    return get_settings(offline=True, data_dir=DATA, db_path=tmp_path / "t.duckdb")


def test_score_beats_random_on_proxy(tmp_path):
    settings = _settings(tmp_path)
    run(settings)
    rep = run_evaluation(settings)
    assert rep.positives > 0
    by_name = {r.name: r for r in rep.rankers}
    full = by_name["Opportunity score (full)"]
    rand = by_name["Random"]
    # the score ranks proxy-positives far above chance; random should not
    assert full.precision_at_k > rep.base_rate
    assert full.lift > 1.0
    assert full.precision_at_k >= rand.precision_at_k

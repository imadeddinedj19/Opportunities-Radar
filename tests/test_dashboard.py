"""Tests for the S4 dashboard generator (data + HTML assembly, run headless-free)."""

import json
import re
from pathlib import Path

import pytest

from radar.config import get_settings
from radar.dashboard import build_dashboard, collect_data
from radar.ingest.pipeline import run
from radar.storage import Store

DATA = Path(__file__).resolve().parents[1] / "data"


def _settings(tmp_path):
    return get_settings(offline=True, data_dir=DATA, db_path=tmp_path / "t.duckdb")


def test_collect_data_shape(tmp_path):
    settings = _settings(tmp_path)
    run(settings)
    with Store(settings.resolved_db_path) as store:
        data = collect_data(store)
    assert len(data["companies"]) == store_count(settings)
    top = data["companies"][0]
    assert top["rank"] == 1
    assert top["products"] and top["best_product_label"]
    # every company carries a full 6-family product breakdown
    assert all(len(c["products"]) == 6 for c in data["companies"])
    # summary numbers are present
    for k in ("companies", "with_signals", "insights", "events"):
        assert k in data["summary"]


def store_count(settings):
    with Store(settings.resolved_db_path) as store:
        return store.count("scores")


def test_build_dashboard_writes_valid_html(tmp_path):
    settings = _settings(tmp_path)
    run(settings)
    out = build_dashboard(settings, tmp_path / "dash.html")
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "<title>Opportunity Radar</title>" in html
    assert "Partners Group" in html
    assert 'id="detail"' in html
    # embedded data blob parses and carries every company
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    blob = json.loads(m.group(1))
    assert len(blob["companies"]) >= 100
    # rows are pre-rendered for at-rest content (no blank shell)
    assert html.count('class="row"') == len(blob["companies"])


def test_top_company_is_signal_rich(tmp_path):
    settings = _settings(tmp_path)
    run(settings)
    with Store(settings.resolved_db_path) as store:
        data = collect_data(store)
    assert data["companies"][0]["n_signals"] > 0


def test_dashboard_requires_scores(tmp_path):
    settings = _settings(tmp_path)
    # init an empty db (no ingest) -> no scores -> friendly error
    with Store(settings.resolved_db_path):
        pass
    with pytest.raises(RuntimeError):
        build_dashboard(settings, tmp_path / "d.html")

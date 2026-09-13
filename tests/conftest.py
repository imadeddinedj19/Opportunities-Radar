from __future__ import annotations

from pathlib import Path

import pytest

from radar.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def offline_settings(tmp_path):
    """Offline settings that read the real fixtures/seed but write to a temp DB."""
    data_dir = PROJECT_ROOT / "data"
    return get_settings(
        offline=True,
        data_dir=data_dir,
        db_path=tmp_path / "test.duckdb",
    )

"""Runtime settings for the POC.

Everything here can be overridden with an environment variable prefixed ``RADAR_``
(for example ``RADAR_OFFLINE=1`` or ``RADAR_DATA_DIR=/somewhere``), or a ``.env`` file
in the project root. Keeping all knobs in one place is what lets the same pipeline run
identically on a laptop, in CI, or later in an approved cloud environment (NFR-03).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RADAR_", env_file=".env", extra="ignore")

    # --- Storage -------------------------------------------------------------------------
    data_dir: Path = PROJECT_ROOT / "data"
    db_path: Path | None = None  # defaults to <data_dir>/db/radar.duckdb

    # --- Collection behaviour ------------------------------------------------------------
    offline: bool = Field(
        default=False,
        description="Replay recorded fixtures instead of calling public sources.",
    )
    record_fixtures: bool = Field(
        default=False,
        description="When collecting live, also save each response as a fixture for offline runs.",
    )
    user_agent: str = (
        "OpportunityRadarPOC/0.1 (research prototype; contact: see repository README)"
    )
    min_seconds_between_requests: float = 1.0  # polite crawling: at most 1 request/second/host
    request_timeout_seconds: float = 20.0
    max_retries: int = 3

    # --- Event collection ----------------------------------------------------------------
    event_lookback_days: int = 180
    max_events_per_company_per_source: int = 50
    news_languages: tuple[str, ...] = ("en",)

    @property
    def seed_path(self) -> Path:
        return self.data_dir / "seed" / "companies.csv"

    @property
    def fixtures_dir(self) -> Path:
        return self.data_dir / "fixtures"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def resolved_db_path(self) -> Path:
        return self.db_path or (self.data_dir / "db" / "radar.duckdb")


def get_settings(**overrides) -> Settings:
    return Settings(**overrides)

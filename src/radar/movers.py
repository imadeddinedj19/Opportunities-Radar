"""Movers - what changed since the last run.

A static ranking gets stale: a rep who read it on Monday has no reason to open it on Tuesday.
The movers view answers the question they actually have, "what is different today?", by comparing
the two most recent scoring runs held in ``score_history``:

* **new**    - scored for the first time (or first time above the attention threshold)
* **riser**  - score climbed materially since the previous run
* **faller** - score dropped materially

Only the *comparison* lives here; the scores themselves are produced by ``radar.scoring``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from radar.config import Settings
from radar.scoring import MODEL_VERSION
from radar.storage import open_store

DEFAULT_MIN_DELTA = 3.0   # points of score change worth showing
NEW_THRESHOLD = 20.0      # a first-time company must reach this to count as "newly flagged"


@dataclass
class Mover:
    company_id: str
    name: str
    region: str
    segment: str
    score: float
    previous: float | None
    delta: float
    rank: int | None
    previous_rank: int | None
    kind: str  # "new" | "riser" | "faller"

    @property
    def rank_delta(self) -> int | None:
        if self.rank is None or self.previous_rank is None:
            return None
        return self.previous_rank - self.rank  # positive = moved up the list


@dataclass
class MoversReport:
    current_run: datetime | None = None
    previous_run: datetime | None = None
    runs_available: int = 0
    movers: list[Mover] = field(default_factory=list)

    @property
    def risers(self) -> list[Mover]:
        return [m for m in self.movers if m.kind == "riser"]

    @property
    def fallers(self) -> list[Mover]:
        return [m for m in self.movers if m.kind == "faller"]

    @property
    def new(self) -> list[Mover]:
        return [m for m in self.movers if m.kind == "new"]


def compute_movers(settings: Settings, min_delta: float = DEFAULT_MIN_DELTA) -> MoversReport:
    report = MoversReport()
    with open_store(settings) as store:
        runs = store.df(
            "SELECT DISTINCT run_at FROM score_history WHERE model_version = ? "
            "ORDER BY run_at DESC LIMIT 2",
            [MODEL_VERSION],
        )
        report.runs_available = len(runs)
        if runs.empty:
            return report
        report.current_run = runs.iloc[0]["run_at"]
        if len(runs) < 2:
            return report  # nothing to compare against yet
        report.previous_run = runs.iloc[1]["run_at"]

        rows = store.df(
            """
            SELECT c.company_id, c.canonical_name, c.region, c.segment,
                   cur.score AS score, cur.rank AS rank,
                   prev.score AS prev_score, prev.rank AS prev_rank
            FROM score_history cur
            JOIN companies c USING (company_id)
            LEFT JOIN score_history prev
              ON prev.company_id = cur.company_id
             AND prev.model_version = cur.model_version
             AND prev.run_at = ?
            WHERE cur.model_version = ? AND cur.run_at = ?
            """,
            [report.previous_run, MODEL_VERSION, report.current_run],
        )

        def _num(v):
            # DuckDB LEFT JOIN misses come back as NaN; normalize to None/int.
            return None if v is None or v != v else v

        movers: list[Mover] = []
        for r in rows.itertuples():
            score = float(r.score)
            prev = _num(r.prev_score)
            if prev is None:
                if score < NEW_THRESHOLD:
                    continue
                kind, delta = "new", score
            else:
                prev = float(prev)
                delta = round(score - prev, 2)
                if abs(delta) < min_delta:
                    continue
                kind = "riser" if delta > 0 else "faller"
            rank = _num(r.rank)
            prev_rank = _num(r.prev_rank)
            movers.append(Mover(
                company_id=r.company_id, name=r.canonical_name,
                region=r.region or "", segment=r.segment or "",
                score=round(score, 1), previous=(round(prev, 1) if prev is not None else None),
                delta=round(delta, 1),
                rank=(int(rank) if rank is not None else None),
                previous_rank=(int(prev_rank) if prev_rank is not None else None),
                kind=kind,
            ))
        movers.sort(key=lambda m: (m.kind != "new", -abs(m.delta)))
        report.movers = movers
    return report

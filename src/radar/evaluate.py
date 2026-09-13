"""Evaluation - does the score actually rank the right companies? (FR-13, Tech Design §10).

The external POC has no real won/lost outcomes, so we cannot measure true accuracy. What we *can*
do honestly is a **proxy feasibility test**: define a defensible stand-in for "looks like a real
opportunity", then check whether the opportunity score surfaces those companies far better than
two references - ranking by static company profile alone (no events), and random order.

Proxy-positive = a company with >= 2 commercially-relevant events corroborated by >= 2 independent
sources. It is a stand-in for "meaningful, real, recent activity", not a sales outcome.

Metrics (at K = number of positives, where precision == recall):
  * Precision@K  - of the top-K ranked companies, the fraction that are proxy-positive.
  * Lift         - Precision@K divided by the base rate (random expectation). >1 means better
                   than chance.

Honesty: the full score is built partly from the same signals as the proxy, so a high score here
is a sanity check that the event signals carry ranking power over a profile-only baseline - it is
NOT evidence of real-world conversion accuracy. That requires approved CRM outcomes (a future
segment). The value of this test is the *gap* between the full score and the profile-only baseline.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from radar.config import Settings
from radar.scoring import MODEL_VERSION
from radar.storage import Store

REL_MIN = 2.0       # >= 2 relevant events
SOURCES_MIN = 2.0   # corroborated by >= 2 sources


@dataclass
class RankerResult:
    name: str
    precision_at_k: float
    recall_at_k: float
    lift: float
    hits_at_k: int


@dataclass
class EvalReport:
    n: int = 0
    positives: int = 0
    base_rate: float = 0.0
    k: int = 0
    rankers: list[RankerResult] = field(default_factory=list)


def _features(store: Store) -> dict[str, dict[str, float]]:
    df = store.df("SELECT company_id, feature_name, value FROM feature_snapshots")
    out: dict[str, dict[str, float]] = {}
    for r in df.itertuples():
        out.setdefault(r.company_id, {})[r.feature_name] = float(r.value)
    return out


def _precision_at_k(ranked: list[str], positives: set[str], k: int) -> tuple[float, int]:
    topk = ranked[:k]
    hits = sum(1 for c in topk if c in positives)
    return (hits / k if k else 0.0), hits


def run_evaluation(settings: Settings, seed: int = 42) -> EvalReport:
    report = EvalReport()
    with Store(settings.resolved_db_path) as store:
        if store.count("scores") == 0:
            raise RuntimeError("No scores in the database. Run `radar ingest` first.")
        feats = _features(store)
        scores = store.df(
            "SELECT company_id, score FROM scores WHERE model_version = ?", [MODEL_VERSION]
        )

    ids = list(feats.keys())
    report.n = len(ids)
    positives = {
        cid for cid, f in feats.items()
        if f.get("relevant_event_count", 0) >= REL_MIN and f.get("sources_max", 0) >= SOURCES_MIN
    }
    report.positives = len(positives)
    report.base_rate = len(positives) / len(ids) if ids else 0.0
    k = max(len(positives), 1)
    report.k = k

    # ranker 1: the full opportunity score
    full_rank = [r.company_id for r in
                 scores.sort_values("score", ascending=False).itertuples()]

    # ranker 2: profile-only baseline (static fit, no events/timing)
    def profile_score(f: dict[str, float]) -> float:
        return (f.get("size_rank", 0) / 5.0) + f.get("is_listed", 0) \
            + f.get("profile_similarity", 0)
    profile_rank = sorted(ids, key=lambda c: profile_score(feats[c]), reverse=True)

    # ranker 3: random order (seeded, reproducible)
    rng = random.Random(seed)
    random_rank = ids[:]
    rng.shuffle(random_rank)

    for name, ranked in (("Opportunity score (full)", full_rank),
                         ("Company profile only", profile_rank),
                         ("Random", random_rank)):
        p, hits = _precision_at_k(ranked, positives, k)
        lift = (p / report.base_rate) if report.base_rate else 0.0
        report.rankers.append(
            RankerResult(name=name, precision_at_k=round(p, 3), recall_at_k=round(p, 3),
                         lift=round(lift, 2), hits_at_k=hits)
        )
    return report

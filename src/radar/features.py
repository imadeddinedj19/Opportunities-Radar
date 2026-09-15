"""Feature engineering - S2 (FR-06): turn companies + events + insights into model-ready features.

A *feature* is a single numeric input a model reads. Raw text and event rows are not something a
model can learn from directly; feature engineering converts them into numbers on comparable
scales. Each feature we compute is written as a ``FeatureSnapshot`` row (company, snapshot_date,
feature_name, value) so the exact inputs behind any future score are reproducible (NFR-03, NFR-07).

Feature families:
  * intensity      - how many relevant events/insights (counts, incl. per relevant type)
  * recency        - how recent and how fast-moving the signals are (half-life weighted)
  * corroboration  - how many independent sources back the company's insights
  * diversity      - how many distinct kinds of event
  * fit            - company characteristics (size, listed, has a public description)
  * profile_similarity - TF-IDF cosine of the company's public text vs a target-customer profile

TF-IDF (term frequency-inverse document frequency) weights each word by how distinctive it is
across all companies, then measures cosine similarity (angle between the weighted word vectors).
It is a transparent, offline stand-in for the sentence-embedding similarity planned for a
networked environment - same idea (does this company read like our ideal customer?), simpler maths.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from radar.config import Settings
from radar.models import FeatureSnapshot, utcnow
from radar.storage import open_store

FEATURE_VERSION = "s2-v1"

# Event types that plausibly precede a rise in demand for financial-information products.
RELEVANT_TYPES = ("acquisition", "expansion", "product_launch", "funding", "partnership")

SIZE_RANK = {"micro": 1, "small": 2, "medium": 3, "large": 4, "enterprise": 5, "unknown": 0}

RECENCY_HALF_LIFE_DAYS = 45  # a signal's weight halves every ~6 weeks

# A short description of the kind of company that tends to need SIX-style financial data. The
# similarity feature scores each company's public text against this. Tunable via settings later.
TARGET_PROFILE = (
    "asset manager wealth management fund launch new investment product private markets "
    "exchange market data reference data corporate actions custody securities pricing "
    "regulatory reporting esg data acquisition expansion financial information analytics"
)

_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with", "is", "are", "as",
    "at", "by", "its", "it", "that", "this", "from", "was", "were", "be", "has", "have", "into",
    "group", "company", "ag", "sa", "plc", "inc", "ltd", "holding", "corporation", "based",
}


def _tokenize(text: str | None) -> list[str]:
    if not text:
        return []
    words = re.split(r"[^a-z0-9]+", text.lower())
    return [w for w in words if len(w) >= 3 and w not in _STOP]


def tfidf_cosine_to_target(docs: list[str], target: str) -> list[float]:
    """Cosine similarity (0-1) of each doc to ``target`` using TF-IDF weights over docs+target."""
    corpus_tokens = [_tokenize(d) for d in docs] + [_tokenize(target)]
    n_docs = len(corpus_tokens)
    df: dict[str, int] = {}
    for toks in corpus_tokens:
        for w in set(toks):
            df[w] = df.get(w, 0) + 1
    idf = {w: math.log((1 + n_docs) / (1 + c)) + 1.0 for w, c in df.items()}

    def vec(toks: list[str]) -> dict[str, float]:
        if not toks:
            return {}
        tf: dict[str, int] = {}
        for w in toks:
            tf[w] = tf.get(w, 0) + 1
        return {w: (c / len(toks)) * idf[w] for w, c in tf.items()}

    target_vec = vec(corpus_tokens[-1])

    def cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        dot = sum(a[w] * b.get(w, 0.0) for w in a)
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0

    return [round(cosine(vec(toks), target_vec), 4) for toks in corpus_tokens[:-1]]


@dataclass
class FeatureReport:
    companies: int = 0
    features_written: int = 0
    feature_names: list[str] = field(default_factory=list)


def build_features(settings: Settings, today: date | None = None) -> FeatureReport:
    today = today or date.today()
    snapshot_date = today
    report = FeatureReport()

    with open_store(settings) as store:
        companies = store.df(
            "SELECT company_id, canonical_name, segment, description, size_band, listed "
            "FROM companies"
        )
        events = store.df(
            "SELECT company_id, event_type, event_date FROM events"
        )
        insights = store.df(
            "SELECT company_id, source_count, insight_type FROM insights"
        )

        # profile similarity over all companies at once (shared IDF)
        docs = [
            f"{row.segment or ''} {row.description or ''}"
            for row in companies.itertuples()
        ]
        sims = tfidf_cosine_to_target(docs, TARGET_PROFILE)
        sim_by_company = dict(zip(companies["company_id"], sims, strict=False))

        snapshots: list[FeatureSnapshot] = []

        def add(cid: str, name: str, value: float) -> None:
            snapshots.append(
                FeatureSnapshot(
                    company_id=cid,
                    snapshot_date=snapshot_date,
                    feature_name=name,
                    value=float(value),
                    feature_version=FEATURE_VERSION,
                )
            )

        for row in companies.itertuples():
            cid = row.company_id
            ev = events[events["company_id"] == cid]
            ins = insights[insights["company_id"] == cid]

            # intensity
            add(cid, "events_total", len(ev))
            add(cid, "insights_total", len(ins))
            relevant = ev[ev["event_type"].isin(RELEVANT_TYPES)]
            add(cid, "relevant_event_count", len(relevant))

            # recency / momentum
            ages = []
            for ed in ev["event_date"].dropna():
                d = ed.date() if hasattr(ed, "date") else ed
                ages.append((today - d).days)
            add(cid, "events_90d", sum(1 for a in ages if 0 <= a <= 90))
            add(cid, "events_180d", sum(1 for a in ages if 0 <= a <= 180))
            add(cid, "days_since_last_event", min([a for a in ages if a >= 0], default=9999))
            recency = sum(0.5 ** (a / RECENCY_HALF_LIFE_DAYS) for a in ages if a >= 0)
            add(cid, "recency_score", round(recency, 4))

            # corroboration
            add(cid, "sources_max", int(ins["source_count"].max()) if len(ins) else 0)
            smean = round(float(ins["source_count"].mean()), 3) if len(ins) else 0.0
            add(cid, "sources_mean", smean)

            # diversity
            add(cid, "distinct_event_types", int(ev["event_type"].nunique()) if len(ev) else 0)

            # fit (listed / description may be SQL NULL -> pandas NA, so guard before bool())
            add(cid, "size_rank", SIZE_RANK.get(row.size_band, 0))
            listed = row.listed
            add(cid, "is_listed", 1 if (not pd.isna(listed) and bool(listed)) else 0)
            desc = row.description
            has_desc = (not pd.isna(desc)) and bool(str(desc).strip())
            add(cid, "has_description", 1 if has_desc else 0)

            # text-profile fit
            add(cid, "profile_similarity", sim_by_company.get(cid, 0.0))

        # rewrite this feature version cleanly
        store.execute(
            "DELETE FROM feature_snapshots WHERE feature_version = ?", [FEATURE_VERSION]
        )
        report.features_written = store.upsert("feature_snapshots", snapshots)
        report.companies = len(companies)
        report.feature_names = sorted({s.feature_name for s in snapshots})
    _ = utcnow  # keep import used for parity with other modules
    return report

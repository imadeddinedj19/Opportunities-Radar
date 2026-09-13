"""Opportunity scoring - S3 (FR-07/08/09/10/11).

Produces, for every company:
  * a 0-100 **Opportunity Score** = a transparent weighted blend of TIMING and FIT,
  * a **product recommendation** = the best-fitting SIX product family + a relevance breakdown,
  * an **Explanation** = plain-language reasons plus the evidence (the sources behind the signals).

This is the "baseline" of the Requirements Spec (FR-13): a weighted, fully explainable model, so
a sales manager can see exactly why a company ranks where it does (NFR-04/08). It needs no training
labels, which the external POC does not have. An ML model on proxy labels is the documented next
step in docs/ROADMAP.md.

The blend (weights sum to 1.0):

    TIMING  (is now the moment?)              FIT (does this company need SIX data?)
      recency_score        0.25                best_product_relevance   0.22   <- SIX product fit
      relevant_event_count 0.15                profile_similarity       0.13
      sources_max          0.15                company_fit (size+listed)0.10

Each input is min-max normalized across the scored companies, so the score is relative to the
current batch and easy to read as 0-100 (a known POC simplification; noted for management).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from radar.config import Settings
from radar.models import Explanation, ProductRelevance, Score, utcnow
from radar.products import PRODUCT_LABEL, best_product, product_relevance_raw, to_display
from radar.storage import Store

MODEL_VERSION = "s3-baseline-v1"

WEIGHTS = {
    "recency_score": 0.25,
    "relevant_event_count": 0.15,
    "sources_max": 0.15,
    "best_product_relevance": 0.22,
    "profile_similarity": 0.13,
    "company_fit": 0.10,
}


@dataclass
class ScoreReport:
    scored: int = 0
    product_rows: int = 0
    explanations: int = 0
    top: list[tuple[str, float, str]] = None  # (company, score, best_product_label)


def _minmax(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi <= lo:
        return {k: 0.0 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def _confidence(sources_max: float, has_description: float, events_total: float) -> float:
    return round(
        0.5 * min(sources_max / 3.0, 1.0)
        + 0.25 * (1.0 if has_description else 0.0)
        + 0.25 * (1.0 if events_total > 0 else 0.0),
        3,
    )


def _reasons(
    feat: dict, norm: dict, best_label: str, event_types: list[str]
) -> tuple[str, list[str]]:
    bits: list[str] = []
    supporting: list[str] = []
    if norm.get("recency_score", 0) >= 0.5 and feat.get("events_90d", 0) > 0:
        bits.append(f"recent activity ({int(feat.get('events_90d', 0))} events in 90 days)")
        supporting.append("recency_score")
    rel = [t for t in ("acquisition", "expansion", "product_launch", "funding", "partnership")
           if t in event_types]
    if rel:
        bits.append("relevant events: " + ", ".join(t.replace("_", " ") for t in rel[:3]))
        supporting.append("relevant_event_count")
    if feat.get("sources_max", 0) >= 2:
        bits.append(f"corroborated by up to {int(feat['sources_max'])} sources")
        supporting.append("sources_max")
    if norm.get("profile_similarity", 0) >= 0.5:
        bits.append("public profile resembles a data-intensive financial firm")
        supporting.append("profile_similarity")
    lead = "; ".join(bits) if bits else "limited recent public signal"
    reason = f"{lead[0].upper()}{lead[1:]}. Best product fit: {best_label}."
    return reason, supporting


def run_scoring(settings: Settings, score_date: datetime | None = None) -> ScoreReport:
    score_date = score_date or utcnow()
    report = ScoreReport()

    with Store(settings.resolved_db_path) as store:
        companies = store.df(
            "SELECT company_id, canonical_name, segment, description FROM companies"
        )
        feats = store.df("SELECT company_id, feature_name, value FROM feature_snapshots")
        ev = store.df(
            "SELECT company_id, event_type, title FROM events"
        )
        # evidence: a few source urls per company from its insights
        isrc = store.df(
            """
            SELECT i.company_id, s.url
            FROM insight_sources s JOIN insights i USING (insight_id)
            WHERE s.url IS NOT NULL
            """
        )

        # pivot features to {company_id: {feature: value}}
        fmap: dict[str, dict[str, float]] = {}
        for r in feats.itertuples():
            fmap.setdefault(r.company_id, {})[r.feature_name] = float(r.value)

        # event types + titles per company
        etypes: dict[str, list[str]] = {}
        etext: dict[str, list[str]] = {}
        for r in ev.itertuples():
            etypes.setdefault(r.company_id, []).append(r.event_type)
            etext.setdefault(r.company_id, []).append(r.title or "")
        evidence: dict[str, list[str]] = {}
        for r in isrc.itertuples():
            evidence.setdefault(r.company_id, []).append(r.url)

        # ---- product relevance + raw component vectors -------------------------------------
        best_rel: dict[str, float] = {}
        best_fam_label: dict[str, str] = {}
        product_rows: list[ProductRelevance] = []
        raw_components: dict[str, dict[str, float]] = {}

        for c in companies.itertuples():
            cid = c.company_id
            text = f"{c.description or ''} " + " ".join(etext.get(cid, []))
            raw = product_relevance_raw(c.segment, etypes.get(cid, []), text)
            disp = to_display(raw)
            fam, fam_raw = best_product(raw)
            best_rel[cid] = fam_raw
            best_fam_label[cid] = PRODUCT_LABEL[fam]
            f = fmap.get(cid, {})
            size_norm = min(f.get("size_rank", 0) / 5.0, 1.0)
            company_fit = 0.6 * size_norm + 0.4 * (1.0 if f.get("is_listed", 0) else 0.0)
            raw_components[cid] = {
                "recency_score": f.get("recency_score", 0.0),
                "relevant_event_count": f.get("relevant_event_count", 0.0),
                "sources_max": f.get("sources_max", 0.0),
                "best_product_relevance": fam_raw,
                "profile_similarity": f.get("profile_similarity", 0.0),
                "company_fit": company_fit,
            }
            for pf, val in disp.items():
                product_rows.append(
                    ProductRelevance(
                        company_id=cid, model_version=MODEL_VERSION, product_family=pf,
                        relevance_score=val,
                        evidence=(f"segment={c.segment or 'n/a'}"),
                    )
                )

        # ---- normalize each component across companies, then blend --------------------------
        norm_by_comp: dict[str, dict[str, float]] = {}
        for comp in WEIGHTS:
            col = {cid: raw_components[cid][comp] for cid in raw_components}
            n = _minmax(col)
            for cid, v in n.items():
                norm_by_comp.setdefault(cid, {})[comp] = v

        scores: list[Score] = []
        explanations: list[Explanation] = []
        raw_score: dict[str, float] = {}
        for cid in raw_components:
            n = norm_by_comp[cid]
            raw_score[cid] = 100.0 * sum(WEIGHTS[k] * n.get(k, 0.0) for k in WEIGHTS)

        ranked = sorted(raw_score.items(), key=lambda kv: kv[1], reverse=True)
        for rank, (cid, sc) in enumerate(ranked, start=1):
            f = fmap.get(cid, {})
            conf = _confidence(f.get("sources_max", 0), f.get("has_description", 0),
                               f.get("events_total", 0))
            scores.append(
                Score(company_id=cid, model_version=MODEL_VERSION, score=round(sc, 2),
                      confidence=conf, score_date=score_date, rank=rank)
            )
            reason, supporting = _reasons(f, norm_by_comp[cid], best_fam_label[cid],
                                          etypes.get(cid, []))
            explanations.append(
                Explanation(company_id=cid, model_version=MODEL_VERSION, reason=reason,
                            supporting_features=supporting, source_ids=evidence.get(cid, [])[:5])
            )

        store.con.execute("DELETE FROM scores WHERE model_version = ?", [MODEL_VERSION])
        store.con.execute("DELETE FROM product_relevance WHERE model_version = ?", [MODEL_VERSION])
        store.con.execute("DELETE FROM explanations WHERE model_version = ?", [MODEL_VERSION])
        report.scored = store.upsert("scores", scores)
        report.product_rows = store.upsert("product_relevance", product_rows)
        report.explanations = store.upsert("explanations", explanations)
        report.top = [
            (companies.set_index("company_id").loc[cid, "canonical_name"], round(sc, 1),
             best_fam_label[cid])
            for cid, sc in ranked[:5]
        ]
    return report

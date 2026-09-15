"""Insight building - deduplicate events across connectors into distinct insights.

The problem this solves: the same real-world happening ("Partners Group acquires X") is reported
by several connectors (Google News, GDELT, Yahoo Finance, SEC EDGAR). Stored as raw events that
is three or four near-duplicate rows. A user does not want four notifications for one event; they
want ONE insight that names every source that reported it.

Approach (near-duplicate detection / deduplication):
1. Within each company, greedily cluster events whose titles are similar (fuzzy token-set match)
   and close in time. Each cluster = one underlying happening.
2. Emit one Insight per cluster: a canonical title, the earliest date, the distinct connectors,
   and one InsightSource row per reporting article (its provenance).
3. Flag insights not seen on a previous run as ``is_new`` - the basis of the Daily Insights view.

This is deliberately a transparent, deterministic first pass. A future upgrade swaps the fuzzy
title match for *semantic* matching using sentence-embeddings, to catch same-meaning-different-
words duplicates ("buys" vs "completes acquisition of"). See docs/ROADMAP.md (S2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from rapidfuzz import fuzz

from radar.config import Settings
from radar.models import EventType, Insight, InsightSource, stable_id, utcnow
from radar.normalize import normalize_name
from radar.storage import open_store


@dataclass
class InsightReport:
    insights_total: int = 0
    insights_new: int = 0
    sources_linked: int = 0
    events_in: int = 0


def _title_similarity(a: str, b: str) -> float:
    return float(fuzz.token_set_ratio(normalize_name(a), normalize_name(b)))


def _within_window(d1, d2, days: int) -> bool:
    if d1 is None or d2 is None:
        return True  # missing dates should not block a clear title match
    return abs((d1 - d2).days) <= days


def _cluster_company_events(
    events: list[dict], sim_threshold: float, window_days: int
) -> list[list[dict]]:
    """Greedy clustering: an event joins the first cluster it is similar and close enough to."""
    ordered = sorted(events, key=lambda e: (e["event_date"] is None, e["event_date"] or ""))
    clusters: list[list[dict]] = []
    for ev in ordered:
        placed = False
        for cluster in clusters:
            best = max(_title_similarity(ev["title"], m["title"]) for m in cluster)
            close = any(
                _within_window(ev["event_date"], m["event_date"], window_days) for m in cluster
            )
            if best >= sim_threshold and close:
                cluster.append(ev)
                placed = True
                break
        if not placed:
            clusters.append([ev])
    return clusters


def _mode_event_type(cluster: list[dict]) -> EventType:
    counts: dict[str, int] = {}
    for e in cluster:
        counts[e["event_type"]] = counts.get(e["event_type"], 0) + 1
    # prefer a real classification over the catch-all buckets when there is a tie
    best = sorted(counts.items(), key=lambda kv: (kv[1], kv[0] not in ("other", "unclassified")))
    return EventType(best[-1][0])


def _canonical_title(cluster: list[dict]) -> str:
    return max((e["title"] for e in cluster), key=len)


def _earliest_date(cluster: list[dict]):
    dates = [e["event_date"] for e in cluster if e["event_date"] is not None]
    return min(dates) if dates else None


def _signature_event(cluster: list[dict]) -> dict:
    dated = [e for e in cluster if e["event_date"] is not None]
    return min(dated, key=lambda e: e["event_date"]) if dated else cluster[0]


def build_insights(settings: Settings, run_started: datetime | None = None) -> InsightReport:
    run_started = run_started or utcnow()
    report = InsightReport()
    sim = settings.dedup_title_similarity
    window = settings.dedup_window_days

    with open_store(settings) as store:
        events_df = store.df(
            """
            SELECT e.event_id, e.company_id, e.event_type, e.event_date, e.title,
                   e.url, e.publisher, s.connector
            FROM events e JOIN sources s USING (source_id)
            """
        )
        report.events_in = len(events_df)

        # preserve first_seen_at across runs so "new" means "new since last run"
        prior = store.df("SELECT insight_id, first_seen_at FROM insights")
        first_seen = dict(zip(prior["insight_id"], prior["first_seen_at"], strict=False))

        insights: list[Insight] = []
        sources: list[InsightSource] = []

        for company_id, cdf in events_df.groupby("company_id"):
            events = cdf.to_dict("records")
            for cluster in _cluster_company_events(events, sim, window):
                sig = _signature_event(cluster)
                # Signature = the earliest event's full normalized title. Using the full title
                # (not a prefix) avoids id collisions between items sharing a long common prefix,
                # e.g. "...filed a Current report (8-K)" vs "...Annual report (10-K)".
                signature = normalize_name(sig["title"])
                insight_id = stable_id("insight", str(company_id), signature)
                connectors = sorted({e["connector"] for e in cluster})

                # one source row per distinct url (drop exact duplicate articles)
                seen_urls: set[str] = set()
                cluster_sources: list[InsightSource] = []
                for e in cluster:
                    key = e["url"] or e["event_id"]
                    if key in seen_urls:
                        continue
                    seen_urls.add(key)
                    cluster_sources.append(
                        InsightSource(
                            insight_id=insight_id,
                            connector=e["connector"],
                            publisher=e["publisher"],
                            url=e["url"],
                            event_id=e["event_id"],
                            event_date=e["event_date"],
                        )
                    )

                is_new = insight_id not in first_seen
                insights.append(
                    Insight(
                        insight_id=insight_id,
                        company_id=str(company_id),
                        insight_type=_mode_event_type(cluster),
                        canonical_title=_canonical_title(cluster),
                        event_date=_earliest_date(cluster),
                        source_count=len(connectors),
                        connectors=connectors,
                        first_seen_at=(run_started if is_new else first_seen[insight_id]),
                        last_seen_at=run_started,
                        is_new=is_new,
                    )
                )
                sources.extend(cluster_sources)
                if is_new:
                    report.insights_new += 1

        # full recompute: clear and rewrite so no stale rows survive
        store.execute("DELETE FROM insight_sources")
        store.execute("DELETE FROM insights")
        report.insights_total = store.upsert("insights", insights)
        report.sources_linked = store.upsert("insight_sources", sources)
    return report

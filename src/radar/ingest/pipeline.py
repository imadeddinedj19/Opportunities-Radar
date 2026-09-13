"""Ingest orchestrator - the S1 end-to-end pipeline (Tech Design §4, steps 1-6).

    seed -> enrich -> collect events -> normalize/link -> store (with provenance)

It is deliberately linear and idempotent: running it twice produces the same rows. Live and
offline runs go through exactly the same code path; only the Fetcher differs.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, timedelta

from radar.config import Settings
from radar.features import build_features
from radar.ingest import gdelt, news, sec_edgar, wikidata, wikipedia, yahoo_finance
from radar.ingest.client import Fetcher
from radar.insights import build_insights
from radar.models import (
    Company,
    Event,
    EventType,
    SizeBand,
    Source,
    stable_id,
    utcnow,
)
from radar.normalize import canonicalize, guess_event_type, normalize_name
from radar.storage import Store

# Registry of insight-producing connectors. Each module exposes ``collect(fetcher, name)`` and a
# ``*_URL`` constant. Adding a source is one entry here plus a connector module (NFR-05).
CONNECTORS = {
    "google_news_rss": (news, "RSS_URL"),
    "gdelt": (gdelt, "DOC_URL"),
    "yahoo_finance": (yahoo_finance, "SEARCH_URL"),
    "sec_edgar": (sec_edgar, "SEARCH_URL"),
}


@dataclass
class IngestReport:
    companies: int = 0
    enriched: int = 0
    events: int = 0
    sources: int = 0
    dropped_stale: int = 0
    dropped_unmatched: int = 0
    per_connector: dict[str, int] = field(default_factory=dict)
    insights_total: int = 0
    insights_new: int = 0
    features_written: int = 0


def load_seed(settings: Settings) -> list[dict]:
    with settings.seed_path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build_company(row: dict) -> Company:
    seed_name = row["seed_name"].strip()
    normalized = normalize_name(seed_name)
    return Company(
        company_id=stable_id("company", normalized),
        canonical_name=canonicalize(seed_name),
        normalized_name=normalized,
        aliases=[seed_name],
        domain=(row.get("homepage") or None),
        country=(row.get("country") or None),
        segment=(row.get("segment") or None),
        description=(row.get("notes") or None),
        seed_source="manual_seed",
    )


def _apply_enrichment(company: Company, enrich: dict, wiki: dict) -> None:
    if enrich.get("employees") is not None:
        company.employees = enrich["employees"]
        company.size_band = SizeBand(enrich.get("size_band", SizeBand.UNKNOWN.value))
    if enrich.get("listed") is not None:
        company.listed = enrich["listed"]
    if enrich.get("domain") and not company.domain:
        company.domain = enrich["domain"]
    if enrich.get("wikidata_id"):
        company.wikidata_id = enrich["wikidata_id"]
    label = enrich.get("wikidata_label")
    if label and label not in company.aliases:
        company.aliases.append(label)
    if wiki.get("description"):
        # Prefer the richer public description over the short seed note.
        company.description = wiki["description"]
    got = sum(
        1
        for v in (enrich.get("employees"), enrich.get("wikidata_id"), wiki.get("description"))
        if v
    )
    company.enrichment_confidence = round(got / 3, 3)
    company.updated_at = utcnow()


def _make_event(company: Company, cand: dict, connector: str, source: Source) -> Event:
    title = cand["title"]
    etype: EventType = EventType.UNCLASSIFIED
    conf: float | None = None
    et, ec = guess_event_type(title, cand.get("text"))
    etype, conf = et, ec  # provisional (S1); replaced by S2 classifier
    return Event(
        event_id=stable_id("event", company.company_id, connector, cand.get("url") or title),
        company_id=company.company_id,
        event_type=etype,
        classification_confidence=conf,
        event_date=cand.get("event_date"),
        title=title,
        text=cand.get("text"),
        url=cand.get("url"),
        publisher=cand.get("publisher"),
        language=cand.get("language"),
        source_id=source.source_id,
        match_method="query+verify",
        match_confidence=cand.get("match_confidence", 1.0),
        mention_verified=cand.get("mention_verified", False),
    )


def _mentions_company(company: Company, cand: dict) -> tuple[bool, float]:
    """Confirm a candidate event actually names the company (guards against wrong-company hits)."""
    from radar.normalize import similarity

    hay = f"{cand.get('title','')} {cand.get('text') or ''}"
    best = 0.0
    for alias in {company.canonical_name, *company.aliases}:
        best = max(best, similarity(alias, hay))
        if normalize_name(alias) and normalize_name(alias) in normalize_name(hay):
            return True, 1.0
    return (best >= 60.0), round(best / 100, 3)


def run(settings: Settings, limit: int | None = None) -> IngestReport:
    seed = load_seed(settings)
    if limit is not None:
        seed = seed[:limit]
    fetcher = Fetcher(settings)
    report = IngestReport()
    cutoff = date.today() - timedelta(days=settings.event_lookback_days)

    companies: list[Company] = []
    sources: dict[str, Source] = {}
    events: list[Event] = []

    try:
        for row in seed:
            company = build_company(row)

            enrich = wikidata.enrich(fetcher, company.canonical_name)
            wiki = wikipedia.describe(fetcher, company.canonical_name)
            if enrich or wiki:
                _apply_enrichment(company, enrich, wiki)
                report.enriched += 1
            companies.append(company)

            for connector in settings.connectors:
                module, _url_attr = CONNECTORS[connector]
                candidates = module.collect(fetcher, company.canonical_name)
                report.per_connector[connector] = report.per_connector.get(connector, 0) + len(
                    candidates
                )
                if candidates:
                    src = Source.build(
                        connector=connector,
                        url=_connector_url(connector),
                        retrieved_at=utcnow(),
                        query=candidates[0].get("query"),
                        from_fixture=settings.offline,
                    )
                    sources[src.source_id] = src
                    for cand in candidates:
                        if not cand.get("title"):
                            continue
                        # recency filter (NFR: signals must be recent enough to matter)
                        ed = cand.get("event_date")
                        if ed is not None and ed < cutoff:
                            report.dropped_stale += 1
                            continue
                        matched, mconf = _mentions_company(company, cand)
                        cand["mention_verified"] = matched
                        cand["match_confidence"] = mconf
                        if not matched:
                            report.dropped_unmatched += 1
                            continue
                        events.append(_make_event(company, cand, connector, src))
    finally:
        fetcher.close()

    # de-duplicate events by id (same article can appear twice)
    unique_events = {e.event_id: e for e in events}

    run_started = utcnow()
    with Store(settings.resolved_db_path) as store:
        report.companies = store.upsert("companies", companies)
        report.sources = store.upsert("sources", sources.values())
        report.events = store.upsert("events", unique_events.values())

    # Deduplicate events across connectors into distinct insights, and flag new ones.
    insight_report = build_insights(settings, run_started=run_started)
    report.insights_total = insight_report.insights_total
    report.insights_new = insight_report.insights_new

    # S2: engineer model-ready features from companies + events + insights.
    feature_report = build_features(settings)
    report.features_written = feature_report.features_written
    return report


def _connector_url(connector: str) -> str:
    module, attr = CONNECTORS.get(connector, (None, None))
    return getattr(module, attr) if module else connector

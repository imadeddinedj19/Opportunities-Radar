"""Google News RSS connector - public business events (FR-03).

Google News exposes a search as an RSS feed (a standard XML format for lists of articles).
Each item becomes a *candidate event*: a headline, a link, a publisher and a publication date.
Candidate events are later linked to the right company by entity resolution and, in S2,
classified into event types (acquisition, expansion, ...).
"""

from __future__ import annotations

from datetime import date

import feedparser

from radar.ingest.client import Fetcher

RSS_URL = "https://news.google.com/rss/search"


def _query(company_name: str) -> str:
    # Bias the feed toward commercially meaningful signals rather than routine coverage.
    terms = "acquisition OR expansion OR launch OR funding OR partnership OR regulatory OR hiring"
    return f'"{company_name}" ({terms})'


def collect(
    fetcher: Fetcher, company_name: str, hl: str = "en-US", max_items: int = 50
) -> list[dict]:
    """Return a list of candidate-event dicts for one company."""
    query = _query(company_name)
    resp = fetcher.fetch(
        connector="google_news_rss",
        key=f"news-{company_name}",
        url=RSS_URL,
        params={"q": query, "hl": hl, "gl": "US", "ceid": "US:en"},
    )
    if not resp.body:
        return []
    feed = feedparser.parse(resp.body)
    out: list[dict] = []
    for entry in feed.entries[:max_items]:
        published: date | None = None
        if getattr(entry, "published_parsed", None):
            t = entry.published_parsed
            published = date(t.tm_year, t.tm_mon, t.tm_mday)
        publisher = None
        src = getattr(entry, "source", None)
        if src is not None:
            publisher = getattr(src, "title", None)
        out.append(
            {
                "title": getattr(entry, "title", "").strip(),
                "url": getattr(entry, "link", None),
                "event_date": published,
                "publisher": publisher,
                "text": getattr(entry, "summary", None),
                "language": "en",
                "query": query,
            }
        )
    return out

"""Yahoo Finance connector - company news as a third insight source (FR-03).

Uses Yahoo Finance's public search endpoint, which returns recent news items for a query as
JSON. It goes through the shared Fetcher so offline replay, rate limiting and provenance work
exactly like the other connectors.

Live-run caveat (I could not verify this from the build sandbox, which has no internet):
Yahoo's endpoints are unofficial and sometimes require a session cookie + "crumb" token to
answer. If a live run returns empty or 401/429, the robust fallback is the ``yfinance`` library
(pip install yfinance), which handles that handshake; the parsing below expects the same
``news`` item shape yfinance exposes, so swapping the transport is localized to this file.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from radar.ingest.client import Fetcher

SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"


def collect(fetcher: Fetcher, company_name: str, max_items: int = 50) -> list[dict]:
    resp = fetcher.fetch(
        connector="yahoo_finance",
        key=f"yahoo-{company_name}",
        url=SEARCH_URL,
        params={"q": company_name, "newsCount": str(max_items), "quotesCount": "0"},
    )
    if not resp.body:
        return []
    try:
        data = json.loads(resp.body)
    except json.JSONDecodeError:
        return []
    out: list[dict] = []
    for item in data.get("news", [])[:max_items]:
        ts = item.get("providerPublishTime")
        event_date = None
        if ts:
            try:
                event_date = datetime.fromtimestamp(int(ts), tz=UTC).date()
            except (ValueError, OSError, TypeError):
                event_date = None
        out.append(
            {
                "title": (item.get("title") or "").strip(),
                "url": item.get("link"),
                "event_date": event_date,
                "publisher": item.get("publisher"),
                "text": None,
                "language": "en",
                "query": company_name,
            }
        )
    return out

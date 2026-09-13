"""GDELT connector - a second, independent public event source (FR-03, NFR: multiple sources).

GDELT is a free global news index. Its Doc API returns recent articles matching a query as
JSON. Using GDELT alongside Google News reduces single-source bias (BRD risk control:
"use multiple sources and record source provenance").
"""

from __future__ import annotations

import json
from datetime import datetime

from radar.ingest.client import Fetcher

DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def collect(fetcher: Fetcher, company_name: str, max_items: int = 50) -> list[dict]:
    resp = fetcher.fetch(
        connector="gdelt",
        key=f"gdelt-{company_name}",
        url=DOC_URL,
        params={
            "query": f'"{company_name}"',
            "mode": "artlist",
            "maxrecords": str(max_items),
            "format": "json",
            "sort": "datedesc",
        },
    )
    if not resp.body:
        return []
    try:
        data = json.loads(resp.body)
    except json.JSONDecodeError:
        return []
    out: list[dict] = []
    for art in data.get("articles", [])[:max_items]:
        event_date = None
        seendate = art.get("seendate")
        if seendate:
            try:
                event_date = datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").date()
            except ValueError:
                event_date = None
        out.append(
            {
                "title": (art.get("title") or "").strip(),
                "url": art.get("url"),
                "event_date": event_date,
                "publisher": art.get("domain"),
                "text": None,
                "language": art.get("language"),
                "query": f'"{company_name}"',
            }
        )
    return out

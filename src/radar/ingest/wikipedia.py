"""Wikipedia connector - a one-paragraph public description of the company (FR-02).

Uses the Wikipedia REST summary endpoint, which returns a short, plain-language extract.
This gives the company a human-readable business description and, later (S2), text the
NLP layer can mine for what the company actually does.
"""

from __future__ import annotations

import json

from radar.ingest.client import Fetcher

SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary"


def describe(fetcher: Fetcher, title: str) -> dict:
    """Return {'description': ..., 'wikipedia_url': ...} for a page title, or {}."""
    resp = fetcher.fetch(
        connector="wikipedia",
        key=f"summary-{title}",
        url=f"{SUMMARY_URL}/{title.replace(' ', '_')}",
        params={},
    )
    if not resp.body:
        return {}
    try:
        data = json.loads(resp.body)
    except json.JSONDecodeError:
        return {}
    extract = data.get("extract")
    if not extract:
        return {}
    out = {"description": extract}
    url = data.get("content_urls", {}).get("desktop", {}).get("page")
    if url:
        out["wikipedia_url"] = url
    return out

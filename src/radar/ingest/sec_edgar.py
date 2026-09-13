"""SEC EDGAR connector - official US regulatory filings as a fourth insight source (FR-03).

EDGAR is the U.S. Securities and Exchange Commission's public database of company filings. Its
full-text search API returns filings (8-K current-report events, 10-K/10-Q results, etc.) as
JSON. These are high-signal, structured events: an 8-K often *is* the acquisition/leadership
announcement the news is reporting, straight from the primary source.

Covers US-listed companies only. SEC asks callers to send a descriptive User-Agent with contact
info and to stay under 10 requests/second - both are handled by the shared Fetcher settings.

Live-run caveat: verified against the documented EDGAR full-text search shape, but not executed
from the build sandbox (no internet). Confirm the response shape on the first live run.
"""

from __future__ import annotations

import json
from datetime import date

from radar.ingest.client import Fetcher

SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

# Map EDGAR form types to a readable label used in the event title.
FORM_LABELS = {
    "8-K": "Current report (8-K)",
    "10-K": "Annual report (10-K)",
    "10-Q": "Quarterly report (10-Q)",
    "6-K": "Foreign issuer report (6-K)",
    "20-F": "Foreign annual report (20-F)",
    "S-1": "Registration statement (S-1)",
    "425": "Business-combination filing (425)",
    "SC 13D": "Beneficial ownership (SC 13D)",
}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def collect(fetcher: Fetcher, company_name: str, max_items: int = 50) -> list[dict]:
    resp = fetcher.fetch(
        connector="sec_edgar",
        key=f"edgar-{company_name}",
        url=SEARCH_URL,
        params={"q": f'"{company_name}"', "forms": "8-K,10-K,10-Q,425", "hits": str(max_items)},
    )
    if not resp.body:
        return []
    try:
        data = json.loads(resp.body)
        hits = data.get("hits", {}).get("hits", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    out: list[dict] = []
    for hit in hits[:max_items]:
        src = hit.get("_source", {})
        form = (src.get("root_form") or src.get("file_type") or "").strip()
        label = FORM_LABELS.get(form, f"SEC filing ({form})" if form else "SEC filing")
        names = src.get("display_names") or []
        who = names[0] if names else company_name
        adsh = (hit.get("_id") or "").split(":")[0]
        url = (
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum={adsh}"
            if adsh else "https://www.sec.gov/cgi-bin/srqsb"
        )
        out.append(
            {
                "title": f"{who} filed a {label}",
                "url": src.get("url") or url,
                "event_date": _parse_date(src.get("file_date")),
                "publisher": "SEC EDGAR",
                "text": None,
                "language": "en",
                "query": company_name,
            }
        )
    return out

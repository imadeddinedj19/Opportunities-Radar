"""Wikidata connector - structured company enrichment (FR-02).

Wikidata is a free, public, structured knowledge base (the data backbone behind Wikipedia).
We use it to attach permitted public attributes to a company: country, industry, employee
count, listed/private status, official website and inception year. Two calls per company:
a search to find the entity id (a "Q-number", e.g. Q650258), then a fetch of that entity.
"""

from __future__ import annotations

import json

from radar.ingest.client import Fetcher
from radar.models import SizeBand

SEARCH_URL = "https://www.wikidata.org/w/api.php"
ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData"

# Property ids we read off a Wikidata entity.
P_INSTANCE_OF = "P31"
P_COUNTRY = "P17"
P_INDUSTRY = "P452"
P_EMPLOYEES = "P1128"
P_WEBSITE = "P856"
P_INCEPTION = "P571"
P_STOCK_EXCHANGE = "P414"
P_ISO_COUNTRY = "P297"  # not on the company; resolved separately if needed


def search_entity(fetcher: Fetcher, name: str) -> str | None:
    """Return the best-matching Wikidata entity id for a company name, or None."""
    resp = fetcher.fetch(
        connector="wikidata",
        key=f"search-{name}",
        url=SEARCH_URL,
        params={
            "action": "wbsearchentities",
            "search": name,
            "language": "en",
            "format": "json",
            "type": "item",
            "limit": "1",
        },
    )
    if resp.status_code != 200 and not resp.body:
        return None
    try:
        data = json.loads(resp.body)
    except json.JSONDecodeError:
        return None
    hits = data.get("search", [])
    return hits[0]["id"] if hits else None


def _claim_value_id(claims: dict, prop: str) -> str | None:
    try:
        snak = claims[prop][0]["mainsnak"]
        return snak["datavalue"]["value"]["id"]
    except (KeyError, IndexError, TypeError):
        return None


def _claim_value_amount(claims: dict, prop: str) -> float | None:
    try:
        snak = claims[prop][0]["mainsnak"]
        return float(snak["datavalue"]["value"]["amount"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _claim_value_string(claims: dict, prop: str) -> str | None:
    try:
        snak = claims[prop][0]["mainsnak"]
        return snak["datavalue"]["value"]
    except (KeyError, IndexError, TypeError):
        return None


def fetch_entity(fetcher: Fetcher, entity_id: str) -> dict:
    """Return a small enrichment dict for a Wikidata entity id."""
    resp = fetcher.fetch(
        connector="wikidata",
        key=f"entity-{entity_id}",
        url=f"{ENTITY_URL}/{entity_id}.json",
        params={},
    )
    out: dict = {"wikidata_id": entity_id}
    if not resp.body:
        return out
    try:
        data = json.loads(resp.body)
        entity = data["entities"][entity_id]
        claims = entity.get("claims", {})
    except (KeyError, json.JSONDecodeError, TypeError):
        return out

    employees = _claim_value_amount(claims, P_EMPLOYEES)
    if employees is not None:
        out["employees"] = int(employees)
        out["size_band"] = SizeBand.from_employees(int(employees)).value
    website = _claim_value_string(claims, P_WEBSITE)
    if website:
        host = website.replace("https://", "").replace("http://", "").strip("/")
        out["domain"] = host.split("/")[0]
    out["listed"] = P_STOCK_EXCHANGE in claims
    # country/industry come back as Q-ids; resolving them to labels needs another call, which
    # we skip in S1 to stay within the rate budget. We keep the raw Q-ids as provenance.
    country_qid = _claim_value_id(claims, P_COUNTRY)
    industry_qid = _claim_value_id(claims, P_INDUSTRY)
    if country_qid:
        out["country_qid"] = country_qid
    if industry_qid:
        out["industry_qid"] = industry_qid
    labels = entity.get("labels", {})
    if "en" in labels:
        out["wikidata_label"] = labels["en"]["value"]
    return out


def enrich(fetcher: Fetcher, name: str) -> dict:
    """Full enrichment for one company name. Returns {} if nothing found."""
    entity_id = search_entity(fetcher, name)
    if entity_id is None:
        return {}
    return fetch_entity(fetcher, entity_id)

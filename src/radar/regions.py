"""Sales-region classification.

Maps each company to one of the sales regions the team works by. "Strategic Accounts" is a
cross-cutting tier, not a geography - a company flagged strategic belongs to that bucket whatever
its country, which keeps the five buckets mutually exclusive (a company is in exactly one):

    UK · US · EMEA · Asia · Strategic Accounts

EMEA here means continental Europe, the Middle East and Africa (the UK is broken out separately,
as sales teams usually do). Strategic accounts are the team's most important clients; because we
cannot know that list, it is driven by a ``strategic`` flag in the seed file (default off) that
the team fills in.
"""

from __future__ import annotations

REGION_UK = "UK"
REGION_US = "US"
REGION_EMEA = "EMEA"
REGION_ASIA = "Asia"
REGION_STRATEGIC = "Strategic Accounts"

REGIONS = (REGION_UK, REGION_US, REGION_EMEA, REGION_ASIA, REGION_STRATEGIC)

# ISO 3166-1 alpha-2 country -> geographic region.
_ASIA = {"SG", "JP", "HK", "CN", "IN", "KR", "TW", "MY", "TH", "ID", "PH", "VN", "AU", "NZ"}
_UK = {"GB", "UK"}
_US = {"US"}
# everything else that appears in a financial-sector seed is treated as EMEA
# (continental Europe, Middle East, Africa): CH DE FR IT NL DK FI NO SE ES PT IE BE AE ZA ...


def geo_region(country: str | None) -> str:
    """Geographic region from an ISO country code (ignores the strategic tier)."""
    if not country:
        return REGION_EMEA
    c = country.upper()
    if c in _UK:
        return REGION_UK
    if c in _US:
        return REGION_US
    if c in _ASIA:
        return REGION_ASIA
    return REGION_EMEA


def resolve_region(country: str | None, strategic: bool) -> str:
    """The sales bucket a company falls in: Strategic Accounts overrides geography."""
    return REGION_STRATEGIC if strategic else geo_region(country)

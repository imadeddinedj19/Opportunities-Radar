"""SIX product-compatibility layer - S3 (FR-09).

For each company we estimate how well it matches each SIX Financial Information **product family**,
then name the best-fitting product to propose. This is the "compatibility with existing SIX
products" the score is built on.

Three transparent signals combine into a per-family relevance (kept explainable on purpose - a
sales manager must be able to see *why* a product was suggested, NFR-04/08):

1. **Segment affinity** - what a company of this kind typically needs (an asset manager leans to
   Funds Data; an exchange to Market Data; a custodian to Corporate Actions).
2. **Event affinity** - what the detected events imply (a new fund launch -> Funds Data; an
   acquisition -> Reference Data + Corporate Actions; a regulatory action -> Regulatory/Tax).
3. **Keyword affinity** - words in the company's public text and event titles that name a product
   area ("ETF" -> Funds Data, "ESG" -> ESG, "index/pricing" -> Market Data).

The three are weighted and normalized *within a company* so the output reads like the Technical
Design's example (Funds Data 91%, Reference Data 84%, ...): a ranking of products for that company.
"""

from __future__ import annotations

from radar.models import ProductFamily as PF

# Weights for combining the three affinity signals.
W_SEGMENT, W_EVENT, W_KEYWORD = 0.5, 0.3, 0.2

# 1. Segment -> product affinity (0-1). Only non-zero entries listed.
SEGMENT_AFFINITY: dict[str, dict[PF, float]] = {
    "asset_manager": {PF.FUNDS_DATA: 1.0, PF.REFERENCE_DATA: 0.7, PF.MARKET_DATA: 0.6, PF.ESG: 0.5},
    "private_markets": {PF.FUNDS_DATA: 0.9, PF.REFERENCE_DATA: 0.7, PF.CORPORATE_ACTIONS: 0.5,
                        PF.ESG: 0.5},
    "wealth_management": {PF.FUNDS_DATA: 0.8, PF.MARKET_DATA: 0.7, PF.REFERENCE_DATA: 0.6,
                          PF.ESG: 0.4},
    "online_broker": {PF.MARKET_DATA: 0.9, PF.REFERENCE_DATA: 0.7, PF.CORPORATE_ACTIONS: 0.5},
    "exchange": {PF.MARKET_DATA: 1.0, PF.REFERENCE_DATA: 0.8, PF.CORPORATE_ACTIONS: 0.6},
    "market_infrastructure": {PF.REFERENCE_DATA: 1.0, PF.MARKET_DATA: 0.8,
                              PF.CORPORATE_ACTIONS: 0.7},
    "electronic_trading": {PF.MARKET_DATA: 1.0, PF.REFERENCE_DATA: 0.7},
    "market_maker": {PF.MARKET_DATA: 1.0, PF.REFERENCE_DATA: 0.6},
    "custodian": {PF.CORPORATE_ACTIONS: 1.0, PF.REFERENCE_DATA: 0.8, PF.FUNDS_DATA: 0.6},
    "universal_bank": {PF.REFERENCE_DATA: 0.8, PF.MARKET_DATA: 0.7, PF.CORPORATE_ACTIONS: 0.6,
                       PF.REGULATORY_TAX: 0.6},
    "investment_bank": {PF.MARKET_DATA: 0.9, PF.REFERENCE_DATA: 0.8, PF.CORPORATE_ACTIONS: 0.7},
    "corporate_bank": {PF.REFERENCE_DATA: 0.8, PF.REGULATORY_TAX: 0.6, PF.CORPORATE_ACTIONS: 0.6},
    "retail_bank": {PF.REFERENCE_DATA: 0.7, PF.REGULATORY_TAX: 0.6, PF.MARKET_DATA: 0.5},
    "insurer": {PF.REGULATORY_TAX: 0.9, PF.ESG: 0.7, PF.REFERENCE_DATA: 0.6, PF.MARKET_DATA: 0.5},
    "reinsurer": {PF.REGULATORY_TAX: 0.9, PF.ESG: 0.7, PF.MARKET_DATA: 0.6},
    "ratings_data": {PF.REFERENCE_DATA: 0.9, PF.ESG: 0.7, PF.CORPORATE_ACTIONS: 0.6},
    "index_data": {PF.MARKET_DATA: 1.0, PF.REFERENCE_DATA: 0.8, PF.ESG: 0.6},
    "financial_data": {PF.REFERENCE_DATA: 0.9, PF.MARKET_DATA: 0.8, PF.ESG: 0.6},
    "payments": {PF.REFERENCE_DATA: 0.6, PF.REGULATORY_TAX: 0.5},
    "fintech_software": {PF.REFERENCE_DATA: 0.7, PF.MARKET_DATA: 0.6},
    "neobank": {PF.REFERENCE_DATA: 0.6, PF.MARKET_DATA: 0.5, PF.REGULATORY_TAX: 0.5},
    "consumer_finance": {PF.REGULATORY_TAX: 0.7, PF.REFERENCE_DATA: 0.5},
    "specialist_lender": {PF.REGULATORY_TAX: 0.7, PF.REFERENCE_DATA: 0.6},
    "structured_products": {PF.MARKET_DATA: 0.9, PF.CORPORATE_ACTIONS: 0.7, PF.REFERENCE_DATA: 0.7},
    "diversified_financial": {PF.REFERENCE_DATA: 0.7, PF.MARKET_DATA: 0.6, PF.REGULATORY_TAX: 0.5},
    "investment_company": {PF.REFERENCE_DATA: 0.7, PF.FUNDS_DATA: 0.6, PF.CORPORATE_ACTIONS: 0.6},
    "insurtech": {PF.REGULATORY_TAX: 0.7, PF.ESG: 0.5},
    "crypto_exchange": {PF.MARKET_DATA: 0.9, PF.REFERENCE_DATA: 0.7, PF.REGULATORY_TAX: 0.6},
    "advisory": {PF.REFERENCE_DATA: 0.6, PF.CORPORATE_ACTIONS: 0.6, PF.MARKET_DATA: 0.5},
    "platform": {PF.FUNDS_DATA: 0.7, PF.MARKET_DATA: 0.6, PF.REFERENCE_DATA: 0.6},
}

# 2. Event type -> product affinity (0-1).
EVENT_AFFINITY: dict[str, dict[PF, float]] = {
    "acquisition": {PF.REFERENCE_DATA: 0.8, PF.CORPORATE_ACTIONS: 0.9},
    "product_launch": {PF.FUNDS_DATA: 0.9, PF.MARKET_DATA: 0.5},
    "expansion": {PF.MARKET_DATA: 0.7, PF.REFERENCE_DATA: 0.6},
    "funding": {PF.CORPORATE_ACTIONS: 0.8, PF.REFERENCE_DATA: 0.5},
    "partnership": {PF.REFERENCE_DATA: 0.6, PF.MARKET_DATA: 0.5},
    "regulatory": {PF.REGULATORY_TAX: 1.0},
    "financial_results": {PF.CORPORATE_ACTIONS: 0.7, PF.REFERENCE_DATA: 0.5},
    "technology": {PF.MARKET_DATA: 0.6, PF.REFERENCE_DATA: 0.6},
    "leadership_change": {PF.REFERENCE_DATA: 0.3},
}

# 3. Keyword -> product affinity. Substrings matched against company text + event titles.
KEYWORD_AFFINITY: list[tuple[tuple[str, ...], PF, float]] = [
    (("fund", "etf", "ucits", "mutual"), PF.FUNDS_DATA, 1.0),
    (("esg", "sustainab", "climate", "green bond", "carbon"), PF.ESG, 1.0),
    (("regulat", "compliance", "mifid", "basel", "tax", "reporting", "licen"),
     PF.REGULATORY_TAX, 1.0),
    (("index", "pricing", "market data", "trading", "exchange", "quote"), PF.MARKET_DATA, 1.0),
    (("corporate action", "dividend", "merger", "acquisition", "custody", "settlement"),
     PF.CORPORATE_ACTIONS, 1.0),
    (("reference data", "securities", "instrument", "identifier", "isin", "entity"),
     PF.REFERENCE_DATA, 1.0),
]

FAMILIES = list(PF)


def _keyword_scores(text: str) -> dict[PF, float]:
    hay = text.lower()
    out: dict[PF, float] = {}
    for keys, fam, w in KEYWORD_AFFINITY:
        if any(k in hay for k in keys):
            out[fam] = max(out.get(fam, 0.0), w)
    return out


def product_relevance_raw(
    segment: str | None,
    event_types: list[str],
    text: str,
) -> dict[PF, float]:
    """Absolute 0-1 relevance per family (weights sum to 1, affinities 0-1, so raw <= 1).

    Absolute means comparable *across companies* - unlike the within-company display percentages,
    a low-fit company scores low on every family here. The headline score uses the best of these.
    """
    seg = SEGMENT_AFFINITY.get(segment or "", {})
    ev: dict[PF, float] = {}
    for et in event_types:
        for fam, w in EVENT_AFFINITY.get(et, {}).items():
            ev[fam] = max(ev.get(fam, 0.0), w)
    kw = _keyword_scores(text)
    return {
        fam: round(
            W_SEGMENT * seg.get(fam, 0.0)
            + W_EVENT * ev.get(fam, 0.0)
            + W_KEYWORD * kw.get(fam, 0.0),
            4,
        )
        for fam in FAMILIES
    }


def to_display(raw: dict[PF, float]) -> dict[PF, float]:
    """Normalize raw relevance within a company so the best-fit family reads as ~100%."""
    top = max(raw.values()) if raw else 0.0
    if top <= 0:
        return {fam: 0.0 for fam in FAMILIES}
    return {fam: round(v / top, 4) for fam, v in raw.items()}


def best_product(relevance: dict[PF, float]) -> tuple[PF, float]:
    fam = max(relevance, key=lambda f: relevance[f])
    return fam, relevance[fam]


PRODUCT_LABEL = {
    PF.REFERENCE_DATA: "Reference Data",
    PF.MARKET_DATA: "Market Data",
    PF.FUNDS_DATA: "Funds Data",
    PF.CORPORATE_ACTIONS: "Corporate Actions",
    PF.REGULATORY_TAX: "Regulatory / Tax Data",
    PF.ESG: "ESG Data",
}

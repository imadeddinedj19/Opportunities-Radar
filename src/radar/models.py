"""The POC data model (Technical Design §5, Requirements §5).

Each class is a *record type*: a validated description of one row we store. Validation at
this boundary is what keeps low-quality public data from silently corrupting the pipeline.

Entities implemented in S1: Company, Source, Event.
Entities reserved for later segments but defined now so the schema is stable:
FeatureSnapshot (S2), Score / ProductRelevance / Explanation (S2-S3), OutcomeLabel (FR-14).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl, field_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


def stable_id(*parts: str, length: int = 16) -> str:
    """Deterministic id from content, so re-running the pipeline never duplicates rows."""
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:length]


class SizeBand(StrEnum):
    MICRO = "micro"  # < 50 employees
    SMALL = "small"  # 50 - 249
    MEDIUM = "medium"  # 250 - 999
    LARGE = "large"  # 1000 - 9999
    ENTERPRISE = "enterprise"  # 10000+
    UNKNOWN = "unknown"

    @classmethod
    def from_employees(cls, n: int | None) -> SizeBand:
        if n is None:
            return cls.UNKNOWN
        if n < 50:
            return cls.MICRO
        if n < 250:
            return cls.SMALL
        if n < 1000:
            return cls.MEDIUM
        if n < 10000:
            return cls.LARGE
        return cls.ENTERPRISE


class EventType(StrEnum):
    """Controlled vocabulary of business events (FR-03).

    S1 stores everything as UNCLASSIFIED; S2 adds the classifier that assigns the other values.
    """

    ACQUISITION = "acquisition"
    EXPANSION = "expansion"
    PRODUCT_LAUNCH = "product_launch"
    FUNDING = "funding"
    HIRING = "hiring"
    LEADERSHIP_CHANGE = "leadership_change"
    PARTNERSHIP = "partnership"
    REGULATORY = "regulatory"
    TECHNOLOGY = "technology"
    FINANCIAL_RESULTS = "financial_results"
    OTHER = "other"
    UNCLASSIFIED = "unclassified"


class ProductFamily(StrEnum):
    """Small controlled taxonomy of SIX Financial Information product families (Tech Design §8)."""

    REFERENCE_DATA = "reference_data"
    MARKET_DATA = "market_data"
    FUNDS_DATA = "funds_data"
    CORPORATE_ACTIONS = "corporate_actions"
    REGULATORY_TAX = "regulatory_tax"
    ESG = "esg"


class Company(BaseModel):
    company_id: str
    canonical_name: str
    normalized_name: str
    aliases: list[str] = Field(default_factory=list)
    domain: str | None = None
    country: str | None = Field(default=None, description="ISO 3166-1 alpha-2, e.g. CH")
    industry: str | None = None
    segment: str | None = Field(
        default=None, description="Target-segment tag from the seed list, e.g. asset_manager"
    )
    size_band: SizeBand = SizeBand.UNKNOWN
    employees: int | None = None
    listed: bool | None = None
    description: str | None = None
    wikidata_id: str | None = None
    enrichment_confidence: float | None = None
    seed_source: str = "manual_seed"
    updated_at: datetime = Field(default_factory=utcnow)

    @field_validator("country")
    @classmethod
    def _upper_country(cls, v: str | None) -> str | None:
        return v.upper() if v else None


class Source(BaseModel):
    """Provenance record: where a piece of information came from and when we fetched it (FR-04)."""

    source_id: str
    connector: str  # e.g. "wikidata", "google_news_rss", "gdelt"
    publisher: str | None = None
    url: str
    query: str | None = None
    retrieved_at: datetime
    from_fixture: bool = False

    @classmethod
    def build(
        cls,
        connector: str,
        url: str,
        retrieved_at: datetime,
        publisher: str | None = None,
        query: str | None = None,
        from_fixture: bool = False,
    ) -> Source:
        return cls(
            source_id=stable_id(connector, url, retrieved_at.isoformat()),
            connector=connector,
            publisher=publisher,
            url=url,
            query=query,
            retrieved_at=retrieved_at,
            from_fixture=from_fixture,
        )


class Event(BaseModel):
    event_id: str
    company_id: str
    event_type: EventType = EventType.UNCLASSIFIED
    event_date: date | None = None
    title: str
    text: str | None = None
    url: str | None = None
    publisher: str | None = None
    language: str | None = None
    source_id: str
    match_method: str = Field(
        default="query", description="How the record was linked to the company (FR-05)"
    )
    match_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    mention_verified: bool = False
    classification_confidence: float | None = None  # filled by S2
    collected_at: datetime = Field(default_factory=utcnow)


# ---- Reserved for later segments -------------------------------------------------------


class FeatureSnapshot(BaseModel):
    company_id: str
    snapshot_date: date
    feature_name: str
    value: float
    feature_version: str = "s2-v0"


class Score(BaseModel):
    company_id: str
    model_version: str
    score: float = Field(ge=0.0, le=100.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    score_date: datetime = Field(default_factory=utcnow)
    rank: int | None = None


class ProductRelevance(BaseModel):
    company_id: str
    model_version: str
    product_family: ProductFamily
    relevance_score: float = Field(ge=0.0, le=1.0)
    evidence: str | None = None


class Explanation(BaseModel):
    company_id: str
    model_version: str
    reason: str
    supporting_features: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class OutcomeLabel(BaseModel):
    """Feedback-ready fields for a future internal pilot (FR-14).

    Never populated in the external POC.
    """

    company_id: str
    opportunity_created: bool | None = None
    opportunity_stage: str | None = None
    won: bool | None = None
    product_family: ProductFamily | None = None
    value: float | None = None
    conversion_date: date | None = None
    label_source: str | None = None


class RawResponse(BaseModel):
    """One HTTP response as retrieved, kept verbatim for reproducibility (NFR-03)."""

    connector: str
    key: str
    url: str
    params: dict[str, str] = Field(default_factory=dict)
    status_code: int
    retrieved_at: datetime
    body: str
    from_fixture: bool = False


__all__ = [
    "Company",
    "Event",
    "EventType",
    "Explanation",
    "FeatureSnapshot",
    "HttpUrl",
    "OutcomeLabel",
    "ProductFamily",
    "ProductRelevance",
    "RawResponse",
    "Score",
    "SizeBand",
    "Source",
    "stable_id",
    "utcnow",
]

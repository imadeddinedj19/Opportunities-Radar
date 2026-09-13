"""Provisional, rule-based event typing (S1 placeholder for the S2 NLP classifier).

S1's job is acquisition and storage, not real event understanding. But leaving every event as
"unclassified" makes the demo opaque, so we assign a *provisional* type from simple keyword
rules and mark it with low ``classification_confidence``. S2 replaces this with a proper
classifier (spaCy / transformer). Keeping it deterministic and separate makes that swap clean.
"""

from __future__ import annotations

from radar.models import EventType

# Ordered: earlier rules win when several keywords appear.
KEYWORDS: list[tuple[EventType, tuple[str, ...]]] = [
    (EventType.ACQUISITION,
     ("acqui", "takeover", "buyout", "to buy", "merger", "merges", "acquire")),
    (EventType.FUNDING,
     ("funding", "raises", "raised", "capital increase", "ipo", "bond issue", "series ")),
    (EventType.PRODUCT_LAUNCH,
     ("launch", "launches", "unveil", "rolls out", "new fund", "new product", "introduces")),
    (EventType.EXPANSION,
     ("expansion", "expands", "opens office", "enters", "new market", "expand into")),
    (EventType.PARTNERSHIP,
     ("partnership", "partners with", "teams up", "alliance", "collaborat", "joint venture")),
    (EventType.REGULATORY,
     ("regulator", "fine", "fined", "compliance", "sanction", "license", "licence", "authorit")),
    (EventType.LEADERSHIP_CHANGE,
     ("appoints", "names ", "steps down", "resigns", "new ceo", "new cfo", "new chair")),
    (EventType.HIRING,
     ("hiring", "hires", "recruit", "jobs", "headcount", "to hire")),
    (EventType.TECHNOLOGY,
     ("technology", "platform", "digital", "cloud", "ai ", "data platform", "modernis")),
    (EventType.FINANCIAL_RESULTS,
     ("results", "earnings", "profit", "revenue", "quarterly", "full-year", "half-year")),
]

PROVISIONAL_CONFIDENCE = 0.35


def guess_event_type(title: str, text: str | None = None) -> tuple[EventType, float]:
    """Return a provisional (event_type, confidence). Confidence stays low by design."""
    hay = f"{title} {text or ''}".lower()
    for event_type, keys in KEYWORDS:
        if any(k in hay for k in keys):
            return event_type, PROVISIONAL_CONFIDENCE
    return EventType.OTHER, 0.1

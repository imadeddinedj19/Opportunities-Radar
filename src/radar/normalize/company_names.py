"""Company-name normalization and lightweight entity resolution (FR-05).

Public records spell the same company many ways: "Partners Group Holding AG",
"Partners Group", "PARTNERS GROUP". *Normalization* reduces a raw name to a comparable
key by lower-casing, stripping punctuation and dropping trailing legal-form suffixes
(AG, SA, Ltd, ...). *Entity resolution* then decides whether a new name refers to a company
we already know, using a fuzzy string-similarity score (token-set ratio) rather than exact
matching.

Design choice: we strip only genuine legal forms (AG, SA, GmbH, Inc, ...), never distinctive
words like "Group" or "Holding". Over-stripping would turn "Partners Group" into "partners"
and risk collapsing different companies onto the same key.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

from rapidfuzz import fuzz, process

# Trailing legal-form suffixes across the jurisdictions in scope. Stripped only when they are
# the last token, and only one level deep per side, so "Group"/"Holding" survive.
LEGAL_SUFFIXES = {
    "ag", "sa", "se", "nv", "bv", "plc", "llc", "llp", "lp", "ltd", "limited",
    "inc", "incorporated", "corp", "corporation", "co", "gmbh", "spa", "srl",
    "oyj", "ab", "as", "asa", "kk", "pte", "sas", "kgaa",
}
LEADING_STOPWORDS = {"the"}

_DOTS = re.compile(r"\.")
_PUNCT = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS = re.compile(r"\s+")


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_name(name: str) -> str:
    """Reduce a company name to a comparable key. Deterministic and idempotent."""
    text = _strip_accents(name).lower()
    text = text.replace("&", " and ")
    text = _DOTS.sub("", text)  # "S.A." -> "SA", "Inc." -> "Inc" before other punctuation
    text = _PUNCT.sub(" ", text)
    text = _WS.sub(" ", text).strip()
    tokens = [t for t in text.split(" ") if t]
    if tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    if tokens and tokens[0] in LEADING_STOPWORDS:
        tokens.pop(0)
    return " ".join(tokens) if tokens else text


def canonicalize(name: str) -> str:
    """A tidy display name: collapse whitespace, keep original casing/punctuation."""
    return _WS.sub(" ", name).strip()


def similarity(a: str, b: str) -> float:
    """0-100 fuzzy similarity between two names after normalization."""
    return float(fuzz.token_set_ratio(normalize_name(a), normalize_name(b)))


def resolve_company(
    name: str,
    known: Mapping[str, str],
    threshold: float = 88.0,
) -> tuple[str | None, float]:
    """Match ``name`` against ``known`` (company_id -> normalized_name).

    Returns ``(company_id, score)`` for the best match at or above ``threshold``,
    otherwise ``(None, best_score)``. This guard stops an article about the wrong company
    from being attached to one of our targets.
    """
    if not known:
        return None, 0.0
    query = normalize_name(name)
    match = process.extractOne(
        query, dict(known), scorer=fuzz.token_set_ratio
    )
    if match is None:
        return None, 0.0
    _matched_name, score, company_id = match
    if score >= threshold:
        return company_id, float(score)
    return None, float(score)

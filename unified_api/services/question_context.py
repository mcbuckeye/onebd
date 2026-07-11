"""Resolve high-confidence question entities before LLM query generation."""

import re
from typing import Callable, List, Optional

import structlog

from unified_api.services.entity_resolution import get_entity_resolution_service

logger = structlog.get_logger(__name__)


_QUESTION_WORDS = {
    "A", "AN", "AND", "ARE", "AS", "AT", "BETWEEN", "BUILD", "BY",
    "COMPARE", "DID", "DO", "DOES", "DONE", "FOR", "FROM", "HAS",
    "HAVE", "HOW", "I", "IN", "IS", "LAST", "ME", "MOST", "MY",
    "OF", "ON", "OR", "OUR", "SHOW", "THE", "THEIR", "THIS", "TO",
    "TOP", "US", "VS", "WAS", "WHAT", "WHEN", "WHICH", "WHO", "WITH",
}

_DOMAIN_WORDS = {
    "ADC", "ADCS", "ASSET", "ASSETS", "BIOTECH", "CART", "CAR-T",
    "COMPANY", "DEAL", "DEALS", "DRUG", "DRUGS", "HEMATOLOGY", "LICENSE",
    "LICENSING", "M&A", "ONCOLOGY", "PHARMA", "PHASE", "THERAPEUTIC",
    "VALUATION",
}


def extract_company_phrases(question: str) -> List[str]:
    """Extract likely capitalized company mentions without treating domain terms as companies."""
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9&.-]*", question)
    phrases: List[str] = []
    current: List[str] = []

    def flush() -> None:
        if current:
            phrase = " ".join(current)
            if phrase not in phrases:
                phrases.append(phrase)
            current.clear()

    for token in tokens:
        upper = token.upper()
        is_candidate = token[0].isupper() or token.isupper()
        if (
            is_candidate
            and upper not in _QUESTION_WORDS
            and upper not in _DOMAIN_WORDS
            and len(token) > 1
        ):
            current.append(token)
            if len(current) == 4:
                flush()
        else:
            flush()
    flush()
    return phrases


def resolve_company_mentions(
    question: str,
    search: Optional[Callable[[str, int], List[dict]]] = None,
) -> List[dict]:
    """Return only unambiguous company resolutions plus explicit ambiguous candidates."""
    service = get_entity_resolution_service()
    search = search or (lambda phrase, limit: service.search_companies(phrase, limit))
    resolutions = []

    for phrase in extract_company_phrases(question):
        try:
            candidates = search(phrase, 5)
        except Exception as exc:
            logger.warning("Company mention resolution failed", phrase=phrase, error=str(exc))
            continue

        normalized_phrase = service.normalize_company_name(phrase)
        plausible = []
        exact = []
        for candidate in candidates:
            normalized_name = service.normalize_company_name(candidate.get("name", ""))
            ticker = (candidate.get("ticker") or "").upper()
            if normalized_name == normalized_phrase or ticker == phrase.upper():
                exact.append(candidate)
            elif len(normalized_phrase) >= 4 and normalized_phrase in normalized_name:
                plausible.append(candidate)

        preferred_exact = [
            candidate for candidate in exact
            if candidate.get("ticker") or candidate.get("has_xref")
        ]
        selected_exact = (
            preferred_exact[0]
            if len(preferred_exact) == 1
            else exact[0] if len(exact) == 1 else None
        )

        if selected_exact:
            candidate = selected_exact
            resolution = {
                "mention": phrase,
                "status": "resolved",
                "company_id": candidate["id"],
                "canonical_name": candidate["name"],
                "ticker": candidate.get("ticker"),
            }
            for key in (
                "matched_alias",
                "parent_company_id",
                "parent_company_name",
                "relationship_type",
            ):
                if candidate.get(key) is not None:
                    resolution[key] = candidate[key]
            resolutions.append(resolution)
        elif exact or plausible:
            choices = (exact or plausible)[:3]
            resolutions.append({
                "mention": phrase,
                "status": "ambiguous",
                "candidates": [
                    {
                        "company_id": candidate["id"],
                        "canonical_name": candidate["name"],
                        "ticker": candidate.get("ticker"),
                    }
                    for candidate in choices
                ],
            })

    return resolutions

"""Resolve high-confidence question entities before LLM query generation."""

import re
from typing import Callable, List, Optional

import structlog

from unified_api.services.entity_resolution import get_entity_resolution_service
from unified_api.services.entity_resolution import normalize_identifier_value

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

        # Preserve explicit distinguishing words such as "& Co" before legal
        # suffix normalization collapses related companies onto the same brand.
        phrase_words = set(re.findall(r"[A-Z0-9]+", phrase.upper()))
        if len(phrase_words) > 1:
            lexical_exact = []
            for candidate in exact:
                candidate_text = " ".join(filter(None, (
                    candidate.get("name"),
                    candidate.get("matched_alias"),
                )))
                candidate_words = set(re.findall(r"[A-Z0-9]+", candidate_text.upper()))
                if phrase_words.issubset(candidate_words):
                    lexical_exact.append(candidate)
            if lexical_exact:
                exact = lexical_exact

        preferred_exact = [
            candidate for candidate in exact
            if candidate.get("ticker") or candidate.get("has_xref")
        ]
        preferred_plausible = [
            candidate for candidate in plausible
            if candidate.get("ticker") or candidate.get("has_xref")
        ]
        selected_exact = (
            preferred_exact[0]
            if len(preferred_exact) == 1
            else exact[0] if len(exact) == 1 else None
        )

        if (
            selected_exact
            and not selected_exact.get("ticker")
            and not selected_exact.get("has_xref")
            and preferred_plausible
        ):
            selected_exact = None

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
            choices = (
                preferred_exact
                or preferred_plausible
                or exact
                or plausible
            )[:3]
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


def _search_drugs_in_question(question: str, limit: int) -> List[dict]:
    """Find source aliases/identifiers occurring verbatim in a question."""
    from sqlalchemy import text

    from unified_api.services.database import get_cortellis_session

    service = get_entity_resolution_service()
    service.ensure_identity_schema()
    candidate_aliases = _question_alias_candidates(question)
    if not candidate_aliases:
        return []
    with get_cortellis_session() as session:
        rows = session.execute(text("""
            WITH identities AS (
                SELECT drug.id AS drug_id, drug.name_display,
                       LOWER(REGEXP_REPLACE(TRIM(drug.name_display),
                             '\\s+', ' ', 'g')) AS normalized_value,
                       drug.name_display AS matched_alias,
                       'cortellis_display_name' AS match_source
                FROM drugs drug
                WHERE LOWER(REGEXP_REPLACE(TRIM(drug.name_display),
                            '\\s+', ' ', 'g')) = ANY(:candidate_aliases)
                UNION ALL
                SELECT alias.drug_id, drug.name_display,
                       alias.normalized_value, alias.alias_value,
                       alias.source
                FROM drug_aliases alias
                JOIN drugs drug ON drug.id = alias.drug_id
                WHERE alias.normalized_value = ANY(:candidate_aliases)
                UNION ALL
                SELECT identifier.drug_id, drug.name_display,
                       identifier.normalized_value,
                       identifier.identifier_value, identifier.source
                FROM drug_identifiers identifier
                JOIN drugs drug ON drug.id = identifier.drug_id
                WHERE identifier.identifier_type IN ('chembl_id', 'pubchem_cid')
                  AND identifier.normalized_value = ANY(:candidate_aliases)
            )
            SELECT DISTINCT drug_id, name_display, normalized_value,
                   matched_alias, match_source,
                   LENGTH(normalized_value) AS match_length
            FROM identities
            WHERE LENGTH(normalized_value) >= 4
            ORDER BY LENGTH(normalized_value) DESC, drug_id
            LIMIT :limit
        """), {
            "candidate_aliases": candidate_aliases,
            "limit": max(10, limit * 5),
        }).mappings().all()
    return [dict(row) for row in rows]


def _question_alias_candidates(question: str) -> list[str]:
    """Return bounded contiguous phrases that can use exact identity indexes."""
    normalized = normalize_identifier_value("drug_alias", question)
    words = [
        word.strip(".,!?;:()[]{}\"'")
        for word in normalized.split()[:40]
    ]
    words = [word for word in words if word]
    candidates = {
        " ".join(words[start:end])
        for start in range(len(words))
        for end in range(start + 1, len(words) + 1)
        if len(" ".join(words[start:end])) >= 4
    }
    return sorted(candidates, key=lambda value: (-len(value), value))


def resolve_drug_mentions(
    question: str,
    search: Optional[Callable[[str, int], List[dict]]] = None,
) -> List[dict]:
    """Resolve only exact source-backed drug aliases present in the question."""
    search = search or _search_drugs_in_question
    try:
        candidates = search(question, 5)
    except Exception as exc:
        logger.warning("Drug mention resolution failed", error=str(exc))
        return []

    normalized_question = normalize_identifier_value("drug_alias", question)
    by_alias: dict[str, list[dict]] = {}
    for candidate in candidates:
        normalized_alias = normalize_identifier_value(
            "drug_alias",
            candidate.get("matched_alias") or candidate.get("name_display") or "",
        )
        if len(normalized_alias) < 4:
            continue
        if not re.search(
            rf"(?<!\w){re.escape(normalized_alias)}(?!\w)",
            normalized_question,
        ):
            continue
        by_alias.setdefault(normalized_alias, []).append(candidate)

    resolutions = []
    resolved_drug_ids: set[int] = set()
    for normalized_alias in sorted(by_alias, key=len, reverse=True):
        choices_by_id = {
            int(candidate["drug_id"]): candidate
            for candidate in by_alias[normalized_alias]
        }
        choices = list(choices_by_id.values())
        if len(choices) == 1:
            candidate = choices[0]
            drug_id = int(candidate["drug_id"])
            if drug_id in resolved_drug_ids:
                continue
            resolved_drug_ids.add(drug_id)
            resolutions.append({
                "entity_type": "drug",
                "mention": candidate.get("matched_alias") or normalized_alias,
                "status": "resolved",
                "drug_id": drug_id,
                "canonical_name": candidate["name_display"],
                "match_source": candidate.get("match_source"),
            })
        elif choices:
            resolutions.append({
                "entity_type": "drug",
                "mention": choices[0].get("matched_alias") or normalized_alias,
                "status": "ambiguous",
                "candidates": [
                    {
                        "drug_id": int(candidate["drug_id"]),
                        "canonical_name": candidate["name_display"],
                    }
                    for candidate in choices[:3]
                ],
            })
    return resolutions

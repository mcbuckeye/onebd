"""Deterministic, provenance-preserving contract financial-clause candidates."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from sqlalchemy import text

from unified_api.services.html_cleaner import clean_contract_html


CONTRACT_CLAUSE_PARSER_VERSION = 2

_ANCHORS = {
    "royalty_rate": re.compile(r"\broyalt(?:y|ies)\b", re.IGNORECASE),
    "milestone_payment": re.compile(r"\bmilestone(?:s)?\b", re.IGNORECASE),
    "upfront_payment": re.compile(
        r"\b(?:up[ -]?front|license issue fee|initial license fee)\b",
        re.IGNORECASE,
    ),
}
_RATE_RE = re.compile(
    r"(?<![\d.])(?P<value>\d{1,3}(?:\.\d+)?)\s*(?:%|percent\b)",
    re.IGNORECASE,
)
_SYMBOL_AMOUNT_RE = re.compile(
    r"(?P<currency>[$€£¥])\s*(?P<value>\d[\d,]*(?:\.\d+)?)"
    r"\s*(?P<unit>million|billion|thousand|mn|bn|m|b|k)?\b",
    re.IGNORECASE,
)
_CODE_AMOUNT_RE = re.compile(
    r"\b(?P<currency>USD|EUR|GBP|JPY)\s*"
    r"(?P<value>\d[\d,]*(?:\.\d+)?)"
    r"\s*(?P<unit>million|billion|thousand|mn|bn|m|b|k)?\b",
    re.IGNORECASE,
)
_CURRENCY_CODES = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}
_TIER_WORDS = re.compile(
    r"\b(?:tier(?:ed|s)?|schedule|threshold|annual net sales|sliding scale)\b",
    re.IGNORECASE,
)
_ROYALTY_RATE_CONTEXT = re.compile(
    r"\b(?:royalt(?:y|ies)|net sales|tier(?:ed|s)?|sublicens\w*)\b",
    re.IGNORECASE,
)
_NON_ROYALTY_RATE_CONTEXT = re.compile(
    r"\b(?:"
    r"underpay\w*|overpay\w*|audit\w*|accountant|reimburse\w*|"
    r"reimburs\w*|royalty[ -]?free|"
    r"delinquen\w*|late payment|interest|libor|prime rate|"
    r"credit\w*|offset\w*|deduct\w*|set[ -]?off|reduc\w*|"
    r"mandatory prepayment|not (?:greater|less) than|"
    r"responsible for (?:all )?costs|"
    r"costs? and expenses?|withhold\w*|tax(?:es)?|"
    r"extraordinary payment|percentage component|supply price"
    r")\b",
    re.IGNORECASE,
)
_PAYMENT_CONTEXT = re.compile(
    r"\b(?:pay(?:able|ment|ments|ing)?|fee|consideration|cash amount|amount due)\b",
    re.IGNORECASE,
)
_NONPAYMENT_AMOUNT_CONTEXT = re.compile(
    r"\b(?:"
    r"net sales|gross sales|revenue|sales threshold|par value|per share|"
    r"at the rate|per year|full[ -]?time staff|research support"
    r")\b",
    re.IGNORECASE,
)
_UPFRONT_AGGREGATE_CONTEXT = re.compile(
    r"\b(?:"
    r"research(?:\s+and\s+development)?\s+funding|equity\s+investment"
    r")\b",
    re.IGNORECASE,
)
_UPFRONT_EQUITY_CONTEXT = re.compile(
    r"\bup[ -]?front\s+equity\s+investment\b",
    re.IGNORECASE,
)
_UPFRONT_ALLOCATION_CONTEXT = re.compile(
    r"\b(?:"
    r"committee\s+reimbursement\s+amount|escrow\s+contribution\s+amount|"
    r"payment\s+agent|distribut(?:e|ion)\s+(?:of\s+)?the\s+upfront\s+payment"
    r")\b",
    re.IGNORECASE,
)
_MILESTONE_AGGREGATE_CONTEXT = re.compile(
    r"\b(?:"
    r"reimburse\w*|reimburs\w*|"
    r"research(?:\s+and\s+development)?\s+funding|equity\s+investment|"
    r"common\s+stock|marketing\s+support\s+fee|progress\s+payment|"
    r"initial\s+payment|license\s+execution|restructur\w*|settlement"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)
_SENTENCE_BOUNDARY = re.compile(
    r"(?:(?<![A-Z0-9])\.\s+|[!?;]\s+|\n\s*\n)"
)
_COMBINED_MILESTONE_PACKAGE = re.compile(
    r"\b(?:license\s+fees?|research(?:\s+and\s+development)?\s+funding)\b"
    r".{0,180}\bmilestone\s+payments?\b.{0,80}\b(?:including|total(?:ing)?)\b",
    re.IGNORECASE | re.DOTALL,
)
_HISTORICAL_MILESTONE_REFERENCE = re.compile(
    r"\b(?:has|have|had)\s+paid\b.{0,100}\bmilestone\b",
    re.IGNORECASE | re.DOTALL,
)
_MILESTONE_EXECUTION_ROW = re.compile(
    r"\bupon\s+execution\s+of\s+(?:the\s+)?license\b",
    re.IGNORECASE,
)


def _number(value: str) -> float:
    return float(value.replace(",", ""))


def _amount_millions(value: str, unit: str | None) -> float:
    number = _number(value)
    normalized = (unit or "").lower()
    if normalized in {"million", "mn", "m"}:
        return number
    if normalized in {"billion", "bn", "b"}:
        return number * 1000
    if normalized in {"thousand", "k"}:
        return number / 1000
    return number / 1_000_000


def _window(text_value: str, start: int, end: int) -> tuple[int, int]:
    """Return a bounded paragraph-oriented window around an anchor."""
    paragraph_start = text_value.rfind("\n\n", 0, start)
    paragraph_start = paragraph_start + 2 if paragraph_start >= 0 else 0
    paragraph_end = text_value.find("\n\n", end)
    paragraph_end = paragraph_end if paragraph_end >= 0 else len(text_value)

    anchor_paragraph = text_value[paragraph_start:paragraph_end]
    is_table_or_schedule = bool(re.search(
        r"\b(?:as follows|specified below|set forth below|amount\s+event|"
        r"milestone payment.*fuss)\b",
        anchor_paragraph,
        re.IGNORECASE | re.DOTALL,
    ))
    # Tables and schedules can span many short paragraphs. Prose windows keep
    # the original two-paragraph continuation to avoid unrelated sections.
    for _ in range(12 if is_table_or_schedule else 2):
        next_start = paragraph_end + 2
        if text_value[next_start:].lstrip().startswith("#"):
            break
        next_end = text_value.find("\n\n", paragraph_end + 2)
        if next_end < 0:
            if len(text_value) - paragraph_start <= 4000:
                paragraph_end = len(text_value)
            break
        if next_end - paragraph_start > 4000:
            break
        paragraph_end = next_end

    if paragraph_end - paragraph_start > 4000:
        paragraph_start = max(paragraph_start, start - 500)
        paragraph_end = min(len(text_value), paragraph_start + 4000)
    return paragraph_start, paragraph_end


def _candidate_windows(text_value: str, pattern: re.Pattern) -> list[tuple[int, int]]:
    windows = [_window(text_value, match.start(), match.end()) for match in pattern.finditer(text_value)]
    if not windows:
        return []

    merged: list[list[int]] = []
    for start, end in windows:
        if merged and start <= merged[-1][1] and end - merged[-1][0] <= 4000:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _rates(excerpt: str, absolute_start: int) -> list[dict]:
    values = []
    seen = set()
    for match in _RATE_RE.finditer(excerpt):
        value = _number(match.group("value"))
        if value > 100:
            continue
        key = (value, match.start())
        if key in seen:
            continue
        seen.add(key)
        values.append({
            "value_pct": value,
            "raw": match.group(0),
            "char_start": absolute_start + match.start(),
            "char_end": absolute_start + match.end(),
        })
    return values


def _rates_with_financial_context(excerpt: str, absolute_start: int) -> list[dict]:
    """Keep rates locally tied to royalties, excluding accounting/cost rates."""
    values = []
    for value in _rates(excerpt, absolute_start):
        relative_start = value["char_start"] - absolute_start
        relative_end = value["char_end"] - absolute_start
        paragraph_start = excerpt.rfind("\n\n", 0, relative_start)
        paragraph_start = paragraph_start + 2 if paragraph_start >= 0 else 0
        paragraph_end = excerpt.find("\n\n", relative_end)
        paragraph_end = paragraph_end if paragraph_end >= 0 else len(excerpt)
        paragraph = excerpt[paragraph_start:paragraph_end]
        paragraph_position = relative_start - paragraph_start
        royalty_distance = _nearest_context_distance(
            _ROYALTY_RATE_CONTEXT,
            paragraph,
            paragraph_position,
        )
        if royalty_distance is None or royalty_distance > 500:
            continue
        before = paragraph[max(0, paragraph_position - 140):paragraph_position]
        after = paragraph[
            paragraph_position + (relative_end - relative_start):
            paragraph_position + (relative_end - relative_start) + 140
        ]
        directly_linked = bool(
            re.search(r"royalt(?:y|ies)\b.{0,100}$", before, re.IGNORECASE)
            or re.match(r"\s*royalt(?:y|ies)\b", after, re.IGNORECASE)
            or re.match(
                r"\s*(?:for|of|on|based\s+on)?\s*(?:the\s+)?"
                r"net\s+(?:sales|revenues)\b",
                after,
                re.IGNORECASE,
            )
            or (
                bool(_TIER_WORDS.search(paragraph))
                and bool(_ANCHORS["royalty_rate"].search(paragraph))
                and royalty_distance <= 500
            )
        )
        if not directly_linked:
            continue
        local_start = max(0, relative_start - 220)
        local_end = min(len(excerpt), relative_end + 220)
        if _NON_ROYALTY_RATE_CONTEXT.search(excerpt[local_start:local_end]):
            continue
        values.append(value)
    return values


def _monetary_values(excerpt: str, absolute_start: int) -> list[dict]:
    values = []
    seen_spans = set()
    for pattern in (_SYMBOL_AMOUNT_RE, _CODE_AMOUNT_RE):
        for match in pattern.finditer(excerpt):
            span = match.span()
            if span in seen_spans:
                continue
            seen_spans.add(span)
            raw_currency = match.group("currency")
            values.append({
                "amount_millions": _amount_millions(
                    match.group("value"),
                    match.group("unit"),
                ),
                "currency": _CURRENCY_CODES.get(
                    raw_currency,
                    raw_currency.upper(),
                ),
                "raw": match.group(0),
                "char_start": absolute_start + match.start(),
                "char_end": absolute_start + match.end(),
            })
    return sorted(values, key=lambda value: value["char_start"])


def _nearest_context_distance(pattern: re.Pattern, text_value: str, position: int) -> int | None:
    distances = [
        min(abs(position - match.start()), abs(position - match.end()))
        for match in pattern.finditer(text_value)
    ]
    return min(distances) if distances else None


def _is_same_sentence_or_following_heading(
    excerpt: str,
    value_start: int,
    value_end: int,
    anchor: re.Match,
) -> bool:
    """Require a local clause link while allowing a short payment-table heading."""
    if anchor.end() <= value_start:
        between = excerpt[anchor.end():value_start]
    elif value_end <= anchor.start():
        between = excerpt[value_end:anchor.start()]
    else:
        return True
    if not _SENTENCE_BOUNDARY.search(between):
        return True
    if anchor.start() >= value_start:
        return False
    line_start = excerpt.rfind("\n", 0, anchor.start()) + 1
    line_end = excerpt.find("\n", anchor.end())
    line_end = line_end if line_end >= 0 else len(excerpt)
    heading = excerpt[line_start:line_end].strip()
    sentence_end = excerpt.find(".", anchor.end())
    inline_heading = (
        not excerpt[line_start:anchor.start()].strip()
        and sentence_end >= 0
        and sentence_end - anchor.end() <= 30
    )
    return (
        (
            inline_heading
            or (
                len(heading) <= 100
                and bool(re.fullmatch(
                    r"(?:[#\d.()\s-]*)?(?:milestone(?:s)?(?:\s+payments?)?|"
                    r"up[ -]?front(?:\s+(?:fees?|payments?|consideration))?|"
                    r"license issue fee)[:.]?",
                    heading,
                    re.IGNORECASE,
                ))
            )
        )
        and value_start - anchor.end() <= 600
    )


def _is_event_only_milestone_anchor(excerpt: str, anchor: re.Match) -> bool:
    """Identify a named trigger rather than a milestone-payment label."""
    context = excerpt[max(0, anchor.start() - 70):anchor.end() + 70]
    if re.search(
        r"\bmilestone\s+payments?\b|\bpayment\s+milestone\b",
        context,
        re.IGNORECASE,
    ):
        return False
    return bool(re.search(
        r"\b(?:achiev\w*|reach\w*|satisf\w*)\b.{0,60}\bmilestone\b",
        context,
        re.IGNORECASE | re.DOTALL,
    ))


def _is_payment_list_value(
    excerpt: str,
    value_start: int,
    anchor: re.Match,
) -> bool:
    """Keep values under an explicit 'payments as follows' list heading."""
    if anchor.end() > value_start or value_start - anchor.end() > 1400:
        return False
    lead = excerpt[anchor.end():min(len(excerpt), anchor.end() + 100)]
    header_context = excerpt[max(0, anchor.start() - 500):anchor.end() + 100]
    explicit_list = bool(re.search(
        r"\b(?:as follows|following|set forth)\b",
        lead,
        re.IGNORECASE,
    ))
    explicit_table = bool(re.search(
        r"\b(?:specified below|milestone\s+payments?)\b",
        header_context,
        re.IGNORECASE,
    )) and "\n" in excerpt[anchor.end():value_start]
    if not (explicit_list or explicit_table):
        return False
    between = excerpt[anchor.end():value_start]
    # A new top-level lettered clause ends the preceding payment list. Nested
    # roman-numeral entries remain part of it.
    if re.search(r"(?:^|\n)\s*\([a-h]\)\s+", between):
        return False
    return True


def _has_strong_payment_link(
    excerpt: str,
    value_start: int,
    value_end: int,
    anchor: re.Match,
) -> bool:
    """Allow a short trigger-to-payment sentence pair such as Milestone I."""
    if anchor.start() >= value_start:
        return False
    segment_start = min(value_start, anchor.start())
    segment_end = max(value_end, anchor.end())
    if segment_end - segment_start > 260:
        return False
    segment = excerpt[segment_start:segment_end]
    if "\n\n" in segment or re.search(
        r"(?:^|\n)\s*\([a-h]\)\s+",
        segment,
    ):
        return False
    return bool(re.search(
        r"\b(?:pay|pays|paid|payable|payment|payments|amount|receive|"
        r"receives|eligible|due)\b",
        segment,
        re.IGNORECASE,
    ))


def _is_combined_payment_amount(
    excerpt: str,
    value: dict,
    target_anchor: re.Match,
    competing_anchor: re.Match | None,
    monetary_values: list[dict],
    absolute_start: int,
) -> bool:
    """Detect one amount expressly aggregating upfront and milestone value."""
    if competing_anchor is None:
        return False
    value_start = value["char_start"] - absolute_start
    value_end = value["char_end"] - absolute_start
    both_after = (
        target_anchor.start() >= value_end
        and competing_anchor.start() >= value_end
    )
    both_before = (
        target_anchor.end() <= value_start
        and competing_anchor.end() <= value_start
    )
    if not (both_after or both_before):
        return False
    segment_start = min(
        value_start,
        target_anchor.start(),
        competing_anchor.start(),
    )
    segment_end = max(
        value_end,
        target_anchor.end(),
        competing_anchor.end(),
    )
    for other in monetary_values:
        if other is value:
            continue
        other_start = other["char_start"] - absolute_start
        other_end = other["char_end"] - absolute_start
        if other_start >= segment_start and other_end <= segment_end:
            return False
    segment = excerpt[segment_start:segment_end]
    between_anchors = excerpt[
        min(target_anchor.end(), competing_anchor.end()):
        max(target_anchor.start(), competing_anchor.start())
    ]
    if re.search(r"[,;]", between_anchors):
        return False
    return bool(re.search(r"\b(?:and|includes?|including)\b", segment, re.IGNORECASE))


def _payment_monetary_values(
    excerpt: str,
    absolute_start: int,
    clause_type: str,
) -> list[dict]:
    """Retain explicit payment amounts, excluding closer sales/par-value context."""
    anchors = list(_ANCHORS[clause_type].finditer(excerpt))
    competing_types = (
        {"milestone_payment", "upfront_payment"} - {clause_type}
    )
    competing_anchors = [
        match
        for competing_type in competing_types
        for match in _ANCHORS[competing_type].finditer(excerpt)
    ]
    if clause_type == "upfront_payment":
        competing_anchors = [
            match
            for match in competing_anchors
            if not _is_event_only_milestone_anchor(excerpt, match)
        ]
    values = []
    monetary_values = _monetary_values(excerpt, absolute_start)
    for value in monetary_values:
        if value["amount_millions"] < 0.001:
            continue
        relative_start = value["char_start"] - absolute_start
        relative_end = value["char_end"] - absolute_start
        position = (relative_start + relative_end) // 2
        anchor_distance = min(
            (
                min(abs(position - match.start()), abs(position - match.end()))
                for match in anchors
            ),
            default=None,
        )
        if anchor_distance is None or anchor_distance > 750:
            continue
        competing_distance = min(
            (
                min(abs(position - match.start()), abs(position - match.end()))
                for match in competing_anchors
            ),
            default=None,
        )
        if competing_distance is not None and competing_distance < anchor_distance:
            continue
        closest_anchor = min(
            anchors,
            key=lambda match: min(
                abs(position - match.start()),
                abs(position - match.end()),
            ),
        )
        closest_competing_anchor = min(
            competing_anchors,
            key=lambda match: min(
                abs(position - match.start()),
                abs(position - match.end()),
            ),
            default=None,
        )
        if _is_combined_payment_amount(
            excerpt,
            value,
            closest_anchor,
            closest_competing_anchor,
            monetary_values,
            absolute_start,
        ):
            continue
        same_sentence = _is_same_sentence_or_following_heading(
            excerpt, relative_start, relative_end, closest_anchor
        )
        list_value = _is_payment_list_value(
            excerpt, relative_start, closest_anchor
        )
        strong_link = _has_strong_payment_link(
            excerpt, relative_start, relative_end, closest_anchor
        )
        if not (same_sentence or list_value or strong_link):
            continue
        if (
            clause_type == "milestone_payment"
            and _is_event_only_milestone_anchor(excerpt, closest_anchor)
            and closest_competing_anchor is not None
            and competing_distance is not None
            and competing_distance <= 750
        ):
            continue
        # Permit "$5m milestone payment", but do not pull an earlier, unrelated
        # transaction amount into a later milestone/upfront section.
        if closest_anchor.start() - position > 80:
            continue
        context_start = max(0, relative_start - 250)
        context_end = min(len(excerpt), relative_end + 250)
        context = excerpt[context_start:context_end]
        context_position = position - context_start
        payment_distance = _nearest_context_distance(
            _PAYMENT_CONTEXT,
            context,
            context_position,
        )
        nonpayment_distance = _nearest_context_distance(
            _NONPAYMENT_AMOUNT_CONTEXT,
            context,
            context_position,
        )
        if payment_distance is None:
            continue
        if nonpayment_distance is not None and nonpayment_distance < payment_distance:
            continue
        if clause_type == "upfront_payment":
            aggregate_distance = _nearest_context_distance(
                _UPFRONT_AGGREGATE_CONTEXT,
                context,
                context_position,
            )
            if (
                aggregate_distance is not None
                and aggregate_distance < anchor_distance
            ):
                continue
            if _UPFRONT_EQUITY_CONTEXT.search(context):
                continue
            allocation_distance = _nearest_context_distance(
                _UPFRONT_ALLOCATION_CONTEXT,
                context,
                context_position,
            )
            if (
                allocation_distance is not None
                and allocation_distance < anchor_distance
            ):
                continue
        if clause_type == "milestone_payment":
            sentence_start = max(
                excerpt.rfind(".", 0, relative_start),
                excerpt.rfind("\n\n", 0, relative_start),
            ) + 1
            sentence_end = excerpt.find(".", relative_end)
            sentence_end = sentence_end if sentence_end >= 0 else len(excerpt)
            sentence = excerpt[sentence_start:sentence_end]
            value_line_start = excerpt.rfind("\n", 0, relative_start) + 1
            value_line_end = excerpt.find("\n", relative_end)
            value_line_end = value_line_end if value_line_end >= 0 else len(excerpt)
            if _MILESTONE_EXECUTION_ROW.search(
                excerpt[value_line_start:value_line_end]
            ):
                continue
            if _COMBINED_MILESTONE_PACKAGE.search(sentence):
                continue
            historical_start = max(0, closest_anchor.start() - 140)
            if _HISTORICAL_MILESTONE_REFERENCE.search(
                excerpt[historical_start:relative_end]
            ):
                continue
            aggregate_distance = _nearest_context_distance(
                _MILESTONE_AGGREGATE_CONTEXT,
                context,
                context_position,
            )
            if (
                aggregate_distance is not None
                and aggregate_distance < anchor_distance
            ):
                continue
        values.append(value)
    return values


def extract_contract_financial_clauses(
    contract_text: str | None,
    *,
    contract_id: int | None = None,
    deal_id: int | None = None,
) -> list[dict]:
    """Extract explicit financial-clause candidates with replayable evidence."""
    clean_text = clean_contract_html(contract_text)
    if not clean_text:
        return []

    clauses = []
    seen = set()
    for clause_type, anchor in _ANCHORS.items():
        for start, end in _candidate_windows(clean_text, anchor):
            excerpt = clean_text[start:end].strip()
            if not excerpt:
                continue
            stripped_start = clean_text.find(excerpt, start, end)
            stripped_end = stripped_start + len(excerpt)
            rates = _rates_with_financial_context(excerpt, stripped_start)
            if clause_type != "royalty_rate":
                rates = []
            monetary_values = (
                _monetary_values(excerpt, stripped_start)
                if clause_type == "royalty_rate"
                else _payment_monetary_values(
                    excerpt,
                    stripped_start,
                    clause_type,
                )
            )

            if clause_type == "royalty_rate" and not rates:
                continue
            if clause_type in {"milestone_payment", "upfront_payment"} and not monetary_values:
                continue

            source_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
            dedupe_key = (clause_type, source_hash)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            rate_values = [item["value_pct"] for item in rates]
            amount_values = [item["amount_millions"] for item in monetary_values]
            currencies = sorted({item["currency"] for item in monetary_values})
            clauses.append({
                "contract_id": contract_id,
                "deal_id": deal_id,
                "clause_type": clause_type,
                "rate_min_pct": min(rate_values) if rate_values else None,
                "rate_max_pct": max(rate_values) if rate_values else None,
                "amount_min_millions": min(amount_values)
                if clause_type != "royalty_rate" and amount_values else None,
                "amount_max_millions": max(amount_values)
                if clause_type != "royalty_rate" and amount_values else None,
                "currency": currencies[0] if len(currencies) == 1 else None,
                "is_tiered": clause_type == "royalty_rate"
                and (len(set(rate_values)) > 1 or bool(_TIER_WORDS.search(excerpt))),
                "confidence": 0.95,
                "review_status": "unreviewed",
                "source_text": excerpt,
                "source_char_start": stripped_start,
                "source_char_end": stripped_end,
                "source_line_start": clean_text.count("\n", 0, stripped_start) + 1,
                "source_line_end": clean_text.count("\n", 0, stripped_end) + 1,
                "source_hash": source_hash,
                "parser_version": CONTRACT_CLAUSE_PARSER_VERSION,
                "extracted_values": {
                    "rates": rates,
                    "monetary_values": monetary_values,
                },
            })
    return clauses


def ensure_contract_financial_clause_schema(session) -> None:
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS contract_financial_clauses (
            id BIGSERIAL PRIMARY KEY,
            contract_id INTEGER NOT NULL REFERENCES contract_content(id) ON DELETE CASCADE,
            deal_id INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
            clause_type TEXT NOT NULL,
            rate_min_pct DOUBLE PRECISION,
            rate_max_pct DOUBLE PRECISION,
            amount_min_millions DOUBLE PRECISION,
            amount_max_millions DOUBLE PRECISION,
            currency VARCHAR(10),
            is_tiered BOOLEAN NOT NULL DEFAULT FALSE,
            confidence DOUBLE PRECISION NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'unreviewed',
            reviewer TEXT,
            review_note TEXT,
            reviewed_at TIMESTAMPTZ,
            source_text TEXT NOT NULL,
            source_char_start INTEGER NOT NULL,
            source_char_end INTEGER NOT NULL,
            source_line_start INTEGER NOT NULL,
            source_line_end INTEGER NOT NULL,
            source_hash VARCHAR(64) NOT NULL,
            parser_version INTEGER NOT NULL,
            extracted_values JSONB NOT NULL,
            extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (contract_id, clause_type, source_hash, parser_version)
        )
    """))
    session.execute(text("""
        ALTER TABLE contract_financial_clauses
        ADD COLUMN IF NOT EXISTS reviewer TEXT
    """))
    session.execute(text("""
        ALTER TABLE contract_financial_clauses
        ADD COLUMN IF NOT EXISTS review_note TEXT
    """))
    session.execute(text("""
        ALTER TABLE contract_financial_clauses
        ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ
    """))
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_contract_financial_clauses_analytics
        ON contract_financial_clauses (
            clause_type, review_status, rate_min_pct, amount_min_millions
        )
    """))
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_contract_financial_clauses_deal
        ON contract_financial_clauses (deal_id)
    """))
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS contract_financial_clause_extractions (
            contract_id INTEGER PRIMARY KEY REFERENCES contract_content(id) ON DELETE CASCADE,
            deal_id INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
            source_hash VARCHAR(64) NOT NULL,
            parser_version INTEGER NOT NULL,
            status TEXT NOT NULL,
            clauses_extracted INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))


def extract_contract_financial_clause_batch(
    session,
    *,
    batch_size: int = 500,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """Extract one serialized, resumable batch of eligible contracts."""
    lock_acquired = session.execute(text(
        "SELECT pg_try_advisory_xact_lock(hashtext('onebd_contract_financial_clauses'))"
    )).scalar()
    if not lock_acquired:
        return {
            "status": "busy",
            "processed": 0,
            "clauses_extracted": 0,
            "errors": 0,
            "parser_version": CONTRACT_CLAUSE_PARSER_VERSION,
            "sample": [],
        }

    ensure_contract_financial_clause_schema(session)
    contracts = session.execute(text("""
        SELECT c.id AS contract_id, c.deal_id, c.content,
               md5(c.content) AS source_hash
        FROM contract_content c
        LEFT JOIN contract_financial_clause_extractions e
          ON e.contract_id = c.id
        WHERE c.content IS NOT NULL
          AND c.deal_id IS NOT NULL
          AND LENGTH(c.content) >= 100
          AND (
            :force
            OR e.contract_id IS NULL
            OR e.parser_version <> :parser_version
            OR e.source_hash <> md5(c.content)
            OR e.status = 'failed'
          )
        ORDER BY c.id
        LIMIT :batch_size
    """), {
        "force": force,
        "parser_version": CONTRACT_CLAUSE_PARSER_VERSION,
        "batch_size": batch_size,
    }).mappings().all()

    processed = 0
    clauses_extracted = 0
    errors = 0
    samples = []
    for contract in contracts:
        contract_id = int(contract["contract_id"])
        deal_id = int(contract["deal_id"])
        source_hash = contract["source_hash"]
        try:
            with session.begin_nested():
                clauses = extract_contract_financial_clauses(
                    contract["content"],
                    contract_id=contract_id,
                    deal_id=deal_id,
                )
                if not dry_run:
                    previous_reviews = {}
                    reviewed_rows = session.execute(text("""
                        SELECT clause_type, source_hash, review_status,
                               reviewer, review_note, reviewed_at
                        FROM contract_financial_clauses
                        WHERE contract_id = :contract_id
                          AND review_status IN ('accepted', 'rejected')
                        ORDER BY parser_version DESC, reviewed_at DESC NULLS LAST
                    """), {"contract_id": contract_id}).mappings().all()
                    for reviewed_row in reviewed_rows:
                        previous_reviews.setdefault(
                            (
                                reviewed_row["clause_type"],
                                reviewed_row["source_hash"],
                            ),
                            dict(reviewed_row),
                        )
                    session.execute(text(
                        "DELETE FROM contract_financial_clauses "
                        "WHERE contract_id = :contract_id"
                    ), {"contract_id": contract_id})
                    for clause in clauses:
                        previous_review = previous_reviews.get((
                            clause["clause_type"],
                            clause["source_hash"],
                        )) or {}
                        session.execute(text("""
                            INSERT INTO contract_financial_clauses (
                                contract_id, deal_id, clause_type,
                                rate_min_pct, rate_max_pct,
                                amount_min_millions, amount_max_millions,
                                currency, is_tiered, confidence, review_status,
                                reviewer, review_note, reviewed_at,
                                source_text, source_char_start, source_char_end,
                                source_line_start, source_line_end, source_hash,
                                parser_version, extracted_values
                            ) VALUES (
                                :contract_id, :deal_id, :clause_type,
                                :rate_min_pct, :rate_max_pct,
                                :amount_min_millions, :amount_max_millions,
                                :currency, :is_tiered, :confidence, :review_status,
                                :reviewer, :review_note, :reviewed_at,
                                :source_text, :source_char_start, :source_char_end,
                                :source_line_start, :source_line_end, :source_hash,
                                :parser_version, CAST(:extracted_values AS JSONB)
                            )
                        """), {
                            **{
                                key: value
                                for key, value in clause.items()
                                if key != "extracted_values"
                            },
                            "review_status": previous_review.get(
                                "review_status",
                                clause["review_status"],
                            ),
                            "reviewer": previous_review.get("reviewer"),
                            "review_note": previous_review.get("review_note"),
                            "reviewed_at": previous_review.get("reviewed_at"),
                            "extracted_values": json.dumps(
                                clause["extracted_values"]
                            ),
                        })
                    session.execute(text("""
                        INSERT INTO contract_financial_clause_extractions (
                            contract_id, deal_id, source_hash, parser_version,
                            status, clauses_extracted, error_message, extracted_at
                        ) VALUES (
                            :contract_id, :deal_id, :source_hash, :parser_version,
                            'completed', :clauses_extracted, NULL, NOW()
                        )
                        ON CONFLICT (contract_id) DO UPDATE SET
                            deal_id = EXCLUDED.deal_id,
                            source_hash = EXCLUDED.source_hash,
                            parser_version = EXCLUDED.parser_version,
                            status = EXCLUDED.status,
                            clauses_extracted = EXCLUDED.clauses_extracted,
                            error_message = NULL,
                            extracted_at = NOW()
                    """), {
                        "contract_id": contract_id,
                        "deal_id": deal_id,
                        "source_hash": source_hash,
                        "parser_version": CONTRACT_CLAUSE_PARSER_VERSION,
                        "clauses_extracted": len(clauses),
                    })
            processed += 1
            clauses_extracted += len(clauses)
            if clauses and len(samples) < 5:
                samples.append({
                    "contract_id": contract_id,
                    "deal_id": deal_id,
                    "clauses": clauses[:3],
                })
        except Exception as exc:
            errors += 1
            if not dry_run:
                with session.begin_nested():
                    session.execute(text("""
                        INSERT INTO contract_financial_clause_extractions (
                            contract_id, deal_id, source_hash, parser_version,
                            status, clauses_extracted, error_message, extracted_at
                        ) VALUES (
                            :contract_id, :deal_id, :source_hash, :parser_version,
                            'failed', 0, :error, NOW()
                        )
                        ON CONFLICT (contract_id) DO UPDATE SET
                            deal_id = EXCLUDED.deal_id,
                            source_hash = EXCLUDED.source_hash,
                            parser_version = EXCLUDED.parser_version,
                            status = 'failed', clauses_extracted = 0,
                            error_message = EXCLUDED.error_message,
                            extracted_at = NOW()
                    """), {
                        "contract_id": contract_id,
                        "deal_id": deal_id,
                        "source_hash": source_hash,
                        "parser_version": CONTRACT_CLAUSE_PARSER_VERSION,
                        "error": str(exc)[:1000],
                    })

    return {
        "status": "completed",
        "processed": processed,
        "clauses_extracted": clauses_extracted,
        "errors": errors,
        "parser_version": CONTRACT_CLAUSE_PARSER_VERSION,
        "sample": samples,
    }


def contract_financial_clause_status(session) -> dict:
    ensure_contract_financial_clause_schema(session)
    row = session.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM contract_content
             WHERE content IS NOT NULL AND deal_id IS NOT NULL
               AND LENGTH(content) >= 100)
                AS eligible_contracts,
            (SELECT COUNT(*) FROM contract_financial_clause_extractions
             WHERE status = 'completed' AND parser_version = :parser_version)
                AS contracts_parsed,
            (SELECT COUNT(*) FROM contract_financial_clause_extractions
             WHERE status = 'failed' AND parser_version = :parser_version)
                AS contracts_failed,
            (SELECT COUNT(*) FROM contract_financial_clauses
             WHERE parser_version = :parser_version) AS clauses_total,
            (SELECT COUNT(DISTINCT contract_id) FROM contract_financial_clauses
             WHERE parser_version = :parser_version) AS contracts_with_clauses,
            (SELECT COUNT(*) FROM contract_financial_clauses
             WHERE parser_version = :parser_version
               AND clause_type = 'royalty_rate') AS royalty_clauses,
            (SELECT COUNT(*) FROM contract_financial_clauses
             WHERE parser_version = :parser_version
               AND clause_type = 'milestone_payment') AS milestone_clauses,
            (SELECT COUNT(*) FROM contract_financial_clauses
             WHERE parser_version = :parser_version
               AND clause_type = 'upfront_payment') AS upfront_clauses
    """), {"parser_version": CONTRACT_CLAUSE_PARSER_VERSION}).mappings().one()
    result = dict(row)
    eligible = int(result["eligible_contracts"] or 0)
    result["parse_coverage_pct"] = round(
        100 * int(result["contracts_parsed"] or 0) / eligible,
        2,
    ) if eligible else 0.0
    result["parser_version"] = CONTRACT_CLAUSE_PARSER_VERSION
    return result


def contract_financial_clause_review_sample(session, *, limit: int = 100) -> list[dict]:
    """Return a stable, clause-type-balanced sample awaiting human review."""
    ensure_contract_financial_clause_schema(session)
    limit = max(1, min(500, limit))
    per_type = math.ceil(limit / len(_ANCHORS))
    rows = session.execute(text("""
        WITH ranked AS (
            SELECT id, contract_id, deal_id, clause_type,
                   rate_min_pct, rate_max_pct,
                   amount_min_millions, amount_max_millions,
                   currency, is_tiered, confidence, source_text,
                   source_line_start, source_line_end, source_hash,
                   ROW_NUMBER() OVER (
                       PARTITION BY clause_type
                       ORDER BY md5(contract_id::text || ':' || source_hash)
                   ) AS sample_rank
            FROM contract_financial_clauses
            WHERE parser_version = :parser_version
              AND review_status = 'unreviewed'
        )
        SELECT * FROM ranked
        WHERE sample_rank <= :per_type
        ORDER BY sample_rank, clause_type
        LIMIT :limit
    """), {
        "parser_version": CONTRACT_CLAUSE_PARSER_VERSION,
        "per_type": per_type,
        "limit": limit,
    }).mappings().all()
    return [dict(row) for row in rows]


def review_contract_financial_clause(
    session,
    *,
    clause_id: int,
    review_status: str,
    reviewer: str,
    note: str | None = None,
) -> dict | None:
    """Persist one explicit human accept/reject decision."""
    if review_status not in {"accepted", "rejected"}:
        raise ValueError("review_status must be accepted or rejected")
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("reviewer is required")
    ensure_contract_financial_clause_schema(session)
    row = session.execute(text("""
        UPDATE contract_financial_clauses
        SET review_status = :review_status,
            reviewer = :reviewer,
            review_note = :note,
            reviewed_at = NOW()
        WHERE id = :clause_id
        RETURNING id, contract_id, deal_id, clause_type, review_status,
                  reviewer, review_note, reviewed_at
    """), {
        "clause_id": clause_id,
        "review_status": review_status,
        "reviewer": reviewer,
        "note": note,
    }).mappings().one_or_none()
    return dict(row) if row else None


def _same_value(actual: Any, expected: Any) -> bool:
    if isinstance(actual, (int, float)) or isinstance(expected, (int, float)):
        if actual is None or expected is None:
            return actual is expected
        return math.isclose(float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-9)
    return actual == expected


def contract_financial_clause_validation_status(
    session,
    *,
    sample_per_type: int = 25,
) -> dict:
    """Return population checks, deterministic replay, and review readiness."""
    sample_per_type = max(1, min(100, sample_per_type))
    status = contract_financial_clause_status(session)
    population = dict(session.execute(text("""
        SELECT
            COUNT(*) FILTER (
                WHERE rate_min_pct < 0 OR rate_max_pct < 0
                   OR rate_min_pct > 100 OR rate_max_pct > 100
                   OR (rate_min_pct IS NOT NULL AND rate_max_pct IS NOT NULL
                       AND rate_min_pct > rate_max_pct)
            ) AS invalid_rate_clauses,
            COUNT(*) FILTER (
                WHERE amount_min_millions < 0 OR amount_max_millions < 0
                   OR (amount_min_millions IS NOT NULL
                       AND amount_max_millions IS NOT NULL
                       AND amount_min_millions > amount_max_millions)
            ) AS invalid_amount_clauses,
            COUNT(*) FILTER (
                WHERE source_text = '' OR source_char_start < 0
                   OR source_char_end <= source_char_start
                   OR length(source_hash) <> 64
            ) AS invalid_provenance_clauses,
            COUNT(*) FILTER (WHERE review_status = 'accepted') AS reviewed_accepted,
            COUNT(*) FILTER (WHERE review_status = 'rejected') AS reviewed_rejected,
            COUNT(*) FILTER (WHERE review_status = 'unreviewed') AS unreviewed_clauses
        FROM contract_financial_clauses
        WHERE parser_version = :parser_version
    """), {"parser_version": CONTRACT_CLAUSE_PARSER_VERSION}).mappings().one())

    rows = session.execute(text("""
        WITH sampled AS (
            SELECT c.*, cc.content,
                   ROW_NUMBER() OVER (
                       PARTITION BY c.clause_type
                       ORDER BY md5(c.contract_id::text || ':' || c.source_hash)
                   ) AS sample_rank
            FROM contract_financial_clauses c
            JOIN contract_content cc ON cc.id = c.contract_id
            WHERE c.parser_version = :parser_version
        )
        SELECT * FROM sampled
        WHERE sample_rank <= :sample_per_type
        ORDER BY clause_type, sample_rank
    """), {
        "parser_version": CONTRACT_CLAUSE_PARSER_VERSION,
        "sample_per_type": sample_per_type,
    }).mappings().all()

    replay_cache: dict[int, dict[tuple[str, str], dict]] = {}
    failures = []
    replay_failure_count = 0
    for row in rows:
        contract_id = int(row["contract_id"])
        if contract_id not in replay_cache:
            replay = extract_contract_financial_clauses(
                row["content"],
                contract_id=contract_id,
                deal_id=int(row["deal_id"]),
            )
            replay_cache[contract_id] = {
                (item["clause_type"], item["source_hash"]): item
                for item in replay
            }
        expected = replay_cache[contract_id].get((
            row["clause_type"],
            row["source_hash"],
        ))
        mismatches = []
        if expected is None:
            mismatches.append({"field": "source_hash", "expected": "replayed", "actual": "missing"})
        else:
            for field in (
                "rate_min_pct",
                "rate_max_pct",
                "amount_min_millions",
                "amount_max_millions",
                "currency",
                "is_tiered",
                "source_text",
                "source_char_start",
                "source_char_end",
            ):
                if not _same_value(row[field], expected[field]):
                    mismatches.append({
                        "field": field,
                        "expected": expected[field],
                        "actual": row[field],
                    })
        if mismatches:
            replay_failure_count += 1
            if len(failures) < 20:
                failures.append({
                    "clause_id": row["id"],
                    "contract_id": contract_id,
                    "deal_id": row["deal_id"],
                    "clause_type": row["clause_type"],
                    "mismatches": mismatches,
                })

    sampled = len(rows)
    replay_failures = replay_failure_count
    reviewed_accepted = int(population["reviewed_accepted"] or 0)
    reviewed_rejected = int(population["reviewed_rejected"] or 0)
    reviewed = reviewed_accepted + reviewed_rejected
    review_precision = round(100 * reviewed_accepted / reviewed, 2) if reviewed else None
    report = {
        **status,
        **population,
        "sampled_clauses": sampled,
        "sample_replay_failures": replay_failures,
        "sample_replay_accuracy_pct": round(
            100 * (sampled - replay_failures) / sampled,
            2,
        ) if sampled else 0.0,
        "reviewed_clauses": reviewed,
        "review_precision_pct": review_precision,
        "failure_samples": failures,
    }
    report["technical_release_ready"] = bool(
        report["parse_coverage_pct"] == 100.0
        and report["clauses_total"] > 0
        and not report["contracts_failed"]
        and not report["invalid_rate_clauses"]
        and not report["invalid_amount_clauses"]
        and not report["invalid_provenance_clauses"]
        and report["sample_replay_accuracy_pct"] == 100.0
    )
    report["governed_release_ready"] = bool(
        report["technical_release_ready"]
        and reviewed >= 100
        and review_precision is not None
        and review_precision >= 95.0
    )
    return report

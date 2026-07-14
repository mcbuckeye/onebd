"""Deterministic, provenance-preserving contract financial-clause candidates."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from sqlalchemy import text

from unified_api.services.html_cleaner import clean_contract_html


CONTRACT_CLAUSE_PARSER_VERSION = 11

_ANCHORS = {
    "royalty_rate": re.compile(r"\broyalt(?:y|ies)\b", re.IGNORECASE),
    "milestone_payment": re.compile(r"\bmilestone(?:s)?\b", re.IGNORECASE),
    "upfront_payment": re.compile(
        r"\b(?:up[ -]?front|license issue fee|initial license fee)\b",
        re.IGNORECASE,
    ),
}
_RATE_RE = re.compile(
    # Do not read the denominator in legacy forms such as ``5-1/2%`` or
    # ``51/2%`` as an independent 2% rate.  We deliberately suppress the
    # ambiguous fraction rather than manufacture a precise decimal value.
    r"(?<![\d./-])(?P<value>\d{1,3}(?:\.\d+)?)\s*(?:%|percent\b)",
    re.IGNORECASE,
)
_SYMBOL_AMOUNT_RE = re.compile(
    r"(?P<currency>[$€£¥])\s*(?P<value>\d[\d,]*(?:\.\d+)?)"
    r"\s*(?P<unit>million|billion|thousand|mn|bn|m|b|k)?\b",
    re.IGNORECASE,
)
_QUALIFIED_DOLLAR_AMOUNT_RE = re.compile(
    r"(?<!\w)(?P<currency>U\.?S\.?|US|Cdn|CAD|Can|AUS|AUD)\s*\$\s*"
    r"(?P<value>\d[\d,]*(?:\.\d+)?)"
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
_QUALIFIED_DOLLAR_CODES = {
    "US": "USD",
    "CDN": "CAD",
    "CAD": "CAD",
    "CAN": "CAD",
    "AUS": "AUD",
    "AUD": "AUD",
}
_TIER_WORDS = re.compile(
    r"\b(?:tier(?:ed|s)?|threshold|annual net sales|sliding scale)\b",
    re.IGNORECASE,
)
_ROYALTY_RATE_CONTEXT = re.compile(
    r"\b(?:royalt(?:y|ies)|net sales|tier(?:ed|s)?|sublicens\w*)\b",
    re.IGNORECASE,
)
_NON_ROYALTY_RATE_CONTEXT = re.compile(
    r"\b(?:"
    r"underpay\w*|overpay\w*|audit\w*|accountant|reimburse\w*|"
    r"reimburs\w*|royalty[ -]?free|diminish\w*|"
    r"delinquen\w*|late payment|interest|libor|prime rate|"
    r"late charges?|allocat\w*|apportion\w*|"
    r"credit\w*|offset\w*|deduct\w*|set[ -]?off|reduc\w*|"
    r"mandatory prepayment|not (?:greater|less) than|"
    r"responsible for (?:all )?costs|borne|"
    r"costs? and expenses?|withhold\w*|tax(?:es)?|"
    r"extraordinary payment|percentage component|supply price|"
    r"(?:contracts?|agreements?).{0,50}provide for royalt\w*|"
    r"errors? in royalt\w*|discrepanc\w* in (?:the amount of )?royalt\w*|"
    r"(?:percent|%).{0,12}of\s+amounts\s+(?:previously\s+)?paid|"
    r"disclosure schedule|material contracts?|equal or exceed|"
    r"financial consideration|"
    r"(?:percent|%).{0,30}of\s+(?:the\s+)?applicable\s+royalty\s+rates?|"
    r"reduced by one[ -]?half|half of (?:the )?applicable royalty rates?"
    r"|royalty\s+shall\s+not\s+be\s+applicable|"
    r"development\s+expenditure|co-development\s+costs?|"
    r"damages\s+and\s+(?:litigation\s+)?expenses|for\s+example|"
    r"(?:then\s+)?outstanding\s+voting\s+stock|change\s+of\s+control|"
    r"amount\s+collected|cost\s+of\s+such\s+examination|"
    r"(?:spent|spending).{0,100}(?:net\s+sales|research\s+and\s+development)|"
    r"royalty\s+on\s+(?:one\s+hundred\s+percent|100\s*%)"
    r"(?:\s*\(\s*100\s*%\s*\))?\s+of|"
    r"(?:percent|%)\s+of\s+all\s+royalties"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)
_NON_ROYALTY_RATE_ASSERTION = re.compile(
    r"(?:"
    r"amount\s+equal\s+to\s+\d+(?:\.\d+)?\s*%\s+of\s+the\s+forecast\s+royalty|"
    r"responsible\s+for\s+\d+(?:\.\d+)?\s*%\s+of\s+such\s+royalties|"
    r"additional\s+royalty\s+equal\s+to\s+\d+(?:\.\d+)?\s*%\s+of\s+the\s+royalty|"
    r"retain\s+\d+(?:\.\d+)?\s*%\s+of\s+(?:any\s+such\s+)?"
    r"(?:sale\s+proceeds|deferred\s+compensation)|"
    r"net\s+sales.{0,180}deemed\s+to\s+be\s+equal\s+to\s+"
    r"\d+(?:\.\d+)?\s*%\s+of\s+the\s+net\s+sales|"
    r"(?:ownership\s+interests?|voting\s+power|net\s+assets).{0,100}"
    r"\d+(?:\.\d+)?\s*%|"
    r"(?:reduction\s+shall.{0,80}exceed|royalt(?:y|ies)\s+shall\s+be\s+reduced\s+by)"
    r".{0,80}\d+(?:\.\d+)?\s*%|"
    r"recovered.{0,80}\d+(?:\.\d+)?\s*%\s+of\s+"
    r"(?:all\s+)?research\s+and\s+development\s+funding|"
    r"defray\s+the\s+expenses.{0,100}\d+(?:\.\d+)?\s*%\s+of\s+royalties|"
    r"example:.{0,300}\d+(?:\.\d+)?\s*%|"
    r"total\s+royalty\s+burden.{0,180}\d+(?:\.\d+)?\s*%"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_PAYMENT_CONTEXT = re.compile(
    r"\b(?:pay(?:able|ment|ments|ing)?|fee|consideration|cash amount|amount due)\b",
    re.IGNORECASE,
)
_NONPAYMENT_AMOUNT_CONTEXT = re.compile(
    r"\b(?:"
    r"net sales|gross sales|revenue|sales threshold|par value|per share|"
    r"at the rate|per year|full[ -]?time staff|research support|"
    r"purchase price|market potential|equity financing|investor commitments?|"
    r"minimum amount|indemnification|per batch"
    r")\b",
    re.IGNORECASE,
)
_UPFRONT_AGGREGATE_CONTEXT = re.compile(
    r"\b(?:"
    r"research(?:\s+and\s+development)?\s+funding|equity\s+investment|"
    r"valued\s+(?:at|up\s+to)|total\s+(?:partnership|transaction)\s+value"
    r"|milestone\s+payments?"
    r")\b",
    re.IGNORECASE,
)
_UPFRONT_CONTINGENT_CONTEXT = re.compile(
    r"\b(?:upon|following|after|within)\b.{0,70}"
    r"\b(?:first\s+)?(?:IND|NDA|BLA|regulatory|clinical|approval)\b",
    re.IGNORECASE | re.DOTALL,
)
_UPFRONT_EQUITY_CONTEXT = re.compile(
    r"\bup[ -]?front\s+equity\s+investment\b",
    re.IGNORECASE,
)
_UPFRONT_ALLOCATION_CONTEXT = re.compile(
    r"\b(?:"
    r"committee\s+reimbursement\s+amount|escrow\s+contribution\s+amount|"
    r"payment\s+agent|distribut(?:e|ion)\s+(?:of\s+)?the\s+upfront\s+payment"
    r"|(?<!non-)(?<!non )creditable\s+against\s+future.{0,80}payments?|"
    r"cost\s+of\s+such\s+license|deducted\s+from\s+(?:the\s+)?purchase\s+price"
    r")\b",
    re.IGNORECASE,
)
_THIRD_PARTY_LICENSE_COST_CAP = re.compile(
    r"\b(?:third[ -]?party.{0,100}license|cost\s+of\s+such\s+license)\b"
    r".{0,500}\bup[ -]?front\s+payments?\b"
    r".{0,500}\b(?:maximum|deducted)\b",
    re.IGNORECASE | re.DOTALL,
)
_UPFRONT_PACKAGE_TOTAL = re.compile(
    r"^.{0,100}\b(?:in\s+total|inclusive\s+of|"
    r"in\s+aggregate\s+payments?,?\s+including)\b"
    r".{0,220}\bup[ -]?front\b.{0,220}\bmilestone",
    re.IGNORECASE | re.DOTALL,
)
_HYPOTHETICAL_UPFRONT = re.compile(
    r"\b(?:if,?\s+for\s+example|for\s+example)\b.{0,800}"
    r"\b(?:third[ -]?part(?:y|ies)|up[ -]?front(?:\s+fee|\s+payment)?)\b|"
    r"\b(?:we\s+assume|our\s+assumption|assume\s+such\s+terms)\b.{0,500}"
    r"\bup[ -]?front\b",
    re.IGNORECASE | re.DOTALL,
)
_OTHER_LICENSE_UPFRONT_REFERENCE = re.compile(
    r"\b(?:grant|grants|granted)\s+to\s+(?:any\s+)?other\s+part(?:y|ies)\b"
    r".{0,500}\b(?:initial\s+license\s+fee|up[ -]?front)\b|"
    r"\bterms\s+of\s+(?:any\s+)?other\s+(?:agreement|license)\b"
    r".{0,500}\b(?:initial\s+license\s+fee|up[ -]?front)\b",
    re.IGNORECASE | re.DOTALL,
)
_MILESTONE_AGGREGATE_CONTEXT = re.compile(
    r"\b(?:"
    r"reimburse\w*|reimburs\w*|"
    r"research(?:\s+and\s+development)?\s+funding|equity\s+investment|"
    r"common\s+stock|marketing\s+support\s+fee|progress\s+payment|"
    r"initial\s+payment|license\s+execution|restructur\w*|settlement"
    r"|amortization\s+expense|cash\s+reserves?|escrow\s+amount|"
    r"\badvance(?:d|s)?\b|partially\s+fund|"
    r"research(?:\s+and\s+development|\s*&\s*development)\s+efforts?"
    r"|late[ -]?delivery|creditable\s+against.{0,40}milestone|"
    r"change\s+of\s+control\s+plan|eligible\s+employees?|"
    r"initial\s+purchase\s+price|licensing\s+fees?|warrants?|repurchase|"
    r"principal\s+amount|market\s+potential|up[ -]?fronts?\s+and\s+milestones?|"
    r"annual\s+net\s+sales|equity\s+financing|research\s+plan|"
    r"additional\s+batches?|per\s+batch"
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
_NUMBERED_MILESTONE_ROW = re.compile(
    r"\bmilestone\s+(?:\d+|[ivxlcdm]+)\b",
    re.IGNORECASE,
)
_FIXED_FEE_MILESTONE_SCHEDULE = re.compile(
    r"\bfixed[ -]?fee\b.{0,500}\b(?:based\s+on|paid\s+per)\b"
    r".{0,120}\bmilestones?\b|"
    r"\bmilestones?\b.{0,160}\bfixed[ -]?fee\b",
    re.IGNORECASE | re.DOTALL,
)
_MIXED_MILESTONE_AGGREGATE = re.compile(
    r"\b(?:up\s+to|total(?:ing)?|aggregate)\b.{0,120}"
    r"\bin\s+equity\s+investments?\s*,\s*milestones?\s+and\s+"
    r"other\s+(?:precommercial\s+)?payments?\b|"
    r"\breceive\b.{0,80}\bapproximately\s+\$?\s*\d[\d,.]*\s*"
    r"(?:million|billion|mn|bn|m|b)?\s+in\s+milestones?\s*,\s*"
    r"development\s+payments?\s+and\s+equity\s+investments?\b",
    re.IGNORECASE | re.DOTALL,
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
    if re.search(
        r"\b(?:aggregate\s+amount\s+)?(?:paid|due|owing).{0,500}"
        r"\broyalt(?:y|ies)\b.{0,500}\bcost\s+of\s+manufacture\b"
        r".{0,500}\bexceed\b.{0,120}\bpercent\b.{0,120}\bnet\s+sales\b"
        r".{0,500}\bshare\b.{0,160}\bexcess\b",
        excerpt,
        re.IGNORECASE | re.DOTALL,
    ):
        return []
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
        sublicense_allocations = list(re.finditer(
            r"\bshare\s+of\s+sublicens\w*\s+income\b.{0,260}?"
            r"\d+(?:\.\d+)?\s*%\s+[A-Za-z][A-Za-z0-9_-]*\s*,\s*"
            r"\d+(?:\.\d+)?\s*%\s+[A-Za-z][A-Za-z0-9_-]*",
            paragraph,
            re.IGNORECASE | re.DOTALL,
        ))
        if any(
            match.start() <= paragraph_position < match.end()
            for match in sublicense_allocations
        ):
            continue
        if (
            re.search(r"\bstockholders?\b.{0,120}$", before, re.IGNORECASE)
            and re.match(r"\s*\)?\s*threshold\b", after, re.IGNORECASE)
        ):
            continue
        if re.match(
            r"\s*\)?\s*(?:of\s+)?(?:the\s+)?(?:then[ -])?outstanding\s+"
            r"(?:capital\s+stock|voting\s+stock|equity)",
            after,
            re.IGNORECASE,
        ):
            continue
        directly_linked = bool(
            re.search(r"royalt(?:y|ies)\b.{0,100}$", before, re.IGNORECASE)
            or re.match(r"\s*royalt(?:y|ies)\b", after, re.IGNORECASE)
            or re.match(
                r"\s*\)?\s*(?:for|of|on|based\s+on)?\s*(?:the\s+)?"
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
        assertion_start = max(0, relative_start - 150)
        assertion_end = min(len(excerpt), relative_end + 150)
        direct_royalty_of = re.search(
            r"\ba\s+royalty\s+of\s+"
            r"(?:[a-z]+(?:[ -][a-z]+){0,5}\s*\()?\s*$",
            before,
            re.IGNORECASE,
        )
        false_rate_before = re.search(
                r"\b(?:retain|responsible\s+for|reduced\s+by|"
                r"diminish(?:ed|es|ing)?\s+by|"
                r"reduction.{0,100}exceed|"
                r"amount\s+less\s+than|additional\s+royalty\s+equal\s+to|"
                r"deemed\s+to\s+be\s+equal\s+to|defray.{0,100}|"
                r"recover(?:ed)?).{0,100}"
                r"(?:percent\s*\()?\s*$",
                before,
                re.IGNORECASE | re.DOTALL,
            )
        false_rate_after = re.match(
                r"\s*\)?\s*(?:of\s+(?:any\s+such\s+|any\s+)?"
                r"(?:(?:net\s+)?sale\s+proceeds|"
                r"deferred\s+compensation|royalties|the\s+royalty|all\s+"
                r"research\s+and\s+development\s+funding|the\s+amounts\s+"
                r"described|the\s+net\s+sales|the\s+corresponding\s+"
                r"milestone\s+payment|u\.?s\.?\s+profits?|the\s+asp|"
                r"(?:the\s+)?remaining\s+proceeds|"
                r"(?:the\s+)?operating\s+income|"
                r"(?:aggregate\s+product\s+)?net\s+sales|"
                r"(?:the\s+)?(?:patent\s+)?royalty\s+rates?|"
                r"(?:the\s+)?rate\s+otherwise\s+applicable|"
                r"(?:the\s+)?amounts?\s+payable\s+to\s+(?:a\s+)?"
                r"third\s+part(?:y|ies))|for\s+net\s+sales|"
                r"on\s+a\s+country|"
                r"by.{0,100}(?:net\s+)?sale\s+proceeds)",
                after,
                re.IGNORECASE,
            )
        position_specific_false_rate = bool(
            (false_rate_before and false_rate_after)
            or re.search(
                r"\btotal\s+royalty\s+payments?.{0,100}"
                r"(?:exceed|threshold).{0,30}$|"
                r"\bdiminution\s+of\s+(?:unit\s+)?sales\s+volumes?"
                r".{0,100}(?:equal\s+to|reduced\s+by).{0,50}$|"
                r"\bunreduced\s+royalty\s+rates?.{0,120}"
                r"(?:apply\s+to\s+the\s+remaining|remaining).{0,30}$",
                before,
                re.IGNORECASE | re.DOTALL,
            )
            or re.match(
                r"\s*\)?\s*of\s+u\.?s\.?\s+profits?\b",
                after,
                re.IGNORECASE,
            )
            or re.match(
                r"\s*\)?\s*of\s+(?:the\s+)?(?:operating\s+income|"
                r"remaining\s+proceeds)\b",
                after,
                re.IGNORECASE,
            )
            or (
                re.search(
                    r"\bonly(?:\s+[a-z]+){0,4}\s+percent\s*\(\s*$",
                    before,
                    re.IGNORECASE,
                )
                and re.match(
                    r"\s*\)?\s*of\s+(?:the\s+)?corresponding\s+"
                    r"milestone\s+payment",
                    after,
                    re.IGNORECASE,
                )
            )
            or (
                re.search(
                    r"\b(?:pay|pays|paying)\s+(?:one\s+hundred\s+percent\s*"
                    r"\(\s*|100\s*%\s*)$",
                    before,
                    re.IGNORECASE,
                )
                and re.match(
                    r"\s*\)?\s*of\s+(?:the\s+)?amounts?\s+payable\s+to\s+"
                    r"(?:(?:a|the|such)\s+)?third\s+part(?:y|ies)",
                    after,
                    re.IGNORECASE,
                )
            )
            or (
                re.search(
                    r"\broyalty\s+rate\s+shall\s+be.{0,30}$",
                    before,
                    re.IGNORECASE | re.DOTALL,
                )
                and re.match(
                    r"\s*\)?\s*of\s+(?:the\s+)?rate\s+otherwise\s+"
                    r"applicable",
                    after,
                    re.IGNORECASE,
                )
            )
            or re.match(
                r"\s*\)?\s*of\s+the\s+asp.{0,100}"
                r"variable\s+selling\s+costs?",
                after,
                re.IGNORECASE | re.DOTALL,
            )
            or (
                re.search(
                    r"\btotal\s+royalty\s+payments?.{0,100}"
                    r"(?:exceed|threshold).{0,30}$|"
                    r"\b(?:unit\s+)?sales\s+volumes?.{0,120}"
                    r"(?:reduced|diminution).{0,80}$|"
                    r"\b(?:reduced|unreduced)\s+royalty\s+rates?.{0,120}"
                    r"(?:apply\s+to|remaining).{0,80}$|"
                    r"\baggregate\s+royalty\s+rate.{0,100}less\s+than.{0,30}$|"
                    r"\bassuming.{0,140}receiv(?:e|ing).{0,60}"
                    r"royalty\s+rate\s+of.{0,30}$|"
                    r"\b(?:pay|pays|paying)\s+(?:one\s+hundred\s+percent|"
                    r"100\s*%).{0,40}$",
                    before,
                    re.IGNORECASE | re.DOTALL,
                )
                and false_rate_after
            )
            or (
                re.search(
                    r"\breceive\b.{0,100}(?:percent\s*\()?\s*$",
                    before,
                    re.IGNORECASE | re.DOTALL,
                )
                and re.match(
                    r"\s*\)?\s*by.{0,100}(?:net\s+)?sale\s+proceeds",
                    after,
                    re.IGNORECASE | re.DOTALL,
                )
            )
            or re.search(
                r"\bamount\s+less\s+than\s*$",
                before,
                re.IGNORECASE,
            )
            or (
                re.search(
                    r"\bshare\s+of\s+sublicens\w*\s+income\b.{0,160}$",
                    before,
                    re.IGNORECASE | re.DOTALL,
                )
                and re.match(
                    r"\s+[A-Za-z][A-Za-z0-9_-]*\s*,\s*\d+(?:\.\d+)?\s*%",
                    after,
                    re.IGNORECASE,
                )
            )
        )
        if (
            direct_royalty_of is None
            and (
                position_specific_false_rate
                or _NON_ROYALTY_RATE_ASSERTION.search(
                    excerpt[assertion_start:assertion_end]
                )
            )
        ):
            continue
        immediate_royalty_rate = re.search(
            r"\broyalty\s+rate\s+would\s+be\s*$",
            before,
            re.IGNORECASE,
        )
        example_prefix = excerpt[max(0, relative_start - 800):relative_start]
        example_matches = list(re.finditer(
            r"\bfor\s+example\b",
            example_prefix,
            re.IGNORECASE,
        ))
        same_rate_before_example = False
        if example_matches:
            example_absolute_start = (
                max(0, relative_start - 800) + example_matches[-1].start()
            )
            same_rate_before_example = any(
                math.isclose(
                    _number(earlier.group("value")),
                    value["value_pct"],
                    rel_tol=1e-12,
                    abs_tol=1e-9,
                )
                for earlier in _RATE_RE.finditer(
                    excerpt[:example_absolute_start]
                )
            )
        if (
            example_matches
            and not same_rate_before_example
            and immediate_royalty_rate is None
        ):
            continue
        if re.match(
            r"\s*\)?\s*(?:percent\s+)?of\s+"
            r"(?:(?:any|the|such)\s+)?(?:funds|sums|"
            r"(?:third[ -]?party\s+license\s+)?payments|royalt(?:y|ies)|"
            r"royalty\s+income)\b",
            after,
            re.IGNORECASE,
        ):
            continue
        if re.match(
            r"\s*\)?\s*(?:percent\s+)?of\s+(?:the\s+)?"
            r"amounts?\s+(?:otherwise\s+payable|due)\b",
            after,
            re.IGNORECASE,
        ):
            continue
        if re.search(
            r"\badditional\s+earned\s+royalties\b.{0,120}"
            r"(?:equal\s+to|greater\s+than).{0,50}$|"
            r"\badditional\s+royalties\s+owed\b.{0,120}"
            r"vary\s+from\s+royalties\s+paid\s+by.{0,30}$",
            before,
            re.IGNORECASE | re.DOTALL,
        ):
            continue
        cost_cap_before = excerpt[max(0, relative_start - 1400):relative_start]
        if (
            re.search(
                r"\b(?:fully\s+allocated\s+cost|"
                r"costs?\s+(?:incurred\s+)?in\s+manufactur\w*)\b"
                r".{0,1100}\b(?:exceed|exceeds|exceeded|in\s+excess\s+of)\b"
                r".{0,500}$",
                cost_cap_before,
                re.IGNORECASE | re.DOTALL,
            )
            and re.match(
                r"\s*\)?\s*of\s+(?:the\s+)?(?:u\.?s\.?\s+partnership'?s\s+|"
                r"relevant\s+jv\s+entity'?s\s+)?net\s+sales\b",
                after,
                re.IGNORECASE,
            )
        ):
            continue
        threshold_before = excerpt[max(0, relative_start - 700):relative_start]
        threshold_scope = excerpt[
            max(0, relative_start - 700):min(len(excerpt), relative_end + 700)
        ]
        if (
            re.match(
                r"\s*\)?\s*of\s+(?:the\s+)?net\s+sales\b",
                after,
                re.IGNORECASE,
            )
            and re.search(
                r"\b(?:one\s+hundred\s+percent|100\s*%)\b.{0,80}"
                r"\bnet\s+sales\b.{0,120}\bused\s+to\s+determine\s+"
                r"(?:the\s+)?royalt(?:y|ies)\b",
                threshold_scope,
                re.IGNORECASE | re.DOTALL,
            )
        ):
            continue
        if (
            re.search(
                r"\b(?:cost\s+of\s+(?:goods|manufacture)|"
                r"aggregate\s+amount\s+(?:paid|due|owing).{0,420}"
                r"royalt(?:y|ies)|sales\s+by\s+third\s+parties|"
                r"sales\s+of\s+(?:a\s+)?generic\s+product|"
                r"sum\s+of\s+.{0,160}royalty\s+payments?)\b"
                r".{0,500}\b(?:greater\s+than|exceed(?:s|ed|ing)?)\b"
                r".{0,80}$",
                threshold_before,
                re.IGNORECASE | re.DOTALL,
            )
            and re.match(
                r"\s*\)?\s*of\s+(?:the\s+)?net\s+sales\b",
                after,
                re.IGNORECASE,
            )
            and re.search(
                r"\b(?:royalt(?:y|ies)|royalty\s+rate)\b.{0,500}"
                r"\b(?:reduc\w*|offset\w*)\b|"
                r"\b(?:reduc\w*|offset\w*)\b.{0,500}\broyalt(?:y|ies)\b|"
                r"\bshare\b.{0,120}\bexcess\b",
                threshold_scope,
                re.IGNORECASE | re.DOTALL,
            )
        ):
            continue
        royalty_distribution_prefix = excerpt[
            max(0, relative_start - 400):relative_start
        ]
        royalty_allocation_scope = excerpt[
            max(0, relative_start - 800):min(len(excerpt), relative_end + 800)
        ]
        if (
            re.search(
                r"\broyalty\s+income\b.{0,300}\bdistributed\s+as\s+follows\b",
                royalty_distribution_prefix,
                re.IGNORECASE | re.DOTALL,
            )
            and re.match(r"\s*\)?\s*to\b", after, re.IGNORECASE)
        ):
            continue
        if re.search(
            r"\broyalty\s+income\b.{0,700}\bdistribut\w*\b",
            royalty_allocation_scope,
            re.IGNORECASE | re.DOTALL,
        ):
            continue
        if (
            re.search(
                r"\b(?:sums?|funds?)\s+recover\w*\b|"
                r"\binfringement\s+recovery\b",
                royalty_allocation_scope,
                re.IGNORECASE,
            )
            and re.search(
                r"\b(?:distribut\w*|belong)\b",
                royalty_allocation_scope,
                re.IGNORECASE,
            )
        ):
            continue
        if (
            _NON_ROYALTY_RATE_CONTEXT.search(excerpt[local_start:local_end])
            and immediate_royalty_rate is None
            and direct_royalty_of is None
        ):
            continue
        values.append(value)
    return values


def _monetary_values(excerpt: str, absolute_start: int) -> list[dict]:
    values = []
    seen_spans: list[tuple[int, int]] = []
    for pattern in (
        _QUALIFIED_DOLLAR_AMOUNT_RE,
        _SYMBOL_AMOUNT_RE,
        _CODE_AMOUNT_RE,
    ):
        for match in pattern.finditer(excerpt):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in seen_spans):
                continue
            seen_spans.append(span)
            raw_currency = match.group("currency")
            normalized_currency = raw_currency.replace(".", "").upper()
            values.append({
                "amount_millions": _amount_millions(
                    match.group("value"),
                    match.group("unit"),
                ),
                "currency": _QUALIFIED_DOLLAR_CODES.get(
                    normalized_currency,
                    _CURRENCY_CODES.get(raw_currency, normalized_currency),
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
    if (
        clause_type == "milestone_payment"
        and (
            _FIXED_FEE_MILESTONE_SCHEDULE.search(excerpt)
            or _MIXED_MILESTONE_AGGREGATE.search(excerpt)
        )
    ):
        return []
    if clause_type == "upfront_payment" and (
        re.search(
            r"\breceives?\s+payment\s+commitments?\b.{0,500}"
            r"\bat\s+least\b.{0,300}\bup[ -]?front\s+payments?\b",
            excerpt,
            re.IGNORECASE | re.DOTALL,
        )
        or re.search(
            r"\bmay\s+retain\b.{0,250}\bup[ -]?front\b.{0,250}"
            r"\bwith\s*out\s+obligation\b",
            excerpt,
            re.IGNORECASE | re.DOTALL,
        )
    ):
        return []
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
        previous_value = max(
            (
                other
                for other in monetary_values
                if other["char_end"] <= value["char_start"]
            ),
            key=lambda other: other["char_end"],
            default=None,
        )
        if previous_value is not None:
            previous_end = previous_value["char_end"] - absolute_start
            bracket_prefix = excerpt[previous_end:relative_start]
            bracket_suffix = excerpt[relative_end:relative_end + 4]
            if (
                previous_value["currency"] != value["currency"]
                and re.fullmatch(r"\s*\[\s*", bracket_prefix)
                and re.match(r"\s*\]", bracket_suffix)
            ):
                continue
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
            numbered_milestone_row = (
                clause_type == "milestone_payment"
                and anchor_distance <= 80
                and _NUMBERED_MILESTONE_ROW.search(
                    excerpt[
                        max(0, closest_anchor.start() - 30):
                        min(len(excerpt), relative_end + 30)
                    ]
                )
            )
            if not numbered_milestone_row:
                continue
            payment_distance = anchor_distance
        value_before = excerpt[max(0, relative_start - 180):relative_start]
        value_after_short = excerpt[relative_end:relative_end + 180]
        if clause_type == "milestone_payment":
            anchor_prefix = excerpt[
                max(0, closest_anchor.start() - 50):closest_anchor.start()
            ]
            if re.search(
                r"\b(?:excluding(?:\s+contingent)?|exclude|excepting|"
                r"other\s+than)\s*$",
                anchor_prefix,
                re.IGNORECASE,
            ):
                continue
            milestone_before = excerpt[
                max(0, relative_start - 650):relative_start
            ]
            milestone_after = excerpt[
                relative_end:min(len(excerpt), relative_end + 260)
            ]
            maintenance_matches = list(re.finditer(
                r"\blicense\s+maintenance\s+(?:fees?|royalt(?:y|ies))\b",
                milestone_before,
                re.IGNORECASE,
            ))
            if maintenance_matches:
                after_maintenance = milestone_before[
                    maintenance_matches[-1].end():
                ]
                substantive_milestone = re.search(
                    r"\bmilestone\s+payments?\b",
                    after_maintenance,
                    re.IGNORECASE,
                )
                if (
                    substantive_milestone is None
                    or re.search(
                        r"\bshall\s+not\s+be\s+credited\s+against\s+"
                        r"milestone\s+payments?\b",
                        after_maintenance,
                        re.IGNORECASE,
                    )
                ):
                    continue
            if re.search(
                r"\bmilestone\s+payments?\s+made\s+in\s+excess\s+of\b"
                r".{0,80}$",
                milestone_before,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            if (
                re.search(
                    r"\b(?:the\s+)?loan\b.{0,120}$|"
                    r"\bpay\b.{0,80}$",
                    value_before,
                    re.IGNORECASE | re.DOTALL,
                )
                and re.match(
                    r"\s*\)?\s*\(\s*the\s+[\"“']Loan[\"”']\s*\)",
                    milestone_after,
                    re.IGNORECASE | re.DOTALL,
                )
            ):
                continue
            if re.search(
                r"\b(?:first|second|third|final)\s+installment\s+"
                r"(?:of\s+)?(?:the\s+)?license\s+fee\b.{0,120}$|"
                r"\b(?:first|second|third|final)\s+installment\s+"
                r"license\s+fee\b.{0,120}$",
                milestone_before,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            cancellation_match = re.search(
                r"\b(?:cancelled|canceled|forfeited)\b",
                milestone_after,
                re.IGNORECASE | re.DOTALL,
            )
            if (
                cancellation_match is not None
                and not _monetary_values(
                    milestone_after[:cancellation_match.end()], 0
                )
            ):
                continue
            if re.search(
                r"\b(?:by\s+way\s+of\s+example\s+only|for\s+example)\b"
                r".{0,600}$",
                milestone_before,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            if re.search(
                r"\bshall\s+not\s+be\s+required\s+to\s+pay\b.{0,300}$|"
                r"\bas\s+consideration\s+for\b.{0,220}\bassignment\b"
                r".{0,180}\bshall\s+pay\b.{0,100}$",
                milestone_before,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            aggregate_payment_matches = list(re.finditer(
                r"\bpayments?\b.{0,120}\b(?:in\s+the\s+)?aggregate\s+"
                r"amount\s+of\b",
                milestone_before,
                re.IGNORECASE | re.DOTALL,
            ))
            if aggregate_payment_matches:
                aggregate_match = aggregate_payment_matches[-1]
                if not _monetary_values(
                    milestone_before[aggregate_match.end():], 0
                ):
                    continue
            if re.search(
                r"\b(?:continuing\s+)?obligations?\b.{0,260}"
                r"\bmilestone(?:\s+or\s+similar)?\s+payments?\b"
                r".{0,120}\bin\s+excess\s+of\b.{0,60}$",
                milestone_before,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            if re.match(
                r"\s+in\s*(?:\n\s*)?(?:confidential\b)?\s*$",
                milestone_after,
                re.IGNORECASE,
            ):
                continue
            trigger_matches = [
                match
                for pattern in (
                    r"\b(?:milestone\s+)?payments?\b.{0,220}\breceived\b"
                    r".{0,100}\bin\s+excess\s+of\b",
                    r"\bnet\s+sales\b.{0,260}\b(?:at\s+least|"
                    r"reach(?:es|ed)?|exceed(?:s|ed|ing)?)\b",
                    r"\brevenues?\b.{0,450}\bexceed(?:s|ed|ing)?\b"
                    r".{0,180}\b(?:amount\s+)?(?:equal\s+to\s+or\s+)?"
                    r"greater\s+than\b",
                )
                for match in re.finditer(
                    pattern,
                    milestone_before,
                    re.IGNORECASE | re.DOTALL,
                )
            ]
            if trigger_matches:
                latest_trigger = max(trigger_matches, key=lambda match: match.end())
                between_trigger_and_value = milestone_before[latest_trigger.end():]
                if (
                    len(between_trigger_and_value) <= 180
                    and not _SENTENCE_BOUNDARY.search(between_trigger_and_value)
                    and not _monetary_values(between_trigger_and_value, 0)
                ):
                    continue
        if re.search(
            r"\bminimum\s+amount\s+of\b.{0,100}$",
            value_before,
            re.IGNORECASE | re.DOTALL,
        ):
            continue
        direct_historical_payment = re.search(
            r"\b(?:has|have|had)\s+paid\b.{0,160}$",
            value_before,
            re.IGNORECASE | re.DOTALL,
        )
        nonpayment_follows_value = _NONPAYMENT_AMOUNT_CONTEXT.search(
            value_after_short
        )
        direct_milestone_label = (
            clause_type == "milestone_payment"
            and bool(re.match(
                r"\s+milestone(?:\s+payment)?\b",
                value_after_short,
                re.IGNORECASE,
            ))
        )
        direct_upfront_label = (
            clause_type == "upfront_payment"
            and closest_anchor.end() <= relative_start
            and relative_start - closest_anchor.end() <= 60
        )
        if (
            nonpayment_distance is not None
            and nonpayment_distance < payment_distance
            and not direct_milestone_label
            and not direct_upfront_label
            and not (
                direct_historical_payment is not None
                and nonpayment_follows_value is not None
            )
        ):
            continue
        if clause_type == "upfront_payment":
            value_after = excerpt[
                relative_end:min(len(excerpt), relative_end + 650)
            ]
            following_value_distance = min(
                (
                    other["char_start"] - value["char_end"]
                    for other in monetary_values
                    if other["char_start"] >= value["char_end"]
                ),
                default=len(value_after),
            )
            value_after_current = value_after[:max(0, following_value_distance)]
            value_scope = excerpt[
                max(0, relative_start - 500):
                min(len(excerpt), relative_end + 650)
            ]
            if re.match(
                r"\s*(?:million|billion|thousand|mn|bn|m|b|k)?\s+in\s+"
                r"(?:pre[ -]?commercialization\s+)?milestones?\b",
                value_after_current,
                re.IGNORECASE,
            ):
                continue
            if re.search(
                r"\badditional\s+license\s+payments?\s+of\s*$",
                value_before,
                re.IGNORECASE,
            ):
                continue
            if re.search(
                r"\bpre[ -]?commercialization\s+payments?\s+of\s+up\s+to\s*$",
                value_before,
                re.IGNORECASE,
            ):
                continue
            if re.search(
                r"\blicense\s+maintenance\s+(?:fees?|royalt(?:y|ies))\b"
                r".{0,100}$",
                value_before,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            if re.search(
                r"\bdenominator\s+shall\s+be\b.{0,260}"
                r"\baggregate\s+up[ -]?front\s+payments?\s+and\s+"
                r"periodic\s+payments?\b|"
                r"\baggregate\s+up[ -]?front\s+payments?\s+and\s+"
                r"periodic\s+payments?\b.{0,300}\bdenominator\b",
                value_scope,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            if _OTHER_LICENSE_UPFRONT_REFERENCE.search(value_scope):
                continue
            if re.search(
                r"\binvest\s*$",
                value_before,
                re.IGNORECASE,
            ) and re.match(
                r".{0,100}\b(?:by\s+)?purchas(?:e|ing)\b.{0,100}\bshares?\b",
                value_after,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            if re.search(
                r"\b(?:purchase|acquire)\s*$",
                value_before,
                re.IGNORECASE,
            ) and re.match(
                r".{0,80}\b(?:its\s+)?(?:common|preferred)\s+stock\b|"
                r".{0,80}\bshares?\b",
                value_after,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            contingent_after_match = re.match(
                r".{0,160}?\b(?:the\s+)?(?:first|second|contingent\s+cash)\s+"
                r"contingent\s+payments?\b",
                value_after,
                re.IGNORECASE | re.DOTALL,
            )
            if re.search(
                r"\bcontingent\s+(?:cash\s+)?payments?\b.{0,120}$",
                value_before,
                re.IGNORECASE | re.DOTALL,
            ) or (
                contingent_after_match is not None
                and not _monetary_values(
                    value_after[:contingent_after_match.end()], 0
                )
            ):
                continue
            if re.match(
                r".{0,100}\bincluding\b.{0,300}\bup[ -]?front\b"
                r".{0,300}\bmilestone",
                value_after,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            if re.search(
                r"\b(?:term\s+loan\s+commitment|credit\s+extensions?)\b",
                value_scope,
                re.IGNORECASE,
            ):
                continue
            if re.search(
                r"\b(?:loans?\s+for\s+(?:an\s+)?aggregate\s+of|"
                r"collaboration\s+expenses\s+in\s+an\s+amount\s+equal\s+to|"
                r"collaboration\s+expenses.{0,100}\(\s*|"
                r"equal\s+to\s+or\s+in\s+excess\s+of|"
                r"amounts?\s+in\s+excess\s+of)\s*$",
                value_before,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            if (
                re.search(
                    r"\binclusive\s+of\s*$",
                    value_before,
                    re.IGNORECASE,
                )
                and re.match(
                    r"\s+in\s+an?\s+up[ -]?front\s+fee\b",
                    value_after,
                    re.IGNORECASE,
                )
            ):
                continue
            if (
                re.search(
                    r"\b\d+(?:\.\d+)?\s*%\s+of\s+the\s+first\s*$",
                    value_before,
                    re.IGNORECASE,
                )
                and re.match(
                    r"\s+of\s+any\s+up[ -]?front\b",
                    value_after,
                    re.IGNORECASE,
                )
            ):
                continue
            if re.search(
                r"\bamount\s+equal\s+to\s+\d+(?:\.\d+)?\s*%\s+of\s+"
                r"the\s+first\s+\$?\s*\d[\d,]*(?:\.\d+)?\s*"
                r"(?:million|billion|thousand|mn|bn|m|b|k)?\s+of\s+any\s+"
                r"up[ -]?front\b",
                value_scope,
                re.IGNORECASE,
            ):
                continue
            if _UPFRONT_PACKAGE_TOTAL.search(value_after):
                continue
            if re.search(
                r"\bventure\s+debt\s+financing\b",
                value_scope,
                re.IGNORECASE,
            ):
                continue
            if re.match(
                r".{0,120}\b(?<!non-)(?<!non )creditable\s+against\s+future\b",
                value_after,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            if _HYPOTHETICAL_UPFRONT.search(value_scope):
                continue
            if re.search(
                r"\blicense\s+maintenance\s+fee\b",
                value_after_current[:180],
                re.IGNORECASE,
            ):
                continue
            if re.search(
                r"\b(?:technology\s+transfer|field\s+expansion)\s+payments?\b",
                value_after_current[:180],
                re.IGNORECASE,
            ):
                continue
            if re.search(
                r"\bsecond\s+payment\s*\([^)]*$|"
                r"\ballocat(?:e|ion)\b.{0,100}$|"
                r"\b(?:test\s+report|method\s+validation\s+report)\b.{0,120}$",
                value_before,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            if re.match(
                r".{0,100}\bupon\s+the\s+successful\s+achievement\b",
                value_after_current[:180],
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            immediate_upfront_label = re.match(
                r".{0,100}\bup[ -]?front\s+payment\b",
                value_after,
                re.IGNORECASE | re.DOTALL,
            )
            if re.search(
                r"\b(?:human\s+)?safety\s+data\s+payment\b|"
                r"\breceiving\s+human\s+safety\s+data\b",
                value_after[:220],
                re.IGNORECASE,
            ) and immediate_upfront_label is None:
                continue
            following_upfront_anchor = min(
                (
                    match
                    for match in anchors
                    if match.start() >= relative_end
                ),
                key=lambda match: match.start(),
                default=None,
            )
            following_milestone_anchor = min(
                (
                    match
                    for match in competing_anchors
                    if match.start() >= relative_end
                ),
                key=lambda match: match.start(),
                default=None,
            )
            # In constructions such as "$55m up-front and up to $6m in
            # milestone payments", proximity alone assigns the second value
            # to the earlier up-front anchor. Prefer the first following
            # payment label when it is close enough to govern the value.
            if (
                following_milestone_anchor is not None
                and following_milestone_anchor.start() - relative_end <= 100
                and anchor_distance > 15
                and not re.search(
                    r"\bup[ -]?front\s+payment\s+of\s*$",
                    excerpt[max(0, relative_start - 100):relative_start],
                    re.IGNORECASE,
                )
                and not _SENTENCE_BOUNDARY.search(
                    excerpt[relative_end:following_milestone_anchor.start()]
                )
                and (
                    following_upfront_anchor is None
                    or following_milestone_anchor.start()
                    < following_upfront_anchor.start()
                )
                and any(
                    other["char_end"] - absolute_start <= relative_start
                    and min(
                        abs(
                            (other["char_start"] + other["char_end"])
                            // 2 - absolute_start - closest_anchor.start()
                        ),
                        abs(
                            (other["char_start"] + other["char_end"])
                            // 2 - absolute_start - closest_anchor.end()
                        ),
                    ) <= 100
                    for other in monetary_values
                    if other is not value
                )
            ):
                continue
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
            allocation_scope = excerpt[
                max(0, min(closest_anchor.start(), relative_start) - 600):
                min(len(excerpt), max(closest_anchor.end(), relative_end) + 600)
            ]
            if _THIRD_PARTY_LICENSE_COST_CAP.search(allocation_scope):
                continue
            previous_end = max(
                (
                    other["char_end"] - absolute_start
                    for other in monetary_values
                    if other["char_end"] - absolute_start <= relative_start
                ),
                default=max(0, relative_start - 160),
            )
            next_start = min(
                (
                    other["char_start"] - absolute_start
                    for other in monetary_values
                    if other["char_start"] - absolute_start >= relative_end
                ),
                default=min(len(excerpt), relative_end + 160),
            )
            contingent_context = excerpt[
                max(previous_end, relative_start - 160):
                min(next_start, relative_end + 160)
            ]
            if (
                _UPFRONT_CONTINGENT_CONTEXT.search(contingent_context)
                and "license issue fee" not in closest_anchor.group(0).lower()
            ):
                continue
        if clause_type == "milestone_payment":
            table_scope = excerpt[
                max(0, relative_start - 600):
                min(len(excerpt), relative_end + 600)
            ]
            if re.search(
                r"\b(?:deduction|credit|offset)\b.{0,80}"
                r"\bshall\s+not\s+exceed\s*$|"
                r"\bpayments?\s+of\s+amounts?\s+in\s+excess\s+of\s*$|"
                r"\b(?:trigger|incur\w*)\s+obligations?\s+to\s+make\s+"
                r"milestone\s+or\s+other\s+payments?.{0,100}exceed\s*$|"
                r"\bwould\s+reasonably\s+be\s+expected\s+to\s+be\s+"
                r"more\s+than\s*$|"
                r"\bnet\s+sales\b.{0,180}\b(?:reach|exceed|exceeding)\w*\s*$",
                value_before,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            if re.search(
                r"\bnet\s+sales\b.{0,220}\b(?:reach|exceed|exceeding)\w*"
                r".{0,100}\bdollars?\s*\(\s*$",
                value_before,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            if re.match(
                r"\s+payment\s+upon\s+closing\b",
                value_after_short,
                re.IGNORECASE,
            ):
                continue
            if re.search(
                r"\baggregate\s+up[ -]?front\b.{0,80}"
                r"\bmilestone\b.{0,120}\b(?:could|may)\s+exceed\b|"
                r"\bvarious\s+collaboration-related\s+payments\b|"
                r"\bfor\s+any\s+milestone\s+not\s+reached\b.{0,180}"
                r"\bpay\b",
                table_scope,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            if re.search(
                r"\b(?:earnout\s+payments?|maximum\s+aggregate\s+"
                r"consideration|maximum\s+increase\s+in\s+the\s+milestone\s+"
                r"payment|(?:has|have|had)\s+expended|aggregate\s+of\s+such\s+"
                r"payments\s+shall\s+not\s+exceed|effective\s+date.{0,80}"
                r"non[ -]?refundable\s+license\s+fee\s+of|"
                r"non[ -]?refundable\s+license\s+fee\s+of.{0,100}"
                r"effective\s+date|license\s+fee\s+in\s+the\s+amount\s+of)"
                r"\b.{0,120}$",
                value_before,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            if re.search(
                r"\bmilestone\s+payments?\b.{0,100}\boption\s+payments?\b"
                r".{0,100}\btotal(?:ing)?\b|"
                r"\boption\s+payments?\b.{0,100}\btotal(?:ing)?\b",
                value_before,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            if closest_anchor.start() >= relative_end:
                license_fee_matches = list(re.finditer(
                    r"\blicense\s+fees?\b",
                    value_before,
                    re.IGNORECASE,
                ))
                if license_fee_matches:
                    after_license_fee = value_before[
                        license_fee_matches[-1].end():
                    ]
                    if not _SENTENCE_BOUNDARY.search(after_license_fee):
                        continue
            if (
                re.search(
                    r"\bannual\s+net\s+sales\b", table_scope, re.IGNORECASE
                )
                and re.search(r"\broyalty\s+rate\b", table_scope, re.IGNORECASE)
            ):
                continue
            preceding_scope = excerpt[max(0, relative_start - 1200):relative_start]
            preceding_lower = preceding_scope.lower()
            def last_context_match(pattern: str) -> int:
                matches = list(re.finditer(pattern, preceding_lower))
                return matches[-1].start() if matches else -1

            last_research_section = max(
                last_context_match(r"\bresearch\s+funding\b"),
                last_context_match(r"\bresearch\s+plan\b"),
                last_context_match(r"\bresearch\s+fees\b"),
                last_context_match(r"\badc\s+access\s+fee\b"),
            )
            last_milestone_payment = last_context_match(
                r"\bmilestone\s+payments?\b"
            )
            if (
                last_research_section >= 0
                and last_research_section > last_milestone_payment
                and len(preceding_scope) - last_research_section <= 700
            ):
                continue
            last_purchase_price = last_context_match(r"\bpurchase\s+price\b")
            if (
                last_purchase_price >= 0
                and last_purchase_price > last_milestone_payment
                and len(preceding_scope) - last_purchase_price <= 700
            ):
                continue
            if re.search(
                r"\bmaximum\s+cash\s+indemnification\b",
                table_scope,
                re.IGNORECASE,
            ):
                continue
            if re.search(
                r"\b(?:annual|cumulative)\s+(?:net\s+)?(?:sales|revenues?|"
                r"royalty\s+payments?).{0,100}(?:equals?|exceeds?|exceeding|"
                r"threshold|total(?:ing)?|of)\b.{0,80}$|"
                r"\b(?:credit\s+facility|aggregate\s+expenditures?|"
                r"annual\s+revenues?|lump\s+sum\s+cash\s+payment)\b.{0,140}$|"
                r"\ba\s+fee\s+of\b.{0,100}$|"
                r"\badditional\s+milestone\s+payment\s+reduction\s+amount\b"
                r".{0,140}$|"
                r"\bannual\s+payment\s+of\b.{0,80}$|"
                r"\broyalties\s+otherwise\s+payable\b.{0,100}$",
                value_before,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            if re.match(
                r"\s*\)?\s*(?:in\s+(?:annual\s+)?(?:net\s+)?sales|"
                r"in\s+cumulative\s+royalty\s+payments|"
                r"credit\s+facility\b|"
                r"of\s+royalties\s+otherwise\s+payable|"
                r"payment\s+(?:to\s+licensors?\s+)?for\s+each\s+"
                r"milestone\s+extension)\b",
                value_after_short,
                re.IGNORECASE,
            ):
                continue
            milestone_value_scope = excerpt[
                max(0, relative_start - 300):relative_end + 300
            ]
            if re.search(
                r"\bfor\s+example,?\s+if\b.{0,260}\b(?:licenses?|products?)\b"
                r".{0,260}\btotal\s+milestones?\b|"
                r"\bmilestone\s+payments?\s+or\s+royalties\b.{0,160}"
                r"\baggregate\s+expenditures?\b",
                milestone_value_scope,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
            sentence_start = max(
                excerpt.rfind(".", 0, relative_start),
                excerpt.rfind("\n\n", 0, relative_start),
            ) + 1
            sentence_end = excerpt.find(".", relative_end)
            sentence_end = sentence_end if sentence_end >= 0 else len(excerpt)
            sentence = excerpt[sentence_start:sentence_end]
            if (
                re.search(r"\bannual\s+net\s+sales\b", sentence, re.IGNORECASE)
                and re.search(r"\broyalty\s+rate\b", sentence, re.IGNORECASE)
                and not re.search(
                    r"\bmilestone\s+payments?\b", sentence, re.IGNORECASE
                )
            ):
                continue
            if (
                re.search(
                    r"\bresearch\s+(?:funding|plan)\b", sentence, re.IGNORECASE
                )
                and not re.search(
                    r"\bmilestone\s+payments?\b", sentence, re.IGNORECASE
                )
            ):
                continue
            if re.search(
                r"\bup[ -]?fronts?\s+and\s+milestones?\b.{0,100}"
                r"\b(?:worth|total(?:ing)?)\b",
                sentence,
                re.IGNORECASE | re.DOTALL,
            ):
                continue
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
                sentence,
                position - sentence_start,
            )
            if (
                aggregate_distance is not None
                and aggregate_distance < anchor_distance
            ):
                continue
        values.append(value)

    # A single min/max pair cannot safely compare different currencies. Keep
    # the first supported currency in document order and preserve the full
    # source excerpt for analysts who need the alternate-currency disclosure.
    if values:
        primary_currency = values[0]["currency"]
        values = [
            value for value in values
            if value["currency"] == primary_currency
        ]
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


def _clause_review_key(clause: dict) -> tuple:
    """Identify the exact extracted assertion covered by a human decision."""
    return (
        clause.get("clause_type"),
        clause.get("source_hash"),
        clause.get("rate_min_pct"),
        clause.get("rate_max_pct"),
        clause.get("amount_min_millions"),
        clause.get("amount_max_millions"),
        clause.get("currency"),
        clause.get("is_tiered"),
    )


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
            review_parser_version INTEGER,
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
        ALTER TABLE contract_financial_clauses
        ADD COLUMN IF NOT EXISTS review_parser_version INTEGER
    """))
    session.execute(text("""
        UPDATE contract_financial_clauses
        SET review_parser_version = parser_version
        WHERE review_status IN ('accepted', 'rejected')
          AND review_parser_version IS NULL
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
                               reviewer, review_note, reviewed_at,
                               review_parser_version,
                               rate_min_pct, rate_max_pct,
                               amount_min_millions, amount_max_millions,
                               currency, is_tiered
                        FROM contract_financial_clauses
                        WHERE contract_id = :contract_id
                          AND review_status IN ('accepted', 'rejected')
                        ORDER BY parser_version DESC, reviewed_at DESC NULLS LAST
                    """), {"contract_id": contract_id}).mappings().all()
                    for reviewed_row in reviewed_rows:
                        previous_reviews.setdefault(
                            _clause_review_key(reviewed_row),
                            dict(reviewed_row),
                        )
                    session.execute(text(
                        "DELETE FROM contract_financial_clauses "
                        "WHERE contract_id = :contract_id"
                    ), {"contract_id": contract_id})
                    for clause in clauses:
                        previous_review = previous_reviews.get(
                            _clause_review_key(clause)
                        ) or {}
                        session.execute(text("""
                            INSERT INTO contract_financial_clauses (
                                contract_id, deal_id, clause_type,
                                rate_min_pct, rate_max_pct,
                                amount_min_millions, amount_max_millions,
                                currency, is_tiered, confidence, review_status,
                                reviewer, review_note, reviewed_at,
                                review_parser_version,
                                source_text, source_char_start, source_char_end,
                                source_line_start, source_line_end, source_hash,
                                parser_version, extracted_values
                            ) VALUES (
                                :contract_id, :deal_id, :clause_type,
                                :rate_min_pct, :rate_max_pct,
                                :amount_min_millions, :amount_max_millions,
                                :currency, :is_tiered, :confidence, :review_status,
                                :reviewer, :review_note, :reviewed_at,
                                :review_parser_version,
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
                            "review_parser_version": previous_review.get(
                                "review_parser_version"
                            ),
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
            reviewed_at = NOW(),
            review_parser_version = :parser_version
        WHERE id = :clause_id
        RETURNING id, contract_id, deal_id, clause_type, review_status,
                  reviewer, review_note, reviewed_at, review_parser_version
    """), {
        "clause_id": clause_id,
        "review_status": review_status,
        "reviewer": reviewer,
        "note": note,
        "parser_version": CONTRACT_CLAUSE_PARSER_VERSION,
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
            COUNT(*) FILTER (
                WHERE review_status = 'accepted'
                  AND review_parser_version = :parser_version
            ) AS fresh_reviewed_accepted,
            COUNT(*) FILTER (
                WHERE review_status = 'rejected'
                  AND review_parser_version = :parser_version
            ) AS fresh_reviewed_rejected,
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
    fresh_reviewed_accepted = int(population["fresh_reviewed_accepted"] or 0)
    fresh_reviewed_rejected = int(population["fresh_reviewed_rejected"] or 0)
    fresh_reviewed = fresh_reviewed_accepted + fresh_reviewed_rejected
    fresh_review_precision = (
        round(100 * fresh_reviewed_accepted / fresh_reviewed, 2)
        if fresh_reviewed else None
    )
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
        "fresh_reviewed_clauses": fresh_reviewed,
        "fresh_review_precision_pct": fresh_review_precision,
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
        and fresh_reviewed >= 100
        and fresh_review_precision is not None
        and fresh_review_precision >= 95.0
    )
    return report

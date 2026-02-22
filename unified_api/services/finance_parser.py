"""
Finance detail parser — extracts structured financial terms from
raw text descriptions (finance_detail_raw, payments fields).

Uses regex-based extraction for speed and reliability.
"""
import re
from typing import Dict, Any, Optional
import structlog

logger = structlog.get_logger(__name__)


def _parse_amount(text: str) -> Optional[Dict[str, Any]]:
    """Extract an amount from text with currency detection. Returns amount in millions."""
    if not text:
        return None

    # Currency symbols and their codes
    currency_patterns = [
        (r'\$', 'USD'),
        (r'€', 'EUR'),
        (r'¥', 'JPY'),
        (r'£', 'GBP'),
    ]

    # Try each currency
    for currency_symbol, currency_code in currency_patterns:
        # Match patterns like: $50 million, €50M, ¥1.2 billion, £100M
        patterns = [
            # X billion / XB
            (currency_symbol + r'\s*([\d,.]+)\s*(?:billion|B)\b', 1000),
            # X million / XM
            (currency_symbol + r'\s*([\d,.]+)\s*(?:million|M)\b', 1),
            # X thousand / XK
            (currency_symbol + r'\s*([\d,]+)\s*(?:thousand|K)\b', 0.001),
        ]

        for pattern, multiplier in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    amount = float(match.group(1).replace(",", "")) * multiplier
                    return {"amount": round(amount, 1), "currency": currency_code}
                except ValueError:
                    continue

    return None


def _parse_royalty_rates(text: str) -> Optional[Dict[str, Any]]:
    """Extract royalty rate ranges from text."""
    if not text:
        return None

    # Match: "X% to Y%", "X%-Y%", "ranging from X% to Y%"
    range_pattern = r'(\d+(?:\.\d+)?)\s*%\s*(?:to|[-–—])\s*(\d+(?:\.\d+)?)\s*%'
    match = re.search(range_pattern, text, re.IGNORECASE)
    if match:
        return {
            "min_rate": float(match.group(1)),
            "max_rate": float(match.group(2)),
        }

    # Match single rate: "X% royalty"
    single_pattern = r'(\d+(?:\.\d+)?)\s*%\s*(?:royalt|on\s+net)'
    match = re.search(single_pattern, text, re.IGNORECASE)
    if match:
        rate = float(match.group(1))
        return {"min_rate": rate, "max_rate": rate}

    return None


def parse_finance_detail(text: Optional[str]) -> Dict[str, Any]:
    """
    Parse a finance_detail_raw string into structured financial terms.

    Returns:
    {
        "upfront": {"amount": float_millions, "currency": "USD"} | None,
        "milestones": {
            "development": {"amount": float_millions} | None,
            "regulatory": {"amount": float_millions} | None,
            "commercial": {"amount": float_millions} | None,
        },
        "royalties": {"min_rate": float, "max_rate": float} | None,
        "total_value": {"amount": float_millions, "currency": "USD"} | None,
        "undisclosed": bool,
    }
    """
    result = {
        "upfront": None,
        "milestones": {"development": None, "regulatory": None, "commercial": None},
        "royalties": None,
        "total_value": None,
        "undisclosed": False,
    }

    if not text:
        return result

    text_lower = text.lower()

    # Check for "no financial terms disclosed" or similar patterns
    undisclosed_patterns = [
        r'no\s+financial\s+terms?\s+disclosed',
        r'financial\s+terms?\s+not\s+disclosed',
        r'terms?\s+of\s+(?:the\s+)?(?:deal|agreement)\s+(?:were\s+)?not\s+disclosed',
        r'undisclosed\s+financial\s+terms?',
    ]
    for pattern in undisclosed_patterns:
        if re.search(pattern, text_lower):
            result["undisclosed"] = True
            return result

    # Upfront payment (supports multiple currencies)
    upfront_patterns = [
        r'(?:upfront|up-front|up\s+front|signing|initial)\s+(?:payment|fee|consideration)\s+(?:of\s+)?(?:approximately\s+)?([€¥£$][\d,.]+\s*(?:million|billion|M|B))',
        r'(?:approximately\s+)?([€¥£$][\d,.]+\s*(?:million|billion|M|B))\s+(?:upfront|up-front|up\s+front|signing)',
    ]
    for pattern in upfront_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result["upfront"] = _parse_amount(match.group(1) if match.lastindex else match.group(0))
            break

    # Development / clinical milestones
    # Now supports multiple currencies (€, ¥, £, $)
    dev_patterns = [
        r'([€¥£$][\d,.]+\s*(?:million|billion|M|B))\s+(?:in\s+)?(?:development|clinical)\s+milestone',
        r'(?:development|clinical)\s+milestone[s]?\s+(?:of\s+)?(?:up\s+to\s+)?(?:approximately\s+)?([€¥£$][\d,.]+\s*(?:million|billion|M|B))',
    ]
    for pattern in dev_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            parsed = _parse_amount(match.group(1))
            if parsed:
                result["milestones"]["development"] = parsed
            break

    # Regulatory milestones
    reg_patterns = [
        r'([€¥£$][\d,.]+\s*(?:million|billion|M|B))\s+(?:in\s+)?regulatory\s+milestone',
        r'regulatory\s+milestone[s]?\s+(?:of\s+)?(?:up\s+to\s+)?(?:approximately\s+)?([€¥£$][\d,.]+\s*(?:million|billion|M|B))',
    ]
    for pattern in reg_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            parsed = _parse_amount(match.group(1))
            if parsed:
                result["milestones"]["regulatory"] = parsed
            break

    # Commercial milestones (including sales-based)
    comm_patterns = [
        r'([€¥£$][\d,.]+\s*(?:million|billion|M|B))\s+(?:in\s+)?(?:commercial|sales(?:-based)?)\s+milestone',
        r'(?:commercial|sales(?:-based)?)\s+milestone[s]?\s+(?:of\s+)?(?:up\s+to\s+)?(?:approximately\s+)?([€¥£$][\d,.]+\s*(?:million|billion|M|B))',
    ]
    for pattern in comm_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            parsed = _parse_amount(match.group(1))
            if parsed:
                result["milestones"]["commercial"] = parsed
            break

    # Combined patterns: "development and regulatory", "clinical and regulatory", "development and commercial"
    combined_patterns = [
        r'([€¥£$][\d,.]+\s*(?:million|billion|M|B))\s+(?:in\s+)?(?:development|clinical)\s+and\s+(?:regulatory|commercial)\s+milestone',
        r'(?:development|clinical)\s+and\s+(?:regulatory|commercial)\s+milestone[s]?\s+(?:of\s+)?(?:up\s+to\s+)?(?:approximately\s+)?([€¥£$][\d,.]+\s*(?:million|billion|M|B))',
    ]
    for pattern in combined_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match and result["milestones"]["development"] is None:
            parsed = _parse_amount(match.group(1))
            if parsed:
                result["milestones"]["development"] = parsed
            break

    # Generic milestone pattern (catches "in milestones" when type not specified)
    # Only use if no other milestone has been captured yet
    if (result["milestones"]["development"] is None and 
        result["milestones"]["regulatory"] is None and 
        result["milestones"]["commercial"] is None):
        generic_patterns = [
            r'(?:up\s+to\s+)?(?:approximately\s+)?([€¥£$][\d,.]+\s*(?:million|billion|M|B))\s+in\s+milestone[s]?',
            r'in\s+milestone[s]?\s+(?:of\s+)?(?:up\s+to\s+)?(?:approximately\s+)?([€¥£$][\d,.]+\s*(?:million|billion|M|B))',
        ]
        for pattern in generic_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                parsed = _parse_amount(match.group(1))
                if parsed:
                    # Default to development category for unspecified milestones
                    result["milestones"]["development"] = parsed
                break

    # Royalties
    result["royalties"] = _parse_royalty_rates(text)

    # Total deal value (supports multiple currencies)
    total_patterns = [
        r'(?:total\s+)?(?:deal\s+|potential\s+|aggregate\s+)?(?:value|consideration)\s+(?:of\s+)?(?:up\s+to\s+)?(?:approximately\s+)?([€¥£$][\d,.]+\s*(?:million|billion|M|B))',
        r'(?:up\s+to\s+)?(?:approximately\s+)?([€¥£$][\d,.]+\s*(?:million|billion|M|B))\s+(?:total|in\s+total|aggregate)',
    ]
    for pattern in total_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result["total_value"] = _parse_amount(match.group(1))
            break

    return result

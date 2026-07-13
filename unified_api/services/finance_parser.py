"""
Finance detail parser — extracts structured financial terms from
raw text descriptions (finance_detail_raw, payments fields).

Uses regex-based extraction for speed and reliability.
"""
import re
from typing import Dict, Any, Optional
import structlog

logger = structlog.get_logger(__name__)

FINANCE_PARSER_VERSION = 4


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _number(value: Any) -> Optional[float]:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _millions(value: Any, unit: Optional[str]) -> Optional[float]:
    number = _number(value)
    if number is None:
        return None
    normalized = (unit or "").lower()
    if normalized in {"b", "billion", "bn"}:
        return number * 1000
    if normalized in {"t", "trillion", "tn"}:
        return number * 1_000_000
    if normalized in {"thousand", "k"}:
        return number / 1000
    return number


def _rate_bounds(value: float, accuracy: Optional[str]) -> tuple[Optional[float], Optional[float]]:
    """Translate Cortellis bound markers into an honest percentage interval."""
    normalized = (accuracy or "").strip()
    if normalized in {"=<", "<="}:
        return None, value
    if normalized in {">=", "=>"}:
        return value, None
    return value, value


def _term_type(payment_type: Optional[str], *, is_breakdown: bool) -> str:
    normalized = (payment_type or "unspecified").lower()
    if "upfront" in normalized or "up front" in normalized:
        return "upfront_payment"
    if "royalty" in normalized and "%" in normalized:
        return "royalty_rate"
    if "transfer price" in normalized and "%" in normalized:
        return "transfer_price_rate"
    if "sales milestone" in normalized or "commercial milestone" in normalized:
        return "commercial_milestone"
    if "dev/reg milestone" in normalized:
        return "development_regulatory_milestone"
    if "development milestone" in normalized or "clinical milestone" in normalized:
        return "development_milestone"
    if "regulatory milestone" in normalized:
        return "regulatory_milestone"
    if "milestone" in normalized:
        return "milestone_component" if is_breakdown else "milestone_total"
    if "royalty" in normalized:
        return "royalty_payment"
    slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return slug or "unspecified"


def _extract_payment(
    payment: dict,
    *,
    deal_id: Optional[int],
    recipient: str,
    basis: str,
    source_path: str,
    is_breakdown: bool = False,
) -> dict:
    values = payment.get("Values") or {}
    value_attributes = values.get("@attributes") or {}
    reported = values.get("ValueReported") or {}
    reported_attributes = reported.get("@attributes") or {}
    converted = values.get("ValueConvertedToUSD") or {}
    converted_attributes = converted.get("@attributes") or {}
    payment_type = payment.get("Type")
    term_type = _term_type(payment_type, is_breakdown=is_breakdown)
    reported_unit = reported_attributes.get("unit")
    reported_value = _number(reported.get("@text"))
    converted_unit = converted_attributes.get("unit")

    # One upstream Cortellis record labels a $200 million upfront payment as
    # 200%, while its converted value and narrative both identify money.  A
    # percentage above 100 with a monetary USD conversion is internally
    # inconsistent, so normalize the analytical unit while retaining the
    # untouched vendor node in source_payload for audit and replay.
    if (
        reported_unit == "%"
        and reported_value is not None
        and reported_value > 100
        and (converted_unit or "").lower()
        in {"million", "b", "billion", "bn", "t", "trillion", "tn"}
    ):
        reported_unit = converted_unit

    rate_min = rate_max = None
    if reported_unit == "%" and reported_value is not None:
        rate_min, rate_max = _rate_bounds(
            reported_value,
            value_attributes.get("accuracy"),
        )
    elif term_type in {"royalty_rate", "transfer_price_rate"}:
        parsed_rates = _parse_royalty_rates(payment.get("Note") or "")
        if parsed_rates:
            rate_min = parsed_rates["min_rate"]
            rate_max = parsed_rates["max_rate"]

    amount_reported_millions = None
    amount_usd_millions = None
    if reported_unit != "%":
        amount_reported_millions = _millions(reported.get("@text"), reported_unit)
        amount_usd_millions = _millions(
            converted.get("@text"),
            converted_unit,
        )

    disclosed = value_attributes.get("disclosureStatus") == "Known"
    has_numeric_value = any(
        value is not None
        for value in (
            amount_reported_millions,
            amount_usd_millions,
            rate_min,
            rate_max,
        )
    )
    return {
        "deal_id": deal_id,
        "recipient": recipient,
        "basis": basis,
        "term_type": term_type,
        "source_payment_type": payment_type,
        "payment_date": payment.get("Date"),
        "amount_reported_millions": amount_reported_millions,
        "reported_currency": reported_attributes.get("currency"),
        "reported_unit": reported_unit,
        "amount_usd_millions": amount_usd_millions,
        "rate_min_pct": rate_min,
        "rate_max_pct": rate_max,
        "accuracy": value_attributes.get("accuracy"),
        "disclosure_status": value_attributes.get("disclosureStatus"),
        "note": payment.get("Note"),
        "is_breakdown": is_breakdown,
        "confidence": 1.0 if disclosed and has_numeric_value else 0.5,
        "source_path": source_path,
        "parser_version": FINANCE_PARSER_VERSION,
        "source_payload": payment,
    }


def extract_financial_terms(payload: Any, deal_id: Optional[int] = None) -> list[dict]:
    """Flatten Cortellis finance JSON into typed terms with source provenance."""
    if not isinstance(payload, dict):
        return []

    terms = []
    side_map = {
        "PaymentsToPrincipal": "principal",
        "PaymentsToPartner": "partner",
    }
    basis_map = {
        "PaymentsPaid": "paid",
        "PaymentsProjectedCurrent": "projected_current",
        "PaymentsProjectedSigning": "projected_signing",
    }

    def add_payments(
        payments: Any,
        *,
        recipient: str,
        basis: str,
        path: str,
        is_breakdown: bool = False,
    ) -> None:
        for index, payment in enumerate(_as_list(payments)):
            if not isinstance(payment, dict):
                continue
            payment_path = f"{path}[{index}]"
            terms.append(_extract_payment(
                payment,
                deal_id=deal_id,
                recipient=recipient,
                basis=basis,
                source_path=payment_path,
                is_breakdown=is_breakdown,
            ))
            breakdown = (payment.get("PaymentBreakdown") or {}).get("Payment")
            add_payments(
                breakdown,
                recipient=recipient,
                basis=basis,
                path=f"{payment_path}.PaymentBreakdown.Payment",
                is_breakdown=True,
            )

    for side_key, recipient in side_map.items():
        side = payload.get(side_key) or {}
        for basis_key, basis in basis_map.items():
            section = side.get(basis_key) or {}
            for collection_key in ("PaymentsGeneral", "PaymentsPercentage"):
                payments = (section.get(collection_key) or {}).get("Payment")
                add_payments(
                    payments,
                    recipient=recipient,
                    basis=basis,
                    path=f"{side_key}.{basis_key}.{collection_key}.Payment",
                )

    return terms


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

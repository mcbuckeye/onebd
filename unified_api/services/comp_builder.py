"""
Comp Builder service — deal similarity scoring and statistical summaries.
"""
from typing import List, Dict, Any
import statistics


def _canonical_match_value(field: str, value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", " ")
    normalized = " ".join(normalized.split())
    aliases = {
        "indication": {
            "nsclc": "non small cell lung cancer",
            "non small cell lung cancer": "non small cell lung cancer",
            "sclc": "small cell lung cancer",
            "aml": "acute myeloid leukemia",
            "acute myelogenous leukemia": "acute myeloid leukemia",
            "dlbcl": "diffuse large b cell lymphoma",
            "tnbc": "triple negative breast cancer",
            "rcc": "renal cell carcinoma",
        },
        "modality": {
            "adc": "antibody drug conjugate",
            "antibody drug conjugate": "antibody drug conjugate",
        },
    }
    return aliases.get(field, {}).get(normalized, normalized)


def score_deal_similarity(criteria: Dict[str, str], deal: Dict[str, Any]) -> float:
    """
    Score how similar a deal is to the target criteria.
    Returns 0.0-1.0.

    Weights:
    - indication match: 0.35
    - phase match: 0.25
    - modality/technology match: 0.25
    - deal type match: 0.15
    """
    if not criteria:
        return 0.0

    total_weight = 0.0
    weighted_score = 0.0

    weights = {
        "indication": 0.35,
        "phase": 0.25,
        "modality": 0.25,
        "deal_type": 0.15,
    }

    for field, weight in weights.items():
        if field not in criteria or not criteria[field]:
            continue
        total_weight += weight

        crit_val = _canonical_match_value(field, criteria[field])
        deal_val = _canonical_match_value(field, deal.get(field, ""))

        if not deal_val:
            continue
        elif crit_val == deal_val:
            weighted_score += weight * 1.0
        elif crit_val in deal_val or deal_val in crit_val:
            weighted_score += weight * 0.5

    if total_weight == 0:
        return 0.0

    return round(weighted_score / total_weight, 3)


def compute_comp_stats(deals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute statistical summary of a comp set's financial data.
    """
    values = [d["total_value"] for d in deals if d.get("total_value") is not None]

    if not values:
        return {
            "count": len(deals),
            "disclosed": 0,
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
            "q1": None,
            "q3": None,
        }

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    # Q1/Q3 calculation
    q1 = sorted_vals[n // 4] if n >= 4 else sorted_vals[0]
    q3 = sorted_vals[(3 * n) // 4] if n >= 4 else sorted_vals[-1]

    return {
        "count": len(deals),
        "disclosed": len(values),
        "mean": round(statistics.mean(values), 1),
        "median": round(statistics.median(values), 1),
        "min": min(values),
        "max": max(values),
        "q1": q1,
        "q3": q3,
    }

"""
Recommendation engine — surfaces relevant deals based on user interests.
"""
from typing import List, Dict, Any


def score_deal_relevance(deal: Dict[str, Any], user_interests: List[str]) -> float:
    """Score how relevant a deal is to user interests."""
    if not user_interests:
        return 0.0

    score = 0.0
    matches = 0

    deal_text = " ".join(str(v).lower() for v in deal.values() if v)

    for interest in user_interests:
        if interest.lower() in deal_text:
            matches += 1

    score = matches / len(user_interests) if user_interests else 0.0
    return min(score, 1.0)


def generate_reasons(deal: Dict[str, Any], matched_on: List[str]) -> List[str]:
    """Generate human-readable reasons for a recommendation."""
    reasons = []

    for match in matched_on:
        if match == "indication":
            reasons.append(f"Matches your tracked indication: {deal.get('indication', 'N/A')}")
        elif match == "company":
            reasons.append(f"Involves a company you follow")
        elif match == "modality":
            reasons.append(f"Uses {deal.get('modality', 'a modality')} you've searched for")
        elif match == "high_value":
            reasons.append(f"High-value deal: ${deal.get('value', 0)}M")

    if not reasons:
        reasons.append("Related to your recent search activity")

    return reasons

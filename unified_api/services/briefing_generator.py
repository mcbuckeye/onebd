"""
Briefing generator — creates structured intelligence briefings.
"""
from typing import Dict, Any, List


def build_market_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": "Market Summary",
        "content": {
            "matching_deals": data.get("matching_deals", data.get("deals_30d", 0)),
            "top_therapy": data.get("top_therapy"),
            "trend": data.get("trend"),
        },
    }


def build_competitor_summary(competitors: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "title": "Competitor Activity",
        "content": competitors[:10],
    }


def build_notable_deals(deals: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "title": "Notable Deals",
        "content": deals[:10],
    }

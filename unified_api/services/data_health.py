"""
Data health monitoring — checks integrity, freshness, and completeness
across all data sources (Cortellis PG, EDGAR PG, Neo4j, Redis).
"""
from typing import Dict, Any, List
from datetime import datetime, timezone, timedelta
import structlog

logger = structlog.get_logger(__name__)


def compute_health_score(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute overall data health score (0-100) with individual checks.
    """
    checks = []
    total_score = 0
    max_score = 0

    # Check 1: Data freshness (last sync)
    max_score += 25
    last_sync_str = metrics.get("last_sync")
    if last_sync_str:
        try:
            if isinstance(last_sync_str, datetime):
                last_sync = last_sync_str
            else:
                last_sync = datetime.fromisoformat(
                    str(last_sync_str).replace("Z", "+00:00")
                )
            if last_sync.tzinfo is None:
                last_sync = last_sync.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - last_sync).total_seconds() / 3600

            if age_hours < 24:
                checks.append({"name": "Data Freshness", "status": "ok", "detail": f"Last sync: {age_hours:.0f}h ago"})
                total_score += 25
            elif age_hours < 72:
                checks.append({"name": "Data Freshness", "status": "warning", "detail": f"Last sync: {age_hours:.0f}h ago — consider resyncing"})
                total_score += 15
            else:
                checks.append({"name": "Data Freshness", "status": "critical", "detail": f"Last sync: {age_hours:.0f}h ago — data is stale"})
                total_score += 5
        except (ValueError, TypeError):
            checks.append({"name": "Data Freshness", "status": "critical", "detail": "Cannot parse last sync time"})
    else:
        checks.append({"name": "Data Freshness", "status": "critical", "detail": "No sync timestamp found"})

    # Check 2: Financial disclosure rate
    max_score += 20
    deals_total = metrics.get("deals_total", 0)
    deals_financial = metrics.get("deals_with_financials", 0)
    if deals_total > 0:
        disclosure_pct = (deals_financial / deals_total) * 100
        if disclosure_pct >= 25:
            checks.append({"name": "Financial Disclosure", "status": "ok", "detail": f"{disclosure_pct:.1f}% ({deals_financial:,}/{deals_total:,})"})
            total_score += 20
        elif disclosure_pct >= 15:
            checks.append({"name": "Financial Disclosure", "status": "warning", "detail": f"{disclosure_pct:.1f}% — below target 25%"})
            total_score += 12
        else:
            checks.append({"name": "Financial Disclosure", "status": "critical", "detail": f"{disclosure_pct:.1f}% — severely low"})
            total_score += 5

    # Check 3: Graph sync completeness (deals)
    max_score += 20
    graph_deals = metrics.get("graph_deals", 0)
    if deals_total > 0 and graph_deals > 0:
        sync_pct = (graph_deals / deals_total) * 100
        if sync_pct >= 90:
            checks.append({"name": "Graph Sync (Deals)", "status": "ok", "detail": f"{sync_pct:.0f}% synced ({graph_deals:,}/{deals_total:,})"})
            total_score += 20
        elif sync_pct >= 50:
            checks.append({"name": "Graph Sync (Deals)", "status": "warning", "detail": f"{sync_pct:.0f}% synced — partial"})
            total_score += 10
        else:
            checks.append({"name": "Graph Sync (Deals)", "status": "critical", "detail": f"{sync_pct:.0f}% synced — graph significantly behind"})
            total_score += 3
    elif graph_deals == 0:
        checks.append({"name": "Graph Sync (Deals)", "status": "critical", "detail": "No deals in graph"})

    # Check 4: Entity resolution coverage
    max_score += 15
    companies_total = metrics.get("companies_total", 0)
    companies_xref = metrics.get("companies_with_xref", 0)
    if companies_total > 0:
        xref_pct = (companies_xref / companies_total) * 100
        if xref_pct >= 10:
            checks.append({"name": "Entity Resolution", "status": "ok", "detail": f"{companies_xref:,}/{companies_total:,} companies cross-referenced ({xref_pct:.1f}%)"})
            total_score += 15
        elif xref_pct >= 2:
            checks.append({"name": "Entity Resolution", "status": "warning", "detail": f"Only {xref_pct:.1f}% cross-referenced — enrichment needed"})
            total_score += 8
        else:
            checks.append({"name": "Entity Resolution", "status": "critical", "detail": f"Only {xref_pct:.1f}% cross-referenced"})
            total_score += 2

    # Check 5: Graph relationship density
    max_score += 20
    graph_rels = metrics.get("graph_relationships", 0)
    graph_companies = metrics.get("graph_companies", 0)
    if graph_companies > 0:
        rels_per_company = graph_rels / graph_companies
        if rels_per_company >= 3:
            checks.append({"name": "Graph Density", "status": "ok", "detail": f"{rels_per_company:.1f} relationships per company"})
            total_score += 20
        elif rels_per_company >= 1:
            checks.append({"name": "Graph Density", "status": "warning", "detail": f"{rels_per_company:.1f} relationships per company — sparse"})
            total_score += 10
        else:
            checks.append({"name": "Graph Density", "status": "critical", "detail": f"{rels_per_company:.1f} relationships per company — very sparse"})
            total_score += 3

    overall = round((total_score / max_score) * 100) if max_score > 0 else 0

    return {
        "overall_score": overall,
        "checks": checks,
    }

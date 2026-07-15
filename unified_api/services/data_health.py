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
    Compute a transparent data-readiness index and categorized checks.

    This is deliberately not an operational uptime score. Source-job and
    service availability are added by the health router and determine the
    overall operational status independently.
    """
    checks: list[dict] = []
    components: list[dict] = []

    def add_component(name: str, value: float, weight: int, rationale: str):
        components.append({
            "name": name,
            "value": round(max(0.0, min(1.0, value)), 4),
            "weight": weight,
            "points": round(max(0.0, min(1.0, value)) * weight, 1),
            "rationale": rationale,
        })

    # Check 1: Data freshness (last sync)
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
                status = "ok"
                freshness_value = 1.0
            elif age_hours < 72:
                status = "warning"
                freshness_value = 0.6
            else:
                status = "critical"
                freshness_value = 0.2
            checks.append({
                "name": "Data Freshness",
                "category": "freshness",
                "status": status,
                "detail": f"Last successful Cortellis sync completed {age_hours:.1f}h ago",
            })
            add_component(
                "Cortellis successful-sync recency",
                freshness_value,
                30,
                "Recency of a completed source check; a no-change run is still operational evidence.",
            )
        except (ValueError, TypeError):
            checks.append({"name": "Data Freshness", "category": "freshness", "status": "critical", "detail": "Cannot parse last successful sync time"})
            add_component("Cortellis successful-sync recency", 0, 30, "Timestamp unavailable or invalid.")
    else:
        checks.append({"name": "Data Freshness", "category": "freshness", "status": "critical", "detail": "No successful sync timestamp found"})
        add_component("Cortellis successful-sync recency", 0, 30, "No successful sync timestamp is available.")

    # Check 2: Financial disclosure rate
    deals_total = metrics.get("deals_total", 0)
    deals_financial = metrics.get("deals_with_financials", 0)
    if deals_total > 0:
        disclosure_pct = (deals_financial / deals_total) * 100
        checks.append({
            "name": "Financial Disclosure Coverage",
            "category": "coverage",
            "status": "info",
            "detail": (
                f"{disclosure_pct:.1f}% ({deals_financial:,}/{deals_total:,}) of deals "
                "have a projected-current amount; non-disclosure is source coverage, not a system failure"
            ),
        })
        add_component(
            "Structured financial coverage",
            min(disclosure_pct / 30.0, 1.0),
            20,
            "Availability index capped at 30% coverage; it is not an operational pass/fail threshold.",
        )
    else:
        checks.append({"name": "Cortellis Deal Coverage", "category": "coverage", "status": "critical", "detail": "No Cortellis deals are available"})
        add_component("Structured financial coverage", 0, 20, "No deal records are available.")

    # Check 3: Graph sync completeness (deals)
    graph_deals = metrics.get("graph_deals", 0)
    if deals_total > 0 and graph_deals > 0:
        sync_pct = (graph_deals / deals_total) * 100
        if sync_pct >= 90:
            status = "ok"
        elif sync_pct >= 50:
            status = "warning"
        else:
            status = "critical"
        checks.append({"name": "Graph Deal Coverage", "category": "coverage", "status": status, "detail": f"{sync_pct:.1f}% ({graph_deals:,}/{deals_total:,}) of Cortellis deals represented in Neo4j"})
        add_component("Neo4j deal coverage", min(sync_pct / 100.0, 1.0), 30, "Ratio of graph Deal nodes to relational deal records.")
    elif graph_deals == 0:
        checks.append({"name": "Graph Deal Coverage", "category": "coverage", "status": "critical", "detail": "No Deal nodes are available in Neo4j"})
        add_component("Neo4j deal coverage", 0, 30, "No graph Deal nodes are available.")

    # Check 4: Entity resolution coverage
    companies_total = metrics.get("companies_total", 0)
    companies_xref = metrics.get("companies_with_xref", 0)
    if companies_total > 0:
        xref_pct = (companies_xref / companies_total) * 100
        checks.append({"name": "Cross-source Entity Resolution", "category": "coverage", "status": "info", "detail": f"{companies_xref:,}/{companies_total:,} companies cross-referenced ({xref_pct:.1f}%); this only measures available cross-source links"})
        add_component("Company cross-reference coverage", min(xref_pct / 10.0, 1.0), 20, "Availability index capped at 10% because many private entities have no EDGAR identity.")
    else:
        add_component("Company cross-reference coverage", 0, 20, "No company records are available.")

    # Check 5: Graph relationship density
    graph_rels = metrics.get("graph_relationships", 0)
    graph_companies = metrics.get("graph_companies", 0)
    if graph_companies > 0:
        rels_per_company = graph_rels / graph_companies
        checks.append({"name": "Graph Relationship Density", "category": "quality", "status": "info", "detail": f"{rels_per_company:.1f} relationships per Company node; descriptive only, because expected density varies by source and entity"})

    overall = round(sum(component["points"] for component in components))

    return {
        "overall_score": overall,
        "readiness_score": overall,
        "score_label": "Data readiness index",
        "score_scope": (
            "Weighted coverage/recency index only; it does not represent uptime, "
            "source-job success, accuracy, or license compliance."
        ),
        "score_components": components,
        "checks": checks,
    }

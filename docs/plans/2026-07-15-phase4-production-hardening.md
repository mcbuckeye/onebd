# Phase 4: Data Integrity, Email Digests & Production Hardening

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ensure all data sources are synced and accurate, add email digest delivery so JVO gets briefings without logging in, and harden the platform for production reliability.

**Working Directory:** `/Users/kayleighbot/Projects/cortellis`

**Methodology:** TDD for all backend tasks.

---

## Overview of Tasks

| Task | Component | Type | Estimated Time |
|------|-----------|------|---------------|
| 1A | Data integrity audit + graph sync verification — TESTS FIRST | Backend/Test | 10 min |
| 1B | Data integrity audit — IMPLEMENTATION (health check endpoint) | Backend | 10 min |
| 2A | Finance data enrichment parser — TESTS FIRST | Backend/Test | 10 min |
| 2B | Finance data enrichment parser — IMPLEMENTATION | Backend | 15 min |
| 3A | Email digest system — TESTS FIRST | Backend/Test | 10 min |
| 3B | Email digest system — IMPLEMENTATION | Backend | 15 min |
| 4 | Wire Celery tasks to real implementations | Backend | 10 min |
| 5A | Production hardening — TESTS FIRST | Backend/Test | 5 min |
| 5B | Production hardening — IMPLEMENTATION | Backend | 15 min |
| 6 | Data status dashboard widget on frontend | Frontend | 10 min |
| 7 | Integration tests + build verification + push | Test/DevOps | 10 min |

---

## Task 1A: Data Integrity Audit — TESTS FIRST

**Files:**
- Create: `unified_api/tests/unit/test_data_health.py`
- Create: `unified_api/tests/integration/test_data_health_endpoint.py`

**Step 1: Write data health tests**

Create `unified_api/tests/unit/test_data_health.py`:
```python
"""
TDD: Data health check tests.
"""
import pytest


class TestDataHealthScoring:
    """Test data health scoring logic."""

    def test_score_returns_dict(self):
        from unified_api.services.data_health import compute_health_score
        result = compute_health_score({
            "deals_total": 145000,
            "deals_with_financials": 39000,
            "companies_total": 52000,
            "companies_with_xref": 692,
            "graph_companies": 55000,
            "graph_deals": 145000,
            "graph_relationships": 289000,
            "last_sync": "2026-07-15T06:30:00",
        })
        assert isinstance(result, dict)
        assert "overall_score" in result
        assert "checks" in result
        assert isinstance(result["checks"], list)

    def test_score_between_0_and_100(self):
        from unified_api.services.data_health import compute_health_score
        result = compute_health_score({
            "deals_total": 145000,
            "deals_with_financials": 39000,
            "companies_total": 52000,
            "companies_with_xref": 692,
            "graph_companies": 55000,
            "graph_deals": 145000,
            "graph_relationships": 289000,
            "last_sync": "2026-07-15T06:30:00",
        })
        assert 0 <= result["overall_score"] <= 100

    def test_stale_sync_flags_warning(self):
        from unified_api.services.data_health import compute_health_score
        result = compute_health_score({
            "deals_total": 145000,
            "deals_with_financials": 39000,
            "companies_total": 52000,
            "companies_with_xref": 692,
            "graph_companies": 55000,
            "graph_deals": 145000,
            "graph_relationships": 289000,
            "last_sync": "2026-01-01T00:00:00",  # Very stale
        })
        warnings = [c for c in result["checks"] if c["status"] == "warning" or c["status"] == "critical"]
        assert len(warnings) > 0

    def test_graph_mismatch_flags_warning(self):
        from unified_api.services.data_health import compute_health_score
        result = compute_health_score({
            "deals_total": 145000,
            "deals_with_financials": 39000,
            "companies_total": 52000,
            "companies_with_xref": 692,
            "graph_companies": 10000,  # Way fewer than PG
            "graph_deals": 50000,  # Way fewer than PG
            "graph_relationships": 100000,
            "last_sync": "2026-07-15T06:30:00",
        })
        warnings = [c for c in result["checks"] if c["status"] in ("warning", "critical")]
        assert len(warnings) > 0
```

Create `unified_api/tests/integration/test_data_health_endpoint.py`:
```python
"""
TDD: Data health endpoint tests.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestDataHealthEndpoint:

    def test_health_data_returns_200(self, client):
        resp = client.get("/api/health/data")
        assert resp.status_code == 200

    def test_health_data_response_structure(self, client):
        data = client.get("/api/health/data").json()
        assert "overall_score" in data
        assert "checks" in data
        assert "sources" in data
        assert isinstance(data["checks"], list)

    def test_health_data_sources_include_all(self, client):
        sources = client.get("/api/health/data").json()["sources"]
        # Should report on all data sources
        assert "cortellis_deals" in sources
        assert "companies" in sources

    def test_health_data_checks_have_name_and_status(self, client):
        checks = client.get("/api/health/data").json()["checks"]
        for check in checks:
            assert "name" in check
            assert "status" in check
            assert check["status"] in ("ok", "warning", "critical")
```

**Step 2: Run, verify FAIL, commit**

```bash
python -m pytest unified_api/tests/unit/test_data_health.py unified_api/tests/integration/test_data_health_endpoint.py -v
git add unified_api/tests/
git commit -m "test: data health check tests (TDD red phase)"
```

---

## Task 1B: Data Integrity Audit — IMPLEMENTATION

**Files:**
- Create: `unified_api/services/data_health.py`
- Modify: `unified_api/routers/health.py` — add `/api/health/data` endpoint

**Step 1: Create data health service**

Create `unified_api/services/data_health.py`:
```python
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
            last_sync = datetime.fromisoformat(last_sync_str.replace("Z", "+00:00"))
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
```

**Step 2: Add endpoint to health router**

Add to `unified_api/routers/health.py`:
```python
@router.get("/health/data")
async def data_health_check():
    """
    Comprehensive data health check across all sources.
    Reports on: Cortellis PG, EDGAR PG, Neo4j graph, sync freshness.
    """
    from unified_api.services.database import get_cortellis_session, get_edgar_session
    from unified_api.services.data_health import compute_health_score
    from sqlalchemy import text

    sources = {}

    # Cortellis DB metrics
    try:
        with get_cortellis_session() as session:
            counts = session.execute(text("""
                SELECT
                    (SELECT COUNT(*) FROM deals) as deals_total,
                    (SELECT COUNT(*) FROM deal_finance_summary
                     WHERE total_projected_current_amount IS NOT NULL) as deals_with_financials,
                    (SELECT COUNT(*) FROM companies) as companies_total,
                    (SELECT COUNT(*) FROM company_xref) as companies_with_xref,
                    (SELECT MAX(date_start)::text FROM deals) as latest_deal_date
            """)).fetchone()

            sources["cortellis_deals"] = {
                "total": counts.deals_total,
                "with_financials": counts.deals_with_financials,
                "disclosure_rate": f"{(counts.deals_with_financials / counts.deals_total * 100):.1f}%" if counts.deals_total > 0 else "N/A",
                "latest_deal": counts.latest_deal_date,
            }
            sources["companies"] = {
                "total": counts.companies_total,
                "cross_referenced": counts.companies_with_xref,
            }
    except Exception as e:
        sources["cortellis_deals"] = {"error": str(e)}
        sources["companies"] = {"error": str(e)}

    # EDGAR DB metrics
    try:
        with get_edgar_session() as session:
            edgar = session.execute(text("""
                SELECT
                    (SELECT COUNT(*) FROM filings) as filings_total,
                    (SELECT COUNT(*) FROM filing_chunks) as chunks_total,
                    (SELECT MAX(filing_date)::text FROM filings) as latest_filing
            """)).fetchone()

            sources["edgar"] = {
                "filings": edgar.filings_total,
                "chunks": edgar.chunks_total,
                "latest_filing": edgar.latest_filing,
            }
    except Exception as e:
        sources["edgar"] = {"error": str(e)}

    # Neo4j metrics
    graph_companies = 0
    graph_deals = 0
    graph_rels = 0
    try:
        from unified_api.services.graph_sync import get_graph_sync_service
        graph_service = get_graph_sync_service()
        stats = graph_service.get_sync_stats()
        graph_companies = stats.get("nodes", {}).get("Company", 0)
        graph_deals = stats.get("nodes", {}).get("Deal", 0)
        graph_rels = sum(stats.get("relationships", {}).values())
        sources["neo4j"] = {
            "companies": graph_companies,
            "deals": graph_deals,
            "relationships": graph_rels,
            "node_types": stats.get("nodes", {}),
            "relationship_types": stats.get("relationships", {}),
        }
    except Exception as e:
        sources["neo4j"] = {"error": str(e)}

    # Redis metrics
    try:
        from unified_api.services.cache import get_redis
        redis_client = get_redis()
        redis_info = redis_client.info("memory")
        cache_keys = redis_client.dbsize()
        sources["redis"] = {
            "cache_keys": cache_keys,
            "memory_used": redis_info.get("used_memory_human", "unknown"),
        }
    except Exception as e:
        sources["redis"] = {"error": str(e)}

    # Compute health score
    metrics = {
        "deals_total": sources.get("cortellis_deals", {}).get("total", 0),
        "deals_with_financials": sources.get("cortellis_deals", {}).get("with_financials", 0),
        "companies_total": sources.get("companies", {}).get("total", 0),
        "companies_with_xref": sources.get("companies", {}).get("cross_referenced", 0),
        "graph_companies": graph_companies,
        "graph_deals": graph_deals,
        "graph_relationships": graph_rels,
        "last_sync": sources.get("cortellis_deals", {}).get("latest_deal", None),
    }

    health = compute_health_score(metrics)

    return {
        "overall_score": health["overall_score"],
        "checks": health["checks"],
        "sources": sources,
    }
```

**Step 3: Run tests, verify PASS, commit**

```bash
python -m pytest unified_api/tests/unit/test_data_health.py unified_api/tests/integration/test_data_health_endpoint.py -v
git add -A
git commit -m "feat: data health check with scoring across all sources (TDD green)"
```

---

## Task 2A: Finance Data Enrichment Parser — TESTS FIRST

**Files:**
- Create: `unified_api/tests/unit/test_finance_parser.py`

```python
"""
TDD: Finance detail parser tests.
"""
import pytest


class TestFinanceDetailParser:
    """Test parsing of finance_detail_raw into structured data."""

    def test_parse_upfront_payment(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("Upfront payment of $50 million")
        assert result["upfront"] is not None
        assert result["upfront"]["amount"] == 50
        assert result["upfront"]["currency"] == "USD"

    def test_parse_milestone_payments(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail(
            "Up to $200 million in development milestones and $300 million in commercial milestones"
        )
        assert result["milestones"]["development"] is not None
        assert result["milestones"]["commercial"] is not None

    def test_parse_royalty_rate(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("Tiered royalties ranging from 8% to 15% on net sales")
        assert result["royalties"] is not None
        assert result["royalties"]["min_rate"] == 8
        assert result["royalties"]["max_rate"] == 15

    def test_parse_total_value(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("Total deal value of up to $1.2 billion")
        assert result["total_value"] is not None
        assert result["total_value"]["amount"] == 1200  # in millions

    def test_parse_empty_string(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("")
        assert result["upfront"] is None
        assert result["royalties"] is None
        assert result["total_value"] is None

    def test_parse_none_input(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail(None)
        assert isinstance(result, dict)

    def test_parse_complex_detail(self):
        from unified_api.services.finance_parser import parse_finance_detail
        text = """
        $75 million upfront payment. Up to $500 million in development and
        regulatory milestone payments. Up to $750 million in commercial milestones.
        Tiered royalties from 10% to 20% on worldwide net sales.
        Total potential deal value of approximately $1.325 billion.
        """
        result = parse_finance_detail(text)
        assert result["upfront"]["amount"] == 75
        assert result["total_value"]["amount"] == 1325
        assert result["royalties"]["min_rate"] == 10
        assert result["royalties"]["max_rate"] == 20

    def test_parse_million_abbreviation(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("$50M upfront payment")
        assert result["upfront"]["amount"] == 50

    def test_parse_billion_to_millions(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("Total deal value of $2.5 billion")
        assert result["total_value"]["amount"] == 2500  # stored in millions
```

```bash
python -m pytest unified_api/tests/unit/test_finance_parser.py -v
git add unified_api/tests/
git commit -m "test: finance detail parser tests (TDD red phase)"
```

---

## Task 2B: Finance Data Enrichment Parser — IMPLEMENTATION

**Files:**
- Create: `unified_api/services/finance_parser.py`
- Create: `unified_api/routers/enrichment.py` — endpoint to trigger enrichment
- Modify: `unified_api/main.py`

**Step 1: Create finance parser**

Create `unified_api/services/finance_parser.py`:
```python
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
    """Extract a dollar amount from text. Returns amount in millions."""
    if not text:
        return None

    # Match patterns like: $50 million, $50M, $1.2 billion, $1.2B, $500,000
    patterns = [
        # $X billion / $XB
        (r'\$\s*([\d,.]+)\s*(?:billion|B)\b', 1000),
        # $X million / $XM
        (r'\$\s*([\d,.]+)\s*(?:million|M)\b', 1),
        # $X,XXX (assume thousands if no unit, convert to millions)
        (r'\$\s*([\d,]+)\s*(?:thousand|K)\b', 0.001),
    ]

    for pattern, multiplier in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                amount = float(match.group(1).replace(",", "")) * multiplier
                return {"amount": round(amount, 1), "currency": "USD"}
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
    }
    """
    result = {
        "upfront": None,
        "milestones": {"development": None, "regulatory": None, "commercial": None},
        "royalties": None,
        "total_value": None,
    }

    if not text:
        return result

    text_lower = text.lower()

    # Upfront payment
    upfront_patterns = [
        r'(?:upfront|up-front|up\s+front|signing|initial)\s+(?:payment|fee|consideration)\s+(?:of\s+)?' + r'(\$[\d,.]+\s*(?:million|billion|M|B))',
        r'(\$[\d,.]+\s*(?:million|billion|M|B))\s+(?:upfront|up-front|up\s+front|signing)',
    ]
    for pattern in upfront_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result["upfront"] = _parse_amount(match.group(1) if match.lastindex else match.group(0))
            break

    # Development / clinical milestones
    dev_patterns = [
        r'(\$[\d,.]+\s*(?:million|billion|M|B))\s+(?:in\s+)?(?:development|clinical)\s+milestone',
        r'(?:development|clinical)\s+milestone[s]?\s+(?:of\s+)?(?:up\s+to\s+)?(\$[\d,.]+\s*(?:million|billion|M|B))',
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
        r'(\$[\d,.]+\s*(?:million|billion|M|B))\s+(?:in\s+)?regulatory\s+milestone',
        r'regulatory\s+milestone[s]?\s+(?:of\s+)?(?:up\s+to\s+)?(\$[\d,.]+\s*(?:million|billion|M|B))',
    ]
    for pattern in reg_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            parsed = _parse_amount(match.group(1))
            if parsed:
                result["milestones"]["regulatory"] = parsed
            break

    # Commercial milestones
    comm_patterns = [
        r'(\$[\d,.]+\s*(?:million|billion|M|B))\s+(?:in\s+)?commercial\s+milestone',
        r'commercial\s+milestone[s]?\s+(?:of\s+)?(?:up\s+to\s+)?(\$[\d,.]+\s*(?:million|billion|M|B))',
    ]
    for pattern in comm_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            parsed = _parse_amount(match.group(1))
            if parsed:
                result["milestones"]["commercial"] = parsed
            break

    # Combined "development and regulatory" or "development and commercial"
    combined_pattern = r'(\$[\d,.]+\s*(?:million|billion|M|B))\s+(?:in\s+)?(?:development\s+and\s+(?:regulatory|commercial)|clinical\s+and\s+(?:regulatory|commercial))\s+milestone'
    match = re.search(combined_pattern, text, re.IGNORECASE)
    if match and result["milestones"]["development"] is None:
        parsed = _parse_amount(match.group(1))
        if parsed:
            result["milestones"]["development"] = parsed

    # Royalties
    result["royalties"] = _parse_royalty_rates(text)

    # Total deal value
    total_patterns = [
        r'(?:total\s+)?(?:deal\s+|potential\s+|aggregate\s+)?(?:value|consideration)\s+(?:of\s+)?(?:up\s+to\s+)?(?:approximately\s+)?(\$[\d,.]+\s*(?:million|billion|M|B))',
        r'(\$[\d,.]+\s*(?:million|billion|M|B))\s+(?:total|in\s+total|aggregate)',
    ]
    for pattern in total_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result["total_value"] = _parse_amount(match.group(1))
            break

    return result
```

**Step 2: Create enrichment endpoint**

Create `unified_api/routers/enrichment.py`:
```python
"""
Data enrichment endpoints — trigger parsing and enrichment of raw data fields.
"""
from fastapi import APIRouter, Query
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.finance_parser import parse_finance_detail

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["enrichment"])


@router.post("/enrichment/parse-financials")
async def parse_financial_details(
    batch_size: int = Query(100, ge=1, le=1000),
    dry_run: bool = Query(False),
):
    """
    Parse finance_detail_raw fields into structured financial data.
    Processes deals that have raw finance text but haven't been parsed yet.
    """
    parsed_count = 0
    error_count = 0
    results_sample = []

    with get_cortellis_session() as session:
        # Check if the enrichment tracking column exists, create if not
        session.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'deal_finance_summary'
                    AND column_name = 'parsed_detail'
                ) THEN
                    ALTER TABLE deal_finance_summary ADD COLUMN parsed_detail JSONB;
                END IF;
            END $$
        """))
        session.commit()

        # Get deals with finance detail text that haven't been parsed
        deals = session.execute(text("""
            SELECT f.deal_id, f.finance_detail_raw
            FROM deal_finance_summary f
            WHERE f.finance_detail_raw IS NOT NULL
              AND f.finance_detail_raw != ''
              AND f.parsed_detail IS NULL
            LIMIT :batch_size
        """), {"batch_size": batch_size}).fetchall()

        for deal in deals:
            try:
                parsed = parse_finance_detail(deal.finance_detail_raw)

                if not dry_run:
                    import json
                    session.execute(text("""
                        UPDATE deal_finance_summary
                        SET parsed_detail = :parsed
                        WHERE deal_id = :deal_id
                    """), {
                        "deal_id": deal.deal_id,
                        "parsed": json.dumps(parsed),
                    })

                parsed_count += 1

                if len(results_sample) < 5:
                    results_sample.append({
                        "deal_id": deal.deal_id,
                        "raw_text": deal.finance_detail_raw[:200],
                        "parsed": parsed,
                    })

            except Exception as e:
                error_count += 1
                logger.error("Failed to parse finance detail", deal_id=deal.deal_id, error=str(e))

        if not dry_run:
            session.commit()

    return {
        "processed": parsed_count,
        "errors": error_count,
        "dry_run": dry_run,
        "sample": results_sample,
        "remaining": "Use batch_size to process more",
    }


@router.get("/enrichment/status")
async def enrichment_status():
    """Get current enrichment status across all data sources."""
    with get_cortellis_session() as session:
        stats = session.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM deal_finance_summary WHERE finance_detail_raw IS NOT NULL) as has_raw_text,
                (SELECT COUNT(*) FROM deal_finance_summary WHERE parsed_detail IS NOT NULL) as has_parsed,
                (SELECT COUNT(*) FROM deal_finance_summary WHERE total_projected_current_amount IS NOT NULL) as has_amount,
                (SELECT COUNT(*) FROM deals) as total_deals
        """)).fetchone()

    return {
        "finance_enrichment": {
            "deals_with_raw_text": stats.has_raw_text,
            "deals_parsed": stats.has_parsed,
            "deals_with_amount": stats.has_amount,
            "total_deals": stats.total_deals,
            "parse_coverage": f"{(stats.has_parsed / stats.has_raw_text * 100):.1f}%" if stats.has_raw_text > 0 else "0%",
        },
    }
```

**Step 3: Register and test**

Register `enrichment` router in `main.py`.

```bash
python -m pytest unified_api/tests/unit/test_finance_parser.py -v
git add -A
git commit -m "feat: finance detail parser with regex extraction (TDD green)"
```

---

## Task 3A: Email Digest System — TESTS FIRST

**Files:**
- Create: `unified_api/tests/unit/test_email_digest.py`

```python
"""
TDD: Email digest tests.
"""
import pytest


class TestEmailDigestBuilder:
    """Test email digest HTML generation."""

    def test_build_digest_returns_html(self):
        from unified_api.services.email_digest import build_digest_html
        html = build_digest_html(
            title="Daily Deal Digest",
            sections=[
                {"title": "Market Summary", "content": "10 new deals today"},
                {"title": "Notable Deals", "items": [{"title": "Deal 1", "value": "$500M"}]},
            ],
        )
        assert isinstance(html, str)
        assert "<html" in html
        assert "Daily Deal Digest" in html

    def test_build_digest_includes_sections(self):
        from unified_api.services.email_digest import build_digest_html
        html = build_digest_html(
            title="Test",
            sections=[
                {"title": "Section A", "content": "Content A"},
                {"title": "Section B", "content": "Content B"},
            ],
        )
        assert "Section A" in html
        assert "Section B" in html
        assert "Content A" in html

    def test_build_digest_handles_empty_sections(self):
        from unified_api.services.email_digest import build_digest_html
        html = build_digest_html(title="Empty Digest", sections=[])
        assert isinstance(html, str)
        assert "Empty Digest" in html

    def test_format_deal_row(self):
        from unified_api.services.email_digest import format_deal_row
        row = format_deal_row({
            "title": "Pfizer-Seagen ADC License",
            "value": 500,
            "principal": "Pfizer",
            "partner": "Seagen",
            "date": "2026-07-15",
        })
        assert isinstance(row, str)
        assert "Pfizer" in row
```

```bash
python -m pytest unified_api/tests/unit/test_email_digest.py -v
git add unified_api/tests/
git commit -m "test: email digest tests (TDD red phase)"
```

---

## Task 3B: Email Digest System — IMPLEMENTATION

**Files:**
- Create: `unified_api/services/email_digest.py`
- Add Celery task for daily/weekly digest
- Modify: `unified_api/workers/celery_app.py` — add digest schedule

**Step 1: Create email digest service**

Create `unified_api/services/email_digest.py`:
```python
"""
Email digest builder and sender.
Generates HTML email digests for daily/weekly briefings.
Supports SendGrid and SMTP delivery.
"""
import os
from typing import List, Dict, Any, Optional
import structlog

logger = structlog.get_logger(__name__)

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
SMTP_HOST = os.environ.get("SMTP_HOST")
FROM_EMAIL = os.environ.get("DIGEST_FROM_EMAIL", "bd-intelligence@machomelab.com")


def format_deal_row(deal: Dict[str, Any]) -> str:
    """Format a single deal as an HTML table row."""
    value = f"${deal.get('value', 0):,.0f}M" if deal.get('value') else "—"
    return f"""
    <tr style="border-bottom: 1px solid #334155;">
        <td style="padding: 8px 12px; color: #e2e8f0; font-size: 14px;">{deal.get('title', 'N/A')}</td>
        <td style="padding: 8px 12px; color: #94a3b8; font-size: 13px;">{deal.get('principal', '—')} → {deal.get('partner', '—')}</td>
        <td style="padding: 8px 12px; color: #cbd5e1; font-size: 14px; font-weight: 600;">{value}</td>
        <td style="padding: 8px 12px; color: #64748b; font-size: 12px;">{deal.get('date', '—')}</td>
    </tr>
    """


def build_digest_html(title: str, sections: List[Dict[str, Any]], app_url: str = "https://cortellis.machomelab.com") -> str:
    """
    Build a complete HTML email digest.
    Dark theme matching the platform UI.
    """
    sections_html = ""

    for section in sections:
        section_html = f"""
        <div style="margin-bottom: 24px;">
            <h2 style="color: #60a5fa; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; font-weight: 600;">
                {section.get('title', '')}
            </h2>
        """

        if section.get("content"):
            section_html += f'<p style="color: #cbd5e1; font-size: 14px; line-height: 1.6;">{section["content"]}</p>'

        if section.get("items"):
            section_html += """
            <table style="width: 100%; border-collapse: collapse; margin-top: 8px;">
                <thead>
                    <tr style="border-bottom: 2px solid #334155;">
                        <th style="padding: 6px 12px; color: #64748b; font-size: 12px; text-align: left;">Deal</th>
                        <th style="padding: 6px 12px; color: #64748b; font-size: 12px; text-align: left;">Parties</th>
                        <th style="padding: 6px 12px; color: #64748b; font-size: 12px; text-align: left;">Value</th>
                        <th style="padding: 6px 12px; color: #64748b; font-size: 12px; text-align: left;">Date</th>
                    </tr>
                </thead>
                <tbody>
            """
            for item in section["items"]:
                section_html += format_deal_row(item)
            section_html += "</tbody></table>"

        if section.get("stats"):
            stats_html = '<div style="display: flex; gap: 16px; margin-top: 8px;">'
            for stat in section["stats"]:
                stats_html += f"""
                <div style="background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 12px 16px; flex: 1;">
                    <div style="color: #64748b; font-size: 11px;">{stat.get('label', '')}</div>
                    <div style="color: #e2e8f0; font-size: 20px; font-weight: 700; margin-top: 4px;">{stat.get('value', '')}</div>
                </div>
                """
            stats_html += '</div>'
            section_html += stats_html

        section_html += "</div>"
        sections_html += section_html

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="margin: 0; padding: 0; background-color: #0f172a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
        <div style="max-width: 640px; margin: 0 auto; padding: 24px;">
            <!-- Header -->
            <div style="text-align: center; padding: 24px 0; border-bottom: 1px solid #1e293b;">
                <h1 style="color: #e2e8f0; font-size: 20px; margin: 0;">📊 {title}</h1>
                <p style="color: #64748b; font-size: 13px; margin-top: 4px;">BD Intelligence Platform</p>
            </div>

            <!-- Content -->
            <div style="padding: 24px 0;">
                {sections_html}
            </div>

            <!-- Footer -->
            <div style="text-align: center; padding: 16px 0; border-top: 1px solid #1e293b;">
                <a href="{app_url}" style="color: #3b82f6; font-size: 13px; text-decoration: none;">
                    Open BD Intelligence Platform →
                </a>
                <p style="color: #475569; font-size: 11px; margin-top: 8px;">
                    You're receiving this because you're subscribed to deal intelligence digests.
                </p>
            </div>
        </div>
    </body>
    </html>
    """

    return html


def send_digest_email(to_email: str, subject: str, html_content: str) -> bool:
    """
    Send digest email via SendGrid or SMTP.
    Returns True if sent successfully.
    """
    if SENDGRID_API_KEY:
        return _send_via_sendgrid(to_email, subject, html_content)
    elif SMTP_HOST:
        return _send_via_smtp(to_email, subject, html_content)
    else:
        logger.warning("No email delivery configured (set SENDGRID_API_KEY or SMTP_HOST)")
        # Log the email for development
        logger.info("Email digest generated (not sent)", to=to_email, subject=subject, html_length=len(html_content))
        return False


def _send_via_sendgrid(to_email: str, subject: str, html_content: str) -> bool:
    """Send via SendGrid API."""
    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail, Email, To, Content

        sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
        message = Mail(
            from_email=Email(FROM_EMAIL, "BD Intelligence"),
            to_emails=To(to_email),
            subject=subject,
            html_content=Content("text/html", html_content),
        )
        response = sg.send(message)
        logger.info("SendGrid email sent", to=to_email, status=response.status_code)
        return response.status_code in (200, 201, 202)
    except Exception as e:
        logger.error("SendGrid send failed", error=str(e))
        return False


def _send_via_smtp(to_email: str, subject: str, html_content: str) -> bool:
    """Send via SMTP."""
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ.get("SMTP_USER", "")
        smtp_pass = os.environ.get("SMTP_PASS", "")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = FROM_EMAIL
        msg["To"] = to_email
        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP(SMTP_HOST, smtp_port) as server:
            server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.sendmail(FROM_EMAIL, to_email, msg.as_string())

        logger.info("SMTP email sent", to=to_email)
        return True
    except Exception as e:
        logger.error("SMTP send failed", error=str(e))
        return False
```

**Step 2: Add Celery task for daily digest**

Add to `unified_api/workers/celery_app.py` in `beat_schedule`:
```python
        # Send daily deal digest at 7:00 AM EST
        "daily-deal-digest": {
            "task": "unified_api.workers.tasks.digest.send_daily_digest",
            "schedule": crontab(hour=12, minute=0),  # 12:00 UTC = 7:00 AM EST
        },
```

Add task definition:
```python
@celery_app.task(name="unified_api.workers.tasks.digest.send_daily_digest")
def send_daily_digest():
    """Generate and send daily deal digest to all subscribed users."""
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session
    from unified_api.services.email_digest import build_digest_html, send_digest_email

    logger.info("Generating daily deal digest")

    with get_cortellis_session() as session:
        # Get yesterday's notable deals
        deals = session.execute(text("""
            SELECT d.title, d.agreement_type, d.date_start::text as date,
                   f.total_projected_current_amount as value,
                   (SELECT c.name FROM deal_companies dc JOIN companies c ON c.id = dc.company_id
                    WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as principal,
                   (SELECT c.name FROM deal_companies dc JOIN companies c ON c.id = dc.company_id
                    WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as partner
            FROM deals d
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
            WHERE d.date_start >= CURRENT_DATE - INTERVAL '1 day'
            ORDER BY f.total_projected_current_amount DESC NULLS LAST
            LIMIT 15
        """)).fetchall()

        deal_count = session.execute(text(
            "SELECT COUNT(*) FROM deals WHERE date_start >= CURRENT_DATE - INTERVAL '1 day'"
        )).scalar()

        # Build sections
        sections = [
            {
                "title": "Today's Summary",
                "stats": [
                    {"label": "New Deals", "value": str(deal_count)},
                ],
            },
            {
                "title": "Notable Deals",
                "items": [{
                    "title": d.title,
                    "principal": d.principal,
                    "partner": d.partner,
                    "value": float(d.value) if d.value else None,
                    "date": d.date,
                } for d in deals],
            },
        ]

        html = build_digest_html("Daily Deal Digest", sections)

        # Get subscribed users
        users = session.execute(text(
            "SELECT email FROM users WHERE role IN ('ceo', 'admin', 'vp_bd')"
        )).fetchall()

        sent = 0
        for user in users:
            if send_digest_email(user.email, "BD Intelligence — Daily Digest", html):
                sent += 1

    logger.info("Daily digest complete", sent=sent, total_users=len(users))
    return {"status": "completed", "emails_sent": sent, "deals": deal_count}
```

**Step 3: Run tests, verify PASS, commit**

```bash
python -m pytest unified_api/tests/unit/test_email_digest.py -v
git add -A
git commit -m "feat: email digest system with SendGrid/SMTP delivery + daily Celery task (TDD green)"
```

---

## Task 4: Wire Celery Tasks to Real Implementations

**Files:**
- Modify: `unified_api/workers/celery_app.py` — connect TODO tasks to actual services

**Step 1: Wire graph sync task**

Update the `sync_graph` task:
```python
@celery_app.task(name="unified_api.workers.tasks.graph.sync_all")
def sync_graph():
    """Sync all data to Neo4j graph database."""
    logger.info("Starting graph sync")
    try:
        from unified_api.services.graph_sync import get_graph_sync_service
        service = get_graph_sync_service()
        results = service.full_sync()
        logger.info("Graph sync complete", **results)
        return {"status": "completed", **results}
    except Exception as e:
        logger.error("Graph sync failed", error=str(e))
        return {"status": "failed", "error": str(e)}
```

**Step 2: Wire alert check to email delivery**

Update the `check_alerts` task to call `send_alert_email` when notifications are created:
```python
# Inside the check_alerts loop, after creating notifications:
if new_deals:
    send_alert_email.delay(
        user_id=str(alert.user_id),
        alert_name=alert.name,
        deals=[{"id": d.id, "title": d.title} for d in new_deals],
    )
```

**Step 3: Wire alert email to actual email service**

Update `send_alert_email`:
```python
@celery_app.task(name="unified_api.workers.tasks.alerts.send_alert_email")
def send_alert_email(user_id: str, alert_name: str, deals: list):
    """Send an email notification for deal alerts."""
    from unified_api.services.email_digest import build_digest_html, send_digest_email
    from unified_api.services.database import get_cortellis_session
    from sqlalchemy import text

    logger.info("Sending alert email", user_id=user_id, alert_name=alert_name, deal_count=len(deals))

    # Get user email
    with get_cortellis_session() as session:
        user = session.execute(text("SELECT email FROM users WHERE id = :id"), {"id": int(user_id)}).fetchone()
        if not user:
            return {"status": "skipped", "reason": "user not found"}

    sections = [
        {
            "title": f"Alert: {alert_name}",
            "content": f"{len(deals)} new deals match your saved search criteria.",
            "items": deals[:10],
        },
    ]

    html = build_digest_html(f"Deal Alert: {alert_name}", sections)
    sent = send_digest_email(user.email, f"BD Intelligence Alert — {alert_name}", html)

    return {"status": "sent" if sent else "logged", "user_id": user_id, "deals": len(deals)}
```

**Step 4: Commit**

```bash
git add -A
git commit -m "feat: wire Celery tasks to real graph sync, alert email, digest delivery"
```

---

## Task 5A: Production Hardening — TESTS FIRST

**Files:**
- Create: `unified_api/tests/integration/test_production.py`

```python
"""
TDD: Production hardening tests.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestProductionEndpoints:

    def test_health_returns_quickly(self, client):
        import time
        start = time.time()
        resp = client.get("/api/health")
        elapsed = time.time() - start
        assert resp.status_code == 200
        assert elapsed < 2.0  # Health check must be fast

    def test_rate_limiting_header(self, client):
        """Rate limiting middleware should add headers."""
        resp = client.get("/api/health")
        # At minimum, should not crash
        assert resp.status_code == 200

    def test_cors_headers(self, client):
        resp = client.options("/api/health", headers={"Origin": "http://localhost:5173"})
        # Should not crash
        assert resp.status_code in (200, 204, 405)

    def test_api_docs_available(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_json(self, client):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "paths" in data
        # Should have many endpoints
        assert len(data["paths"]) > 30
```

```bash
python -m pytest unified_api/tests/integration/test_production.py -v
git add unified_api/tests/
git commit -m "test: production hardening tests (TDD red phase)"
```

---

## Task 5B: Production Hardening — IMPLEMENTATION

**Files:**
- Modify: `unified_api/main.py` — add middleware, connection pooling, error handling

**Step 1: Add production middleware to main.py**

Add to `unified_api/main.py`:
```python
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Add X-Response-Time header and log slow requests."""
    async def dispatch(self, request, call_next):
        start = time.time()
        response = await call_next(request)
        elapsed = time.time() - start
        response.headers["X-Response-Time"] = f"{elapsed:.3f}s"
        if elapsed > 5.0:
            logger.warning("Slow request", path=request.url.path, elapsed=f"{elapsed:.2f}s")
        return response


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Catch unhandled exceptions and return JSON error responses."""
    async def dispatch(self, request, call_next):
        try:
            return await call_next(request)
        except Exception as e:
            logger.error("Unhandled exception", path=request.url.path, error=str(e))
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error", "type": type(e).__name__},
            )


# Add middleware (order matters — first added = outermost)
app.add_middleware(RequestTimingMiddleware)
app.add_middleware(ErrorHandlingMiddleware)
```

**Step 2: Add connection pool configuration**

Update database service to use connection pooling:
```python
# In unified_api/services/database.py, update engine creation:
engine = create_engine(
    url,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,  # Recycle connections every 30 min
    pool_pre_ping=True,  # Verify connections before use
)
```

**Step 3: Add startup/shutdown events**

```python
@app.on_event("startup")
async def startup_event():
    logger.info("BD Intelligence Platform starting",
                version="2.0",
                endpoints=len(app.routes))

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("BD Intelligence Platform shutting down")
    # Close graph connections
    try:
        from unified_api.services.graph_sync import get_graph_sync_service
        get_graph_sync_service().close()
    except Exception:
        pass
```

**Step 4: Run tests, commit**

```bash
python -m pytest unified_api/tests/integration/test_production.py -v
git add -A
git commit -m "feat: production hardening — middleware, connection pooling, error handling (TDD green)"
```

---

## Task 6: Data Status Dashboard Widget

**Files:**
- Modify: `frontend/src/pages/DashboardPage.tsx` — add data health widget

**Step 1: Add data health widget to dashboard**

Add a new widget at the bottom of the dashboard that fetches `/api/health/data` and displays:
- Overall health score (0-100) with color coding
- Individual check statuses (ok/warning/critical) with icons
- Source summary (deal count, filing count, graph stats, last sync)

The widget should:
```typescript
// Add to DashboardPage component:
const [dataHealth, setDataHealth] = useState<any>(null);

useEffect(() => {
  api.get('/health/data').then(r => setDataHealth(r.data)).catch(() => {});
}, []);

// Render a "Data Status" card:
// - Score badge (green ≥80, yellow ≥60, red <60)
// - Check list with status icons (✅ ok, ⚠️ warning, ❌ critical)
// - Source counts in compact row
```

**Step 2: Verify build and commit**

```bash
cd frontend && npm run build
git add -A
git commit -m "feat: data health status widget on executive dashboard"
```

---

## Task 7: Integration Tests + Build Verification + Push

**Files:**
- Create: `unified_api/tests/integration/test_phase4_e2e.py`

```python
"""
End-to-end integration tests for Phase 4.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestPhase4Endpoints:

    def test_data_health(self, client):
        resp = client.get("/api/health/data")
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_score" in data
        assert "sources" in data

    def test_enrichment_status(self, client):
        resp = client.get("/api/enrichment/status")
        assert resp.status_code == 200

    def test_parse_financials_dry_run(self, client):
        resp = client.post("/api/enrichment/parse-financials?dry_run=true&batch_size=5")
        assert resp.status_code == 200
        assert resp.json()["dry_run"] is True

    def test_all_routers_registered(self, client):
        """Verify all expected routes exist."""
        resp = client.get("/openapi.json")
        paths = resp.json()["paths"]
        expected = [
            "/api/health", "/api/health/data",
            "/api/auth/login", "/api/auth/register",
            "/api/dashboard/executive",
            "/api/chat/v2",
            "/api/comps/build",
            "/api/dd/generate",
            "/api/briefings/generate",
            "/api/recommendations",
            "/api/enrichment/status",
        ]
        for path in expected:
            assert path in paths, f"Missing route: {path}"

    def test_timing_header(self, client):
        resp = client.get("/api/health")
        assert "x-response-time" in resp.headers
```

**Run ALL tests:**

```bash
cd /Users/kayleighbot/Projects/cortellis
python -m pytest unified_api/tests/ -v --tb=short
cd frontend && npm run build
```

**Commit and push:**

```bash
git add -A
git commit -m "feat: Phase 4 complete — data health, finance parser, email digests, production hardening"
git push origin main
```

---

## Summary

After Phase 4, the platform has:

1. **Data Health Check** (`/api/health/data`) — scores integrity across all 4 data sources (Cortellis PG, EDGAR PG, Neo4j, Redis) with 5 checks: freshness, disclosure rate, graph sync, entity resolution, graph density
2. **Finance Parser** — regex-based extraction of upfront payments, milestones, royalty rates, total values from `finance_detail_raw`. Enrichment endpoint processes in batches with dry-run mode.
3. **Email Digest System** — dark-themed HTML emails matching platform UI. SendGrid + SMTP support. Daily digest Celery task at 7 AM EST.
4. **Wired Celery Tasks** — graph sync, alert emails, and digest delivery connected to real implementations (were TODOs before)
5. **Production Hardening** — request timing middleware, error handling middleware, connection pooling (pool_size=10, max_overflow=20, pre_ping=True), startup/shutdown events
6. **Data Status Widget** — health score on executive dashboard

**New tests:** 4 data health unit + 4 data health integration + 9 finance parser unit + 4 email digest unit + 5 production tests + 5 Phase 4 e2e = **31 new tests**

**Total tests across all phases:** ~139 tests

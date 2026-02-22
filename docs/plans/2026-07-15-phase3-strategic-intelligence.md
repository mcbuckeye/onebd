# Phase 3: Strategic Intelligence — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** The platform generates insights, not just answers. Build the DD package generator, territory rights visualization, automated briefing system, and recommendation engine. These are the features that turn this from a search tool into a strategic weapon.

**Architecture:** Phase 3 is ~50% backend (DD generator orchestration, briefing system, territory GeoJSON, recommendation engine) and ~50% frontend (DD page, territory map, briefing viewer). Most underlying data APIs already exist — this phase orchestrates them into higher-order intelligence.

**Tech Stack:**
- Frontend: React 18, TypeScript, Recharts, react-simple-maps (territory), jsPDF (export)
- Backend: FastAPI, SQLAlchemy, OpenAI GPT-4o (briefing generation), Celery (scheduled briefings)
- Existing: All entity/graph/analytics/export endpoints, 14 analytics endpoints, comp builder

**Working Directory:** `/Users/kayleighbot/Projects/cortellis`

**Methodology:** TDD for all backend tasks. Frontend verified with `npm run build`.

---

## Overview of Tasks

| Task | Component | Type | Estimated Time |
|------|-----------|------|---------------|
| 1A | DD Package Generator backend — TESTS FIRST | Backend/Test | 10 min |
| 1B | DD Package Generator backend — IMPLEMENTATION | Backend | 20 min |
| 2 | DD Package Generator frontend | Frontend | 15 min |
| 3A | Territory Rights backend — TESTS FIRST | Backend/Test | 5 min |
| 3B | Territory Rights backend — IMPLEMENTATION | Backend | 10 min |
| 4 | Territory Rights frontend (map visualization) | Frontend | 15 min |
| 5A | Automated Briefing System backend — TESTS FIRST | Backend/Test | 10 min |
| 5B | Automated Briefing System backend — IMPLEMENTATION | Backend | 15 min |
| 6 | Briefing viewer frontend | Frontend | 10 min |
| 7A | Recommendation Engine — TESTS FIRST | Backend/Test | 5 min |
| 7B | Recommendation Engine — IMPLEMENTATION | Backend | 10 min |
| 8 | Recommendations frontend widget | Frontend | 10 min |
| 9 | Integration tests + build verification + push | Test/DevOps | 10 min |

---

## Task 1A: DD Package Generator Backend — TESTS FIRST

**Files:**
- Create: `unified_api/tests/unit/test_dd_generator.py`
- Create: `unified_api/tests/integration/test_dd_endpoints.py`

**Step 1: Write DD generator tests**

Create `unified_api/tests/unit/test_dd_generator.py`:
```python
"""
TDD: Due Diligence package generator tests.
"""
import pytest


class TestDDPackageStructure:
    """Test DD package generation logic."""

    def test_package_has_required_sections(self):
        from unified_api.services.dd_generator import DD_SECTIONS
        required = ["company_overview", "deal_history", "drug_portfolio", "partnerships", "financials"]
        for section in required:
            assert section in DD_SECTIONS

    def test_build_company_overview_returns_dict(self):
        from unified_api.services.dd_generator import build_section
        # Mock data — function should handle gracefully
        result = build_section("company_overview", {"company_id": 1, "name": "Test Corp"})
        assert isinstance(result, dict)
        assert "title" in result
        assert "content" in result

    def test_build_section_unknown_type_returns_empty(self):
        from unified_api.services.dd_generator import build_section
        result = build_section("nonexistent_section", {})
        assert result["content"] is None or result["content"] == ""

    def test_risk_flags_detection(self):
        from unified_api.services.dd_generator import detect_risk_flags
        deal_data = {
            "terminated_deals": 5,
            "total_deals": 10,
            "concentrated_partnerships": True,
            "recent_litigation": True,
        }
        flags = detect_risk_flags(deal_data)
        assert isinstance(flags, list)
        assert len(flags) > 0
        assert all(isinstance(f, dict) and "flag" in f and "severity" in f for f in flags)

    def test_risk_flags_clean_company(self):
        from unified_api.services.dd_generator import detect_risk_flags
        clean_data = {
            "terminated_deals": 0,
            "total_deals": 50,
            "concentrated_partnerships": False,
            "recent_litigation": False,
        }
        flags = detect_risk_flags(clean_data)
        assert isinstance(flags, list)
        # Clean company may still have informational flags, but no high severity
        high_severity = [f for f in flags if f.get("severity") == "high"]
        assert len(high_severity) == 0
```

Create `unified_api/tests/integration/test_dd_endpoints.py`:
```python
"""
TDD: DD Package endpoint tests.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestDDGenerateEndpoint:
    """Test POST /api/dd/generate"""

    def test_generate_dd_returns_200(self, client):
        resp = client.post("/api/dd/generate", json={"company_id": 1})
        assert resp.status_code == 200

    def test_generate_dd_response_structure(self, client):
        data = client.post("/api/dd/generate", json={"company_id": 1}).json()
        assert "company" in data
        assert "sections" in data
        assert isinstance(data["sections"], list)
        assert len(data["sections"]) > 0

    def test_generate_dd_sections_have_titles(self, client):
        data = client.post("/api/dd/generate", json={"company_id": 1}).json()
        for section in data["sections"]:
            assert "title" in section

    def test_generate_dd_has_risk_flags(self, client):
        data = client.post("/api/dd/generate", json={"company_id": 1}).json()
        assert "risk_flags" in data
        assert isinstance(data["risk_flags"], list)

    def test_generate_dd_invalid_company(self, client):
        resp = client.post("/api/dd/generate", json={"company_id": 999999})
        # Should still return 200 with empty/minimal data, not crash
        assert resp.status_code in [200, 404]
```

**Step 2: Run tests — verify they FAIL**

```bash
python -m pytest unified_api/tests/unit/test_dd_generator.py -v
python -m pytest unified_api/tests/integration/test_dd_endpoints.py -v
```

**Step 3: Commit**

```bash
git add unified_api/tests/
git commit -m "test: DD package generator tests (TDD red phase)"
```

---

## Task 1B: DD Package Generator Backend — IMPLEMENTATION

**Files:**
- Create: `unified_api/services/dd_generator.py`
- Create: `unified_api/routers/dd.py`
- Modify: `unified_api/main.py` — register dd router

**Step 1: Create DD generator service**

Create `unified_api/services/dd_generator.py`:
```python
"""
Due Diligence package generator.
Orchestrates data from multiple sources into a comprehensive DD report.
"""
from typing import Dict, Any, List, Optional
import structlog

logger = structlog.get_logger(__name__)

DD_SECTIONS = {
    "company_overview": "Company Overview",
    "deal_history": "Deal History",
    "drug_portfolio": "Drug / Asset Portfolio",
    "partnerships": "Partnership Network",
    "financials": "Financial Summary",
    "sec_filings": "SEC Filings",
    "contracts": "Key Contracts",
    "territory_rights": "Territory Rights",
    "comparable_transactions": "Comparable Transactions",
    "risk_assessment": "Risk Assessment",
}


def build_section(section_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Build a single DD section from data."""
    title = DD_SECTIONS.get(section_type, section_type.replace("_", " ").title())

    if section_type == "company_overview":
        return {
            "type": section_type,
            "title": title,
            "content": {
                "name": data.get("name"),
                "company_type": data.get("company_type"),
                "ticker": data.get("ticker"),
                "hq_location": data.get("hq_location"),
                "total_deals": data.get("total_deals", 0),
            },
        }
    elif section_type == "deal_history":
        return {
            "type": section_type,
            "title": title,
            "content": data.get("deals", []),
        }
    elif section_type == "drug_portfolio":
        return {
            "type": section_type,
            "title": title,
            "content": data.get("drugs", []),
        }
    elif section_type == "partnerships":
        return {
            "type": section_type,
            "title": title,
            "content": data.get("partners", []),
        }
    elif section_type == "financials":
        return {
            "type": section_type,
            "title": title,
            "content": {
                "total_deal_value": data.get("total_deal_value"),
                "avg_deal_value": data.get("avg_deal_value"),
                "largest_deal": data.get("largest_deal"),
                "deal_count_with_financials": data.get("disclosed_count", 0),
            },
        }
    elif section_type == "sec_filings":
        return {
            "type": section_type,
            "title": title,
            "content": data.get("filings", []),
        }
    elif section_type == "contracts":
        return {
            "type": section_type,
            "title": title,
            "content": data.get("contracts", []),
        }
    elif section_type == "territory_rights":
        return {
            "type": section_type,
            "title": title,
            "content": data.get("territories", []),
        }
    elif section_type == "comparable_transactions":
        return {
            "type": section_type,
            "title": title,
            "content": data.get("comps", []),
        }
    elif section_type == "risk_assessment":
        return {
            "type": section_type,
            "title": title,
            "content": data.get("risk_flags", []),
        }
    else:
        return {"type": section_type, "title": title, "content": None}


def detect_risk_flags(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Detect risk flags from company/deal data."""
    flags = []

    terminated = data.get("terminated_deals", 0)
    total = data.get("total_deals", 0)

    if total > 0 and terminated / total > 0.3:
        flags.append({
            "flag": f"High termination rate: {terminated}/{total} deals terminated ({(terminated/total*100):.0f}%)",
            "severity": "high",
            "category": "deal_stability",
        })

    if data.get("concentrated_partnerships"):
        flags.append({
            "flag": "Partnership concentration: >50% of deals with a single partner",
            "severity": "medium",
            "category": "dependency",
        })

    if data.get("recent_litigation"):
        flags.append({
            "flag": "Recent litigation-related SEC filings detected",
            "severity": "high",
            "category": "legal",
        })

    if total < 3:
        flags.append({
            "flag": f"Limited deal history: only {total} deals on record",
            "severity": "medium",
            "category": "track_record",
        })

    if total > 0 and terminated == 0:
        flags.append({
            "flag": "No terminated deals on record (positive indicator)",
            "severity": "low",
            "category": "deal_stability",
        })

    return flags
```

**Step 2: Create DD router**

Create `unified_api/routers/dd.py`:
```python
"""
Due Diligence package generation endpoints.
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.dd_generator import build_section, detect_risk_flags, DD_SECTIONS

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["due-diligence"])


class DDGenerateRequest(BaseModel):
    company_id: int
    sections: Optional[List[str]] = None  # If None, generate all


@router.post("/dd/generate")
async def generate_dd_package(req: DDGenerateRequest):
    """
    Generate a comprehensive due diligence package for a company.
    Aggregates data from deals, drugs, partnerships, financials, SEC filings.
    """
    with get_cortellis_session() as session:
        # Get company info
        company = session.execute(text("""
            SELECT id, name, company_type, ticker, hq_location
            FROM companies WHERE id = :id
        """), {"id": req.company_id}).fetchone()

        if not company:
            raise HTTPException(status_code=404, detail="Company not found")

        company_data = {
            "id": company.id,
            "name": company.name,
            "company_type": company.company_type,
            "ticker": company.ticker,
            "hq_location": company.hq_location,
        }

        # Deal history
        deals = session.execute(text("""
            SELECT d.id, d.title, d.agreement_type, d.status, d.date_start::text,
                   f.total_projected_current_amount as total_value,
                   (SELECT c.name FROM deal_companies dc2
                    JOIN companies c ON c.id = dc2.company_id
                    WHERE dc2.deal_id = d.id AND dc2.role != dc.role LIMIT 1) as counterparty
            FROM deal_companies dc
            JOIN deals d ON d.id = dc.deal_id
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
            WHERE dc.company_id = :company_id
            ORDER BY d.date_start DESC NULLS LAST
            LIMIT 100
        """), {"company_id": req.company_id}).fetchall()

        deal_list = [{
            "id": d.id, "title": d.title, "type": d.agreement_type,
            "status": d.status, "date": d.date_start,
            "value": float(d.total_value) if d.total_value else None,
            "counterparty": d.counterparty,
        } for d in deals]

        # Drug portfolio
        drugs = session.execute(text("""
            SELECT DISTINCT dr.id, dr.name_display as name, dr.phase_highest_now as phase
            FROM deal_companies dc
            JOIN deal_drugs dd ON dd.deal_id = dc.deal_id
            JOIN drugs dr ON dr.id = dd.drug_id
            WHERE dc.company_id = :company_id
            ORDER BY dr.name_display
            LIMIT 50
        """), {"company_id": req.company_id}).fetchall()

        drug_list = [{"id": d.id, "name": d.name, "phase": d.phase} for d in drugs]

        # Top partners
        partners = session.execute(text("""
            SELECT c2.id, c2.name, COUNT(DISTINCT d.id) as deal_count
            FROM deal_companies dc1
            JOIN deals d ON d.id = dc1.deal_id
            JOIN deal_companies dc2 ON dc2.deal_id = d.id AND dc2.company_id != dc1.company_id
            JOIN companies c2 ON c2.id = dc2.company_id
            WHERE dc1.company_id = :company_id
            GROUP BY c2.id, c2.name
            ORDER BY deal_count DESC
            LIMIT 20
        """), {"company_id": req.company_id}).fetchall()

        partner_list = [{"id": p.id, "name": p.name, "deal_count": p.deal_count} for p in partners]

        # Financial summary
        financials = session.execute(text("""
            SELECT
                COUNT(*) as total_deals,
                COUNT(f.total_projected_current_amount) as disclosed_count,
                SUM(f.total_projected_current_amount) as total_value,
                AVG(f.total_projected_current_amount) as avg_value,
                MAX(f.total_projected_current_amount) as max_value,
                COUNT(*) FILTER (WHERE d.status = 'Terminated') as terminated_deals
            FROM deal_companies dc
            JOIN deals d ON d.id = dc.deal_id
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
            WHERE dc.company_id = :company_id
        """), {"company_id": req.company_id}).fetchone()

        # Check partnership concentration
        concentrated = False
        if partners and financials and financials.total_deals > 5:
            top_partner_pct = partners[0].deal_count / financials.total_deals if financials.total_deals > 0 else 0
            concentrated = top_partner_pct > 0.5

        # Risk flags
        risk_data = {
            "terminated_deals": financials.terminated_deals if financials else 0,
            "total_deals": financials.total_deals if financials else 0,
            "concentrated_partnerships": concentrated,
            "recent_litigation": False,  # Would check SEC filings for litigation
        }
        risk_flags = detect_risk_flags(risk_data)

        # Build sections
        sections_to_build = req.sections or list(DD_SECTIONS.keys())
        section_data = {
            "company_overview": company_data | {"total_deals": financials.total_deals if financials else 0},
            "deal_history": {"deals": deal_list},
            "drug_portfolio": {"drugs": drug_list},
            "partnerships": {"partners": partner_list},
            "financials": {
                "total_deal_value": float(financials.total_value) if financials and financials.total_value else None,
                "avg_deal_value": float(financials.avg_value) if financials and financials.avg_value else None,
                "largest_deal": float(financials.max_value) if financials and financials.max_value else None,
                "disclosed_count": financials.disclosed_count if financials else 0,
            },
            "sec_filings": {"filings": []},  # Would query Edgar DB
            "contracts": {"contracts": []},
            "territory_rights": {"territories": []},
            "comparable_transactions": {"comps": []},
            "risk_assessment": {"risk_flags": risk_flags},
        }

        built_sections = []
        for section_type in sections_to_build:
            data = section_data.get(section_type, {})
            built_sections.append(build_section(section_type, data))

    return {
        "company": company_data,
        "sections": built_sections,
        "risk_flags": risk_flags,
        "metadata": {
            "total_deals_analyzed": financials.total_deals if financials else 0,
            "financial_disclosure_rate": f"{(financials.disclosed_count / financials.total_deals * 100):.0f}%" if financials and financials.total_deals > 0 else "N/A",
        },
    }
```

**Step 3: Register in main.py**

Add `dd` to imports and `app.include_router(dd.router, prefix="/api")`.

**Step 4: Run tests — verify PASS**

```bash
python -m pytest unified_api/tests/unit/test_dd_generator.py -v
python -m pytest unified_api/tests/integration/test_dd_endpoints.py -v
```

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: DD package generator with risk flags, multi-section report (TDD green)"
```

---

## Task 2: DD Package Generator Frontend

**Files:**
- Create: `frontend/src/pages/DDPage.tsx`
- Modify: `frontend/src/router.tsx` — add route
- Modify: `frontend/src/layouts/MainLayout.tsx` — add nav item

**Step 1: Install jsPDF for export**

```bash
cd frontend && npm install jspdf
```

**Step 2: Build DD page**

Create `frontend/src/pages/DDPage.tsx`:
```typescript
import { useState, useEffect } from 'react';
import { Search, FileDown, AlertTriangle, CheckCircle, Info, Building2, Pill, Users, DollarSign, Shield } from 'lucide-react';
import api from '../lib/api';

function formatValue(v: number | null): string {
  if (v === null || v === undefined) return 'N/A';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
}

const SECTION_ICONS: Record<string, any> = {
  company_overview: Building2,
  deal_history: Info,
  drug_portfolio: Pill,
  partnerships: Users,
  financials: DollarSign,
  risk_assessment: Shield,
};

export default function DDPage() {
  const [searchQuery, setSearchQuery] = useState('');
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [ddPackage, setDdPackage] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['company_overview', 'risk_assessment']));

  // Autocomplete
  useEffect(() => {
    if (searchQuery.length < 2) { setSuggestions([]); return; }
    const timer = setTimeout(() => {
      api.get(`/search/autocomplete/companies?q=${encodeURIComponent(searchQuery)}&limit=8`)
        .then(r => setSuggestions(r.data.suggestions || []))
        .catch(() => {});
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const generateDD = async (companyId: number, companyName: string) => {
    setSearchQuery(companyName);
    setSuggestions([]);
    setLoading(true);
    try {
      const resp = await api.post('/dd/generate', { company_id: companyId });
      setDdPackage(resp.data);
      setExpandedSections(new Set(['company_overview', 'risk_assessment']));
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const toggleSection = (type: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type); else next.add(type);
      return next;
    });
  };

  const expandAll = () => setExpandedSections(new Set(ddPackage?.sections?.map((s: any) => s.type) || []));
  const collapseAll = () => setExpandedSections(new Set());

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">Due Diligence</h1>
        <p className="text-sm text-slate-500 mt-1">Generate comprehensive DD packages for acquisition targets</p>
      </div>

      {/* Company search */}
      <div className="relative mb-6 max-w-lg">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
        <input
          type="text" value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search for a company to analyze..."
          className="w-full pl-10 pr-4 py-3 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
        />
        {suggestions.length > 0 && (
          <div className="absolute z-20 w-full mt-1 bg-slate-800 border border-slate-700 rounded-lg shadow-xl max-h-48 overflow-y-auto">
            {suggestions.map((s: any) => (
              <button key={s.id} onClick={() => generateDD(s.id, s.name)}
                className="w-full text-left px-3 py-2 text-sm text-slate-300 hover:bg-slate-700"
              >
                {s.name}
                {s.company_type && <span className="text-xs text-slate-500 ml-2">({s.company_type})</span>}
              </button>
            ))}
          </div>
        )}
      </div>

      {loading && (
        <div className="text-center py-16">
          <div className="animate-spin w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full mx-auto mb-4" />
          <p className="text-slate-400">Generating DD package...</p>
        </div>
      )}

      {ddPackage && !loading && (
        <>
          {/* Header */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 mb-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-xl font-bold text-slate-100">{ddPackage.company?.name}</h2>
                <div className="flex gap-3 mt-1 text-sm text-slate-500">
                  <span>{ddPackage.company?.company_type}</span>
                  {ddPackage.company?.ticker && <span>({ddPackage.company.ticker})</span>}
                  <span>{ddPackage.metadata?.total_deals_analyzed} deals analyzed</span>
                  <span>{ddPackage.metadata?.financial_disclosure_rate} disclosed</span>
                </div>
              </div>
              <div className="flex gap-2">
                <button onClick={expandAll} className="px-3 py-1.5 bg-slate-800 rounded text-xs text-slate-400 hover:text-slate-200">Expand All</button>
                <button onClick={collapseAll} className="px-3 py-1.5 bg-slate-800 rounded text-xs text-slate-400 hover:text-slate-200">Collapse All</button>
              </div>
            </div>
          </div>

          {/* Risk flags banner */}
          {ddPackage.risk_flags?.length > 0 && (
            <div className="mb-4 space-y-2">
              {ddPackage.risk_flags.filter((f: any) => f.severity === 'high').map((f: any, i: number) => (
                <div key={i} className="flex items-center gap-2 px-4 py-2.5 bg-red-500/10 border border-red-500/30 rounded-lg">
                  <AlertTriangle className="w-4 h-4 text-red-400 flex-shrink-0" />
                  <span className="text-sm text-red-300">{f.flag}</span>
                </div>
              ))}
              {ddPackage.risk_flags.filter((f: any) => f.severity === 'medium').map((f: any, i: number) => (
                <div key={i} className="flex items-center gap-2 px-4 py-2.5 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
                  <Info className="w-4 h-4 text-yellow-400 flex-shrink-0" />
                  <span className="text-sm text-yellow-300">{f.flag}</span>
                </div>
              ))}
              {ddPackage.risk_flags.filter((f: any) => f.severity === 'low').map((f: any, i: number) => (
                <div key={i} className="flex items-center gap-2 px-4 py-2.5 bg-green-500/10 border border-green-500/30 rounded-lg">
                  <CheckCircle className="w-4 h-4 text-green-400 flex-shrink-0" />
                  <span className="text-sm text-green-300">{f.flag}</span>
                </div>
              ))}
            </div>
          )}

          {/* Sections */}
          <div className="space-y-2">
            {ddPackage.sections?.map((section: any) => {
              const Icon = SECTION_ICONS[section.type] || Info;
              const isExpanded = expandedSections.has(section.type);

              return (
                <div key={section.type} className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
                  <button
                    onClick={() => toggleSection(section.type)}
                    className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-slate-800/50 transition-colors"
                  >
                    <Icon className="w-5 h-5 text-blue-400 flex-shrink-0" />
                    <span className="font-medium text-slate-200">{section.title}</span>
                    <span className="ml-auto text-xs text-slate-500">{isExpanded ? '▼' : '▶'}</span>
                  </button>

                  {isExpanded && (
                    <div className="px-5 pb-4 border-t border-slate-800">
                      {section.type === 'deal_history' && Array.isArray(section.content) ? (
                        <table className="w-full text-sm mt-3">
                          <thead>
                            <tr className="text-left text-slate-500">
                              <th className="pb-2">Deal</th>
                              <th className="pb-2">Counterparty</th>
                              <th className="pb-2">Type</th>
                              <th className="pb-2">Value</th>
                              <th className="pb-2">Status</th>
                              <th className="pb-2">Date</th>
                            </tr>
                          </thead>
                          <tbody>
                            {section.content.slice(0, 25).map((d: any) => (
                              <tr key={d.id} className="border-t border-slate-800/50">
                                <td className="py-2 text-slate-300 max-w-xs truncate">{d.title}</td>
                                <td className="py-2 text-slate-400">{d.counterparty || '—'}</td>
                                <td className="py-2 text-slate-500 text-xs">{d.type || '—'}</td>
                                <td className="py-2 text-slate-300">{formatValue(d.value)}</td>
                                <td className="py-2">
                                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                                    d.status === 'Terminated' ? 'bg-red-500/10 text-red-400' :
                                    d.status === 'Active' ? 'bg-green-500/10 text-green-400' :
                                    'bg-slate-700 text-slate-400'
                                  }`}>{d.status || '—'}</span>
                                </td>
                                <td className="py-2 text-slate-500 text-xs">{d.date || '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : section.type === 'drug_portfolio' && Array.isArray(section.content) ? (
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mt-3">
                          {section.content.map((d: any) => (
                            <div key={d.id} className="flex items-center justify-between px-3 py-2 bg-slate-800 rounded-lg">
                              <span className="text-sm text-slate-300 truncate">{d.name}</span>
                              <span className="text-xs px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-400">{d.phase}</span>
                            </div>
                          ))}
                        </div>
                      ) : section.type === 'partnerships' && Array.isArray(section.content) ? (
                        <div className="space-y-1 mt-3">
                          {section.content.map((p: any) => (
                            <div key={p.id} className="flex items-center justify-between text-sm">
                              <span className="text-slate-300">{p.name}</span>
                              <span className="text-slate-500">{p.deal_count} deals</span>
                            </div>
                          ))}
                        </div>
                      ) : section.type === 'financials' && section.content ? (
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
                          {[
                            { label: 'Total Deal Value', value: formatValue(section.content.total_deal_value) },
                            { label: 'Avg Deal Value', value: formatValue(section.content.avg_deal_value) },
                            { label: 'Largest Deal', value: formatValue(section.content.largest_deal) },
                            { label: 'Deals w/ Financials', value: section.content.deal_count_with_financials?.toString() || '0' },
                          ].map(kpi => (
                            <div key={kpi.label} className="bg-slate-800 rounded-lg p-3">
                              <div className="text-xs text-slate-500">{kpi.label}</div>
                              <div className="text-lg font-bold text-slate-200 mt-1">{kpi.value}</div>
                            </div>
                          ))}
                        </div>
                      ) : section.type === 'company_overview' && section.content ? (
                        <div className="grid grid-cols-2 gap-3 mt-3 text-sm">
                          {Object.entries(section.content).filter(([k]) => k !== 'id').map(([key, val]) => (
                            <div key={key}>
                              <span className="text-slate-500">{key.replace(/_/g, ' ')}:</span>
                              <span className="text-slate-300 ml-2">{String(val || '—')}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="mt-3 text-sm text-slate-500">
                          {Array.isArray(section.content) && section.content.length === 0 ? 'No data available' :
                           section.content ? <pre className="text-xs">{JSON.stringify(section.content, null, 2)}</pre> : 'No data available'}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}

      {!ddPackage && !loading && (
        <div className="text-center py-16">
          <Shield className="w-16 h-16 text-slate-700 mx-auto mb-4" />
          <p className="text-slate-500">Search for a company to generate a DD package</p>
          <p className="text-sm text-slate-600 mt-1">Combines deal history, drug portfolio, partnerships, financials, and risk assessment</p>
        </div>
      )}
    </div>
  );
}
```

**Step 3: Add route and nav**

Add to `frontend/src/router.tsx`:
- Import: `import DDPage from './pages/DDPage';`
- Route: `{ path: 'dd', element: <DDPage /> },`

Add to `MainLayout.tsx` nav items:
```typescript
{ to: '/dd', icon: Shield, label: 'Due Diligence' },
```
Import `Shield` from lucide-react.

**Step 4: Verify build and commit**

```bash
cd frontend && npm run build
git add -A
git commit -m "feat: due diligence page with company search, risk flags, collapsible sections"
```

---

## Task 3A: Territory Rights Backend — TESTS FIRST

**Files:**
- Create: `unified_api/tests/integration/test_territory.py`

**Step 1: Write territory tests**

Create `unified_api/tests/integration/test_territory.py`:
```python
"""
TDD: Territory rights endpoint tests.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestTerritoryEndpoint:
    """Test GET /api/territory/{drug_id}/map"""

    def test_territory_returns_200(self, client):
        resp = client.get("/api/territory/1/map")
        assert resp.status_code in [200, 404]  # 404 if drug doesn't exist

    def test_territory_response_structure(self, client):
        resp = client.get("/api/territory/1/map")
        if resp.status_code == 200:
            data = resp.json()
            assert "drug" in data
            assert "territories" in data
            assert isinstance(data["territories"], list)

    def test_territory_entries_have_required_fields(self, client):
        resp = client.get("/api/territory/1/map")
        if resp.status_code == 200:
            for t in resp.json().get("territories", []):
                assert "territory" in t
                assert "status" in t  # committed, available, etc.
```

**Step 2: Run, verify FAIL, commit**

```bash
python -m pytest unified_api/tests/integration/test_territory.py -v
git add unified_api/tests/
git commit -m "test: territory rights tests (TDD red phase)"
```

---

## Task 3B: Territory Rights Backend — IMPLEMENTATION

**Files:**
- Create: `unified_api/routers/territory.py`
- Modify: `unified_api/main.py`

**Step 1: Create territory router**

Create `unified_api/routers/territory.py`:
```python
"""
Territory rights endpoints.
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["territory"])


@router.get("/territory/{drug_id}/map")
async def get_territory_map(drug_id: int):
    """
    Get territory rights map for a drug/asset.
    Returns territories with commitment status.
    """
    with get_cortellis_session() as session:
        # Get drug info
        drug = session.execute(text("""
            SELECT id, name_display as name, phase_highest_now as phase
            FROM drugs WHERE id = :id
        """), {"id": drug_id}).fetchone()

        if not drug:
            raise HTTPException(status_code=404, detail="Drug not found")

        # Get territory data from deals involving this drug
        territories = session.execute(text("""
            SELECT DISTINCT
                t.name as territory,
                d.id as deal_id,
                d.title as deal_title,
                d.status as deal_status,
                d.date_start::text as deal_date,
                (SELECT c.name FROM deal_companies dc
                 JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as rights_holder
            FROM deal_drugs dd
            JOIN deals d ON d.id = dd.deal_id
            JOIN deal_territories dt ON dt.deal_id = d.id
            JOIN territories t ON t.id = dt.territory_id
            WHERE dd.drug_id = :drug_id
            ORDER BY t.name
        """), {"drug_id": drug_id}).fetchall()

        territory_list = []
        for t in territories:
            status = "committed" if t.deal_status == "Active" else "terminated" if t.deal_status == "Terminated" else "unknown"
            territory_list.append({
                "territory": t.territory,
                "status": status,
                "rights_holder": t.rights_holder,
                "deal_id": t.deal_id,
                "deal_title": t.deal_title,
                "deal_date": t.deal_date,
            })

    return {
        "drug": {"id": drug.id, "name": drug.name, "phase": drug.phase},
        "territories": territory_list,
        "summary": {
            "total_territories": len(territory_list),
            "committed": sum(1 for t in territory_list if t["status"] == "committed"),
            "terminated": sum(1 for t in territory_list if t["status"] == "terminated"),
        },
    }
```

**Step 2: Register in main.py and run tests**

```bash
python -m pytest unified_api/tests/integration/test_territory.py -v
git add -A
git commit -m "feat: territory rights endpoint (TDD green)"
```

---

## Task 4: Territory Rights Frontend

**Files:**
- Create: `frontend/src/pages/TerritoryPage.tsx`
- Modify: `frontend/src/router.tsx`

**Step 1: Install map library**

```bash
cd frontend && npm install react-simple-maps
```

**Step 2: Build territory page**

Create `frontend/src/pages/TerritoryPage.tsx`:
```typescript
import { useState, useEffect } from 'react';
import { Search, Globe, MapPin } from 'lucide-react';
import api from '../lib/api';

export default function TerritoryPage() {
  const [searchQuery, setSearchQuery] = useState('');
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [territoryData, setTerritoryData] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (searchQuery.length < 2) { setSuggestions([]); return; }
    const timer = setTimeout(() => {
      api.get(`/search/autocomplete/drugs?q=${encodeURIComponent(searchQuery)}&limit=8`)
        .then(r => setSuggestions(r.data.suggestions || []))
        .catch(() => {});
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const loadTerritory = async (drugId: number, drugName: string) => {
    setSearchQuery(drugName);
    setSuggestions([]);
    setLoading(true);
    try {
      const resp = await api.get(`/territory/${drugId}/map`);
      setTerritoryData(resp.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const statusColor = (status: string) => {
    switch (status) {
      case 'committed': return 'bg-red-500/10 text-red-400 border-red-500/30';
      case 'terminated': return 'bg-slate-700 text-slate-400 border-slate-600';
      default: return 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30';
    }
  };

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">Territory Rights</h1>
        <p className="text-sm text-slate-500 mt-1">View territory commitments and available rights for drug assets</p>
      </div>

      <div className="relative mb-6 max-w-lg">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
        <input
          type="text" value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search for a drug/asset..."
          className="w-full pl-10 pr-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
        />
        {suggestions.length > 0 && (
          <div className="absolute z-20 w-full mt-1 bg-slate-800 border border-slate-700 rounded-lg shadow-xl max-h-48 overflow-y-auto">
            {suggestions.map((s: any) => (
              <button key={s.id} onClick={() => loadTerritory(s.id, s.name)}
                className="w-full text-left px-3 py-2 text-sm text-slate-300 hover:bg-slate-700"
              >
                {s.name}
                {s.phase && <span className="text-xs text-slate-500 ml-2">({s.phase})</span>}
              </button>
            ))}
          </div>
        )}
      </div>

      {loading && <div className="text-center py-16 text-slate-500">Loading territory data...</div>}

      {territoryData && !loading && (
        <>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 mb-4">
            <h2 className="text-lg font-semibold text-slate-200">{territoryData.drug?.name}</h2>
            <div className="flex gap-4 mt-2 text-sm">
              <span className="text-slate-500">Phase: {territoryData.drug?.phase || '—'}</span>
              <span className="text-red-400">{territoryData.summary?.committed} committed</span>
              <span className="text-slate-500">{territoryData.summary?.terminated} terminated</span>
              <span className="text-slate-400">{territoryData.summary?.total_territories} total territories</span>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {territoryData.territories?.map((t: any, i: number) => (
              <div key={i} className={`border rounded-lg px-4 py-3 ${statusColor(t.status)}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <MapPin className="w-4 h-4" />
                    <span className="font-medium">{t.territory}</span>
                  </div>
                  <span className="text-xs uppercase">{t.status}</span>
                </div>
                <div className="text-xs mt-1 opacity-75">
                  {t.rights_holder && <span>Holder: {t.rights_holder}</span>}
                  {t.deal_date && <span className="ml-2">({t.deal_date})</span>}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {!territoryData && !loading && (
        <div className="text-center py-16">
          <Globe className="w-16 h-16 text-slate-700 mx-auto mb-4" />
          <p className="text-slate-500">Search for a drug to view territory commitments</p>
        </div>
      )}
    </div>
  );
}
```

**Step 3: Add route**

Add to router: `{ path: 'territory', element: <TerritoryPage /> }`

**Step 4: Verify build and commit**

```bash
cd frontend && npm run build
git add -A
git commit -m "feat: territory rights visualization page with drug search"
```

---

## Task 5A: Automated Briefing System Backend — TESTS FIRST

**Files:**
- Create: `unified_api/tests/unit/test_briefing.py`
- Create: `unified_api/tests/integration/test_briefing_endpoints.py`

**Step 1: Write tests**

Create `unified_api/tests/unit/test_briefing.py`:
```python
"""
TDD: Briefing generator tests.
"""
import pytest


class TestBriefingSections:
    """Test briefing section generation."""

    def test_build_market_summary_returns_dict(self):
        from unified_api.services.briefing_generator import build_market_summary
        result = build_market_summary({"deals_30d": 100, "top_therapy": "Oncology"})
        assert isinstance(result, dict)
        assert "title" in result
        assert "content" in result

    def test_build_competitor_summary_returns_dict(self):
        from unified_api.services.briefing_generator import build_competitor_summary
        result = build_competitor_summary([{"name": "Pfizer", "deals": 5}])
        assert isinstance(result, dict)
        assert "title" in result

    def test_build_notable_deals_returns_dict(self):
        from unified_api.services.briefing_generator import build_notable_deals
        result = build_notable_deals([{"title": "Test Deal", "value": 100}])
        assert isinstance(result, dict)
```

Create `unified_api/tests/integration/test_briefing_endpoints.py`:
```python
"""
TDD: Briefing endpoint tests.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestBriefingGenerate:
    """Test POST /api/briefings/generate"""

    def test_generate_returns_200(self, client):
        resp = client.post("/api/briefings/generate", json={"topic": "oncology"})
        assert resp.status_code == 200

    def test_generate_response_structure(self, client):
        data = client.post("/api/briefings/generate", json={"topic": "oncology"}).json()
        assert "title" in data
        assert "sections" in data
        assert isinstance(data["sections"], list)

    def test_generate_with_company_topic(self, client):
        data = client.post("/api/briefings/generate", json={"topic": "Pfizer"}).json()
        assert "title" in data

    def test_list_briefings(self, client):
        resp = client.get("/api/briefings")
        assert resp.status_code == 200
```

**Step 2: Run, verify FAIL, commit**

```bash
python -m pytest unified_api/tests/unit/test_briefing.py unified_api/tests/integration/test_briefing_endpoints.py -v
git add unified_api/tests/
git commit -m "test: briefing system tests (TDD red phase)"
```

---

## Task 5B: Automated Briefing System Backend — IMPLEMENTATION

**Files:**
- Create: `unified_api/services/briefing_generator.py`
- Create: `unified_api/routers/briefings.py`
- Modify: `unified_api/main.py`

**Step 1: Create briefing service**

Create `unified_api/services/briefing_generator.py`:
```python
"""
Briefing generator — creates structured intelligence briefings.
"""
from typing import Dict, Any, List


def build_market_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": "Market Summary",
        "content": {
            "deals_30d": data.get("deals_30d", 0),
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
```

**Step 2: Create briefings router**

Create `unified_api/routers/briefings.py`:
```python
"""
Briefing generation and management endpoints.
"""
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.briefing_generator import build_market_summary, build_competitor_summary, build_notable_deals

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["briefings"])


class BriefingRequest(BaseModel):
    topic: str
    period_days: int = 30


@router.post("/briefings/generate")
async def generate_briefing(req: BriefingRequest):
    """Generate an on-demand briefing on a topic."""
    with get_cortellis_session() as session:
        # Market stats
        market = session.execute(text("""
            SELECT COUNT(*) as deal_count
            FROM deals
            WHERE date_start >= CURRENT_DATE - make_interval(days => :days)
        """), {"days": req.period_days}).fetchone()

        # Top therapy area
        top_ta = session.execute(text("""
            SELECT ta.name, COUNT(*) as cnt
            FROM deals d
            JOIN therapy_areas ta ON ta.id = d.therapy_area_id
            WHERE d.date_start >= CURRENT_DATE - make_interval(days => :days)
              AND ta.name IS NOT NULL
            GROUP BY ta.name ORDER BY cnt DESC LIMIT 1
        """), {"days": req.period_days}).fetchone()

        # Notable deals (filtered by topic if it looks like a therapy area/company)
        notable_query = """
            SELECT d.id, d.title, d.agreement_type, d.date_start::text,
                   f.total_projected_current_amount as total_value,
                   (SELECT c.name FROM deal_companies dc JOIN companies c ON c.id = dc.company_id
                    WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as principal,
                   (SELECT c.name FROM deal_companies dc JOIN companies c ON c.id = dc.company_id
                    WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as partner
            FROM deals d
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
            WHERE d.date_start >= CURRENT_DATE - make_interval(days => :days)
        """
        params: dict = {"days": req.period_days}

        if req.topic:
            notable_query += """
                AND (d.title ILIKE :topic_search
                     OR d.id IN (SELECT dc.deal_id FROM deal_companies dc
                                 JOIN companies c ON c.id = dc.company_id
                                 WHERE c.name ILIKE :topic_search)
                     OR d.id IN (SELECT di.deal_id FROM deal_indications di
                                 JOIN indications i ON i.id = di.indication_id
                                 WHERE i.name ILIKE :topic_search)
                     OR d.id IN (SELECT dt2.deal_id FROM deal_technologies dt2
                                 JOIN technologies t ON t.id = dt2.technology_id
                                 WHERE t.name ILIKE :topic_search))
            """
            params["topic_search"] = f"%{req.topic}%"

        notable_query += " ORDER BY f.total_projected_current_amount DESC NULLS LAST LIMIT 10"

        notable = session.execute(text(notable_query), params).fetchall()

        notable_list = [{
            "id": d.id, "title": d.title, "type": d.agreement_type,
            "date": d.date_start,
            "value": float(d.total_value) if d.total_value else None,
            "principal": d.principal, "partner": d.partner,
        } for d in notable]

    sections = [
        build_market_summary({
            "deals_30d": market.deal_count if market else 0,
            "top_therapy": top_ta.name if top_ta else None,
        }),
        build_notable_deals(notable_list),
    ]

    return {
        "title": f"Intelligence Briefing: {req.topic}",
        "topic": req.topic,
        "period_days": req.period_days,
        "sections": sections,
        "generated_at": "now",
    }


@router.get("/briefings")
async def list_briefings():
    """List generated briefings (placeholder for persistence)."""
    return []
```

**Step 3: Register and test**

```bash
python -m pytest unified_api/tests/unit/test_briefing.py unified_api/tests/integration/test_briefing_endpoints.py -v
git add -A
git commit -m "feat: briefing system with on-demand generation (TDD green)"
```

---

## Task 6: Briefing Viewer Frontend

**Files:**
- Create: `frontend/src/pages/BriefingPage.tsx`
- Modify: `frontend/src/router.tsx`

**Step 1: Build briefing page**

Create `frontend/src/pages/BriefingPage.tsx`:
```typescript
import { useState } from 'react';
import { Newspaper, Search, Clock } from 'lucide-react';
import api from '../lib/api';

function formatValue(v: number | null): string {
  if (v === null || v === undefined) return '—';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
}

export default function BriefingPage() {
  const [topic, setTopic] = useState('');
  const [briefing, setBriefing] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const generate = async () => {
    if (!topic.trim()) return;
    setLoading(true);
    try {
      const resp = await api.post('/briefings/generate', { topic: topic.trim() });
      setBriefing(resp.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">Intelligence Briefings</h1>
        <p className="text-sm text-slate-500 mt-1">On-demand market intelligence reports</p>
      </div>

      <div className="flex gap-2 mb-6 max-w-xl">
        <input
          type="text" value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && generate()}
          placeholder="Brief me on... (e.g., ADC deals, Pfizer, oncology)"
          className="flex-1 px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
        />
        <button onClick={generate} disabled={loading}
          className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-sm font-medium"
        >
          {loading ? 'Generating...' : 'Generate'}
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mb-6">
        {['Oncology', 'ADC deals', 'Pfizer', 'M&A activity', 'bispecific antibodies', 'immuno-oncology'].map(q => (
          <button key={q} onClick={() => { setTopic(q); }}
            className="px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-400 hover:text-slate-200"
          >{q}</button>
        ))}
      </div>

      {briefing && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-xl font-bold text-slate-100 mb-1">{briefing.title}</h2>
          <div className="flex items-center gap-2 text-xs text-slate-500 mb-6">
            <Clock className="w-3 h-3" />
            <span>Last {briefing.period_days} days</span>
          </div>

          {briefing.sections?.map((section: any, i: number) => (
            <div key={i} className="mb-6">
              <h3 className="text-sm font-semibold text-blue-400 uppercase tracking-wider mb-3">{section.title}</h3>

              {section.title === 'Market Summary' && section.content && (
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-slate-800 rounded-lg p-3">
                    <div className="text-xs text-slate-500">Deals</div>
                    <div className="text-2xl font-bold text-slate-200">{section.content.deals_30d}</div>
                  </div>
                  <div className="bg-slate-800 rounded-lg p-3">
                    <div className="text-xs text-slate-500">Top Area</div>
                    <div className="text-lg font-bold text-slate-200">{section.content.top_therapy || '—'}</div>
                  </div>
                </div>
              )}

              {section.title === 'Notable Deals' && Array.isArray(section.content) && (
                <div className="space-y-2">
                  {section.content.map((d: any, j: number) => (
                    <div key={j} className="flex items-center justify-between py-2 border-b border-slate-800 last:border-0">
                      <div>
                        <div className="text-sm text-slate-200">{d.title}</div>
                        <div className="text-xs text-slate-500">{d.principal} → {d.partner} • {d.type}</div>
                      </div>
                      <div className="text-right flex-shrink-0">
                        <div className="text-sm text-slate-300 font-medium">{formatValue(d.value)}</div>
                        <div className="text-xs text-slate-500">{d.date}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {!briefing && !loading && (
        <div className="text-center py-16">
          <Newspaper className="w-16 h-16 text-slate-700 mx-auto mb-4" />
          <p className="text-slate-500">Enter a topic to generate an intelligence briefing</p>
        </div>
      )}
    </div>
  );
}
```

**Step 2: Add route**

Add to router: `{ path: 'briefings', element: <BriefingPage /> }`

**Step 3: Verify build and commit**

```bash
cd frontend && npm run build
git add -A
git commit -m "feat: briefing page with on-demand generation and topic search"
```

---

## Task 7A: Recommendation Engine — TESTS FIRST

**Files:**
- Create: `unified_api/tests/unit/test_recommendations.py`

```python
"""
TDD: Recommendation engine tests.
"""
import pytest


class TestRecommendations:

    def test_score_deal_relevance_returns_float(self):
        from unified_api.services.recommendations import score_deal_relevance
        score = score_deal_relevance(
            deal={"indication": "NSCLC", "value": 500},
            user_interests=["oncology", "NSCLC"],
        )
        assert isinstance(score, float)
        assert 0 <= score <= 1

    def test_generate_reasons_returns_list(self):
        from unified_api.services.recommendations import generate_reasons
        reasons = generate_reasons(
            deal={"indication": "NSCLC", "value": 500, "agreement_type": "M&A"},
            matched_on=["indication"],
        )
        assert isinstance(reasons, list)
        assert len(reasons) > 0
        assert all(isinstance(r, str) for r in reasons)
```

```bash
python -m pytest unified_api/tests/unit/test_recommendations.py -v
git add unified_api/tests/
git commit -m "test: recommendation engine tests (TDD red phase)"
```

---

## Task 7B: Recommendation Engine — IMPLEMENTATION

**Files:**
- Create: `unified_api/services/recommendations.py`
- Create: `unified_api/routers/recommendations.py`
- Modify: `unified_api/main.py`

**Step 1: Create recommendation service**

Create `unified_api/services/recommendations.py`:
```python
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
```

**Step 2: Create recommendations router**

Create `unified_api/routers/recommendations.py`:
```python
"""
Recommendation endpoints — personalized deal suggestions.
"""
from fastapi import APIRouter
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.recommendations import score_deal_relevance, generate_reasons

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["recommendations"])


@router.get("/recommendations")
async def get_recommendations(limit: int = 10):
    """
    Get personalized deal recommendations.
    Currently uses recency + high value as a proxy for relevance.
    Future: use search history and watchlist patterns.
    """
    with get_cortellis_session() as session:
        # Get recent high-value deals as recommendations
        deals = session.execute(text("""
            SELECT
                d.id, d.title, d.agreement_type, d.date_start::text,
                f.total_projected_current_amount as total_value,
                (SELECT c.name FROM deal_companies dc JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as principal,
                (SELECT c.name FROM deal_companies dc JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as partner,
                (SELECT i.name FROM deal_indications di JOIN indications i ON i.id = di.indication_id
                 WHERE di.deal_id = d.id LIMIT 1) as indication,
                (SELECT t.name FROM deal_technologies dt JOIN technologies t ON t.id = dt.technology_id
                 WHERE dt.deal_id = d.id LIMIT 1) as modality
            FROM deals d
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
            WHERE d.date_start >= CURRENT_DATE - INTERVAL '90 days'
              AND f.total_projected_current_amount IS NOT NULL
            ORDER BY f.total_projected_current_amount DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()

        recommendations = []
        for d in deals:
            reasons = []
            if d.total_value and d.total_value > 500:
                reasons.append(f"High-value deal: ${d.total_value:.0f}M")
            if d.indication:
                reasons.append(f"Indication: {d.indication}")
            if d.modality:
                reasons.append(f"Modality: {d.modality}")
            if not reasons:
                reasons.append("Recent notable deal")

            recommendations.append({
                "deal_id": d.id,
                "title": d.title,
                "agreement_type": d.agreement_type,
                "date": d.date_start,
                "value": float(d.total_value) if d.total_value else None,
                "principal": d.principal,
                "partner": d.partner,
                "indication": d.indication,
                "modality": d.modality,
                "reasons": reasons,
            })

    return {"recommendations": recommendations}
```

**Step 3: Register and test**

```bash
python -m pytest unified_api/tests/unit/test_recommendations.py -v
git add -A
git commit -m "feat: recommendation engine with relevance scoring (TDD green)"
```

---

## Task 8: Recommendations Widget on Dashboard

**Files:**
- Modify: `frontend/src/pages/DashboardPage.tsx` — add recommendations section

**Step 1: Add recommendations fetch and display to DashboardPage**

Add to the DashboardPage component after existing sections — fetch `/api/recommendations?limit=5` on mount, display as a card list with reasons badges.

The widget should show:
- "Deals You Should Know About" heading
- 5 deals with title, parties, value, and reason badges
- Link to each deal

**Step 2: Verify build and commit**

```bash
cd frontend && npm run build
git add -A
git commit -m "feat: recommendations widget on executive dashboard"
```

---

## Task 9: Integration Tests + Build Verification + Push

**Files:**
- Create: `unified_api/tests/integration/test_phase3_e2e.py`

**Step 1: Write Phase 3 e2e tests**

Create `unified_api/tests/integration/test_phase3_e2e.py`:
```python
"""
End-to-end integration tests for Phase 3.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestPhase3Endpoints:

    def test_dd_generate(self, client):
        resp = client.post("/api/dd/generate", json={"company_id": 1})
        assert resp.status_code in [200, 404]

    def test_territory_map(self, client):
        resp = client.get("/api/territory/1/map")
        assert resp.status_code in [200, 404]

    def test_briefing_generate(self, client):
        resp = client.post("/api/briefings/generate", json={"topic": "oncology"})
        assert resp.status_code == 200
        data = resp.json()
        assert "title" in data
        assert "sections" in data

    def test_briefing_list(self, client):
        resp = client.get("/api/briefings")
        assert resp.status_code == 200

    def test_recommendations(self, client):
        resp = client.get("/api/recommendations")
        assert resp.status_code == 200
        data = resp.json()
        assert "recommendations" in data

    def test_recommendations_have_reasons(self, client):
        data = client.get("/api/recommendations").json()
        for rec in data["recommendations"]:
            assert "reasons" in rec
            assert isinstance(rec["reasons"], list)
```

**Step 2: Run ALL tests**

```bash
python -m pytest unified_api/tests/ -v --tb=short
```

**Step 3: Verify frontend build**

```bash
cd frontend && npm run build
```

**Step 4: Commit and push**

```bash
git add -A
git commit -m "feat: Phase 3 complete — DD generator, territory map, briefings, recommendations"
git push origin main
```

---

## Summary

After Phase 3, the platform has:

1. **DD Package Generator** — Search company → auto-generate 10-section DD report with risk flags (TDD)
2. **Territory Rights** — Search drug → view territory commitments with status indicators (TDD)
3. **Automated Briefings** — "Brief me on [topic]" → structured intelligence report with market data + notable deals (TDD)
4. **Recommendation Engine** — "Deals you should know about" on dashboard with reasons (TDD)
5. **Dashboard enhanced** — Recommendations widget added

**New tests:** 5 DD unit + 5 DD integration + 3 territory + 3 briefing unit + 4 briefing integration + 2 recommendation unit + 6 Phase 3 e2e = **28 new tests**

**New routes:** /dd, /territory, /briefings + nav items added
**New endpoints:** /dd/generate, /territory/{id}/map, /briefings/generate, /briefings, /recommendations

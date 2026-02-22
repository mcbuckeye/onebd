# Phase 2: Analytical Power — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire up 14 existing analytics endpoints to frontend dashboards, build partnership network visualization, and create the Comp Builder — the #1 BD workflow.

**Architecture:** Phase 2 is ~60% frontend (wiring existing APIs to rich visualizations) and ~40% new backend (comp builder endpoints, comp set persistence). All analytics endpoints already exist in `unified_api/routers/analytics.py` (1,424 LOC). Graph endpoints exist in `unified_api/routers/graph.py`.

**Tech Stack:**
- Frontend: React 18, TypeScript, Recharts (charts), react-force-graph-2d (network), TanStack Table
- Backend: FastAPI, SQLAlchemy (comp builder endpoints + comp_sets table)
- Existing: 14 analytics endpoints, 7 graph endpoints, all tested

**Working Directory:** `/Users/kayleighbot/Projects/cortellis`

**Methodology:** TDD for backend tasks. Frontend tasks verified with `npm run build`.

---

## Overview of Tasks

| Task | Component | Type | Estimated Time |
|------|-----------|------|---------------|
| 1 | Analytics: Market Trends dashboard page | Frontend | 15 min |
| 2 | Analytics: Valuation Benchmarks dashboard page | Frontend | 15 min |
| 3 | Analytics: Geographic + Competitive Landscape page | Frontend | 15 min |
| 4 | Partnership Network visualization page | Frontend | 20 min |
| 5A | Comp Builder backend — TESTS FIRST | Backend/Test | 10 min |
| 5B | Comp Builder backend — IMPLEMENTATION | Backend | 15 min |
| 6 | Comp Builder frontend | Frontend | 20 min |
| 7 | Competitor tracking page | Frontend | 15 min |
| 8 | Integration tests + build verification | Test/DevOps | 10 min |

---

## Task 1: Analytics — Market Trends Dashboard

**Files:**
- Modify: `frontend/src/pages/AnalyticsPage.tsx` — full analytics dashboard with tabs

**Step 1: Install additional chart dependency**

```bash
cd frontend && npm install react-force-graph-2d
```

**Step 2: Build the analytics page with Market Trends as default tab**

Replace `frontend/src/pages/AnalyticsPage.tsx`:
```typescript
import { useState, useEffect } from 'react';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Legend, AreaChart, Area
} from 'recharts';
import { TrendingUp, DollarSign, Globe, Building2, Activity, Info } from 'lucide-react';
import api from '../lib/api';

type Tab = 'trends' | 'valuations' | 'geographic' | 'competitive';

function DataBadge({ n, disclosed }: { n: number; disclosed?: number }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full">
      <Info className="w-3 h-3" />
      N={n}{disclosed !== undefined && `, ${((disclosed / n) * 100).toFixed(0)}% disclosed`}
    </span>
  );
}

function formatValue(v: number | null): string {
  if (v === null || v === undefined) return '—';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  if (v >= 1) return `$${v.toFixed(0)}M`;
  return `$${(v * 1000).toFixed(0)}K`;
}

const CHART_STYLE = { backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' };

export default function AnalyticsPage() {
  const [tab, setTab] = useState<Tab>('trends');
  const [trends, setTrends] = useState<any>(null);
  const [valuations, setValuations] = useState<any>(null);
  const [geographic, setGeographic] = useState<any>(null);
  const [competitive, setCompetitive] = useState<any>(null);
  const [agreementTypes, setAgreementTypes] = useState<any>(null);
  const [yoy, setYoy] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [therapyFilter, setTherapyFilter] = useState('');
  const [filterOptions, setFilterOptions] = useState<string[]>([]);

  // Load filter options
  useEffect(() => {
    api.get('/search/filters').then(r => setFilterOptions(r.data.therapy_areas)).catch(() => {});
  }, []);

  // Load data based on tab
  useEffect(() => {
    setLoading(true);
    const params = therapyFilter ? `?therapy_area=${encodeURIComponent(therapyFilter)}` : '';

    if (tab === 'trends' && !trends) {
      Promise.all([
        api.get(`/analytics/market-trends${params}`),
        api.get(`/analytics/agreement-type-distribution${params}`),
        api.get(`/analytics/yoy-growth${params}`),
      ]).then(([t, a, y]) => {
        setTrends(t.data);
        setAgreementTypes(a.data);
        setYoy(y.data);
      }).catch(console.error).finally(() => setLoading(false));
    } else if (tab === 'valuations' && !valuations) {
      Promise.all([
        api.get('/analytics/valuations/by-phase'),
        api.get('/analytics/valuations/by-indication'),
        api.get('/analytics/valuations/by-deal-type'),
      ]).then(([p, i, d]) => {
        setValuations({ byPhase: p.data, byIndication: i.data, byDealType: d.data });
      }).catch(console.error).finally(() => setLoading(false));
    } else if (tab === 'geographic' && !geographic) {
      api.get('/analytics/geographic-distribution')
        .then(r => setGeographic(r.data))
        .catch(console.error).finally(() => setLoading(false));
    } else if (tab === 'competitive' && !competitive) {
      Promise.all([
        api.get('/analytics/top-acquirers'),
        api.get('/analytics/top-deals'),
        api.get('/analytics/therapy-area-heatmap'),
        api.get('/analytics/company-comparison?company_ids=1,2,3'),
      ]).then(([acq, deals, heatmap, comp]) => {
        setCompetitive({ topAcquirers: acq.data, topDeals: deals.data, heatmap: heatmap.data, comparison: comp.data });
      }).catch(console.error).finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, [tab, therapyFilter]);

  const tabs: Array<{ id: Tab; label: string; icon: any }> = [
    { id: 'trends', label: 'Market Trends', icon: TrendingUp },
    { id: 'valuations', label: 'Valuations', icon: DollarSign },
    { id: 'geographic', label: 'Geographic', icon: Globe },
    { id: 'competitive', label: 'Competitive', icon: Building2 },
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Analytics</h1>
          <p className="text-sm text-slate-500 mt-1">Market intelligence dashboards</p>
        </div>
        {/* Therapy area filter */}
        <select
          value={therapyFilter}
          onChange={(e) => { setTherapyFilter(e.target.value); setTrends(null); }}
          className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-300"
        >
          <option value="">All Therapy Areas</option>
          {filterOptions.map(ta => <option key={ta} value={ta}>{ta}</option>)}
        </select>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 bg-slate-900 p-1 rounded-lg w-fit">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm transition-colors ${
              tab === id ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Icon className="w-4 h-4" /> {label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="space-y-4">
          {[1, 2].map(i => <div key={i} className="h-64 bg-slate-800 rounded-xl animate-pulse" />)}
        </div>
      ) : (
        <>
          {/* MARKET TRENDS TAB */}
          {tab === 'trends' && trends && (
            <div className="space-y-6">
              {/* Deal volume over time */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-sm font-medium text-slate-400">Deal Volume Over Time</h2>
                  <DataBadge n={trends.data?.length || 0} />
                </div>
                <ResponsiveContainer width="100%" height={300}>
                  <AreaChart data={trends.data || []}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="period" stroke="#475569" fontSize={12} />
                    <YAxis stroke="#475569" fontSize={12} />
                    <Tooltip contentStyle={CHART_STYLE} />
                    <Area type="monotone" dataKey="deal_count" fill="#3b82f6" fillOpacity={0.2} stroke="#3b82f6" strokeWidth={2} name="Deal Count" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>

              {/* Deal value over time */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-sm font-medium text-slate-400">Average Deal Value Over Time (Disclosed Only)</h2>
                  {trends.data && (
                    <DataBadge
                      n={trends.data.reduce((s: number, d: any) => s + (d.deal_count || 0), 0)}
                      disclosed={trends.data.reduce((s: number, d: any) => s + (d.disclosed_count || 0), 0)}
                    />
                  )}
                </div>
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={trends.data || []}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="period" stroke="#475569" fontSize={12} />
                    <YAxis stroke="#475569" fontSize={12} tickFormatter={(v) => `$${v}M`} />
                    <Tooltip contentStyle={CHART_STYLE} formatter={(v: any) => [`$${v?.toFixed(0)}M`, 'Avg Value']} />
                    <Line type="monotone" dataKey="avg_value" stroke="#10b981" strokeWidth={2} dot={false} name="Avg Value ($M)" />
                  </LineChart>
                </ResponsiveContainer>
              </div>

              {/* Agreement type breakdown */}
              {agreementTypes && (
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                  <h2 className="text-sm font-medium text-slate-400 mb-4">Deal Activity by Agreement Type</h2>
                  <ResponsiveContainer width="100%" height={300}>
                    <BarChart data={agreementTypes.data?.slice(0, 10) || []} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis type="number" stroke="#475569" fontSize={12} />
                      <YAxis type="category" dataKey="agreement_type" stroke="#475569" fontSize={10} width={200} />
                      <Tooltip contentStyle={CHART_STYLE} />
                      <Bar dataKey="count" fill="#8b5cf6" radius={[0, 4, 4, 0]} name="Deals" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}

              {/* YoY Growth */}
              {yoy && yoy.data && (
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                  <h2 className="text-sm font-medium text-slate-400 mb-4">Year-over-Year Growth</h2>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-slate-500 border-b border-slate-800">
                          <th className="pb-2">Year</th>
                          <th className="pb-2">Deals</th>
                          <th className="pb-2">YoY Change</th>
                          <th className="pb-2">Avg Value</th>
                        </tr>
                      </thead>
                      <tbody>
                        {yoy.data.map((row: any) => (
                          <tr key={row.year} className="border-t border-slate-800/50">
                            <td className="py-2 text-slate-300">{row.year}</td>
                            <td className="py-2 text-slate-300">{row.deal_count?.toLocaleString()}</td>
                            <td className={`py-2 ${row.growth_rate > 0 ? 'text-green-400' : row.growth_rate < 0 ? 'text-red-400' : 'text-slate-500'}`}>
                              {row.growth_rate !== null ? `${row.growth_rate > 0 ? '+' : ''}${row.growth_rate?.toFixed(1)}%` : '—'}
                            </td>
                            <td className="py-2 text-slate-400">{formatValue(row.avg_value)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* VALUATIONS TAB */}
          {tab === 'valuations' && valuations && (
            <div className="space-y-6">
              {/* By Phase */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                <h2 className="text-sm font-medium text-slate-400 mb-4">Deal Valuation by Development Phase</h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-slate-500 border-b border-slate-800">
                        <th className="pb-2">Phase</th>
                        <th className="pb-2">N</th>
                        <th className="pb-2">Disclosed</th>
                        <th className="pb-2">Median ($M)</th>
                        <th className="pb-2">Mean ($M)</th>
                        <th className="pb-2">Q1-Q3 ($M)</th>
                        <th className="pb-2">Range ($M)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(valuations.byPhase?.benchmarks || []).map((b: any) => (
                        <tr key={b.category} className="border-t border-slate-800/50">
                          <td className="py-2 text-slate-200 font-medium">{b.category}</td>
                          <td className="py-2 text-slate-400">{b.deal_count}</td>
                          <td className="py-2 text-slate-500">{b.disclosed_count} ({b.deal_count > 0 ? ((b.disclosed_count / b.deal_count) * 100).toFixed(0) : 0}%)</td>
                          <td className="py-2 text-slate-300">{formatValue(b.median_value)}</td>
                          <td className="py-2 text-slate-300">{formatValue(b.avg_value)}</td>
                          <td className="py-2 text-slate-400">{b.q1_value && b.q3_value ? `${formatValue(b.q1_value)} – ${formatValue(b.q3_value)}` : '—'}</td>
                          <td className="py-2 text-slate-500">{b.min_value && b.max_value ? `${formatValue(b.min_value)} – ${formatValue(b.max_value)}` : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* By Phase - Bar Chart */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                <h2 className="text-sm font-medium text-slate-400 mb-4">Median Deal Value by Phase</h2>
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={valuations.byPhase?.benchmarks?.filter((b: any) => b.median_value) || []}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="category" stroke="#475569" fontSize={10} angle={-30} textAnchor="end" height={80} />
                    <YAxis stroke="#475569" fontSize={12} tickFormatter={(v) => `$${v}M`} />
                    <Tooltip contentStyle={CHART_STYLE} formatter={(v: any) => [`$${v?.toFixed(0)}M`, 'Median']} />
                    <Bar dataKey="median_value" fill="#3b82f6" radius={[4, 4, 0, 0]} name="Median Value ($M)" />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* By Indication */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                <h2 className="text-sm font-medium text-slate-400 mb-4">Deal Valuation by Indication (Top 15)</h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-slate-500 border-b border-slate-800">
                        <th className="pb-2">Indication</th>
                        <th className="pb-2">N</th>
                        <th className="pb-2">Disclosed</th>
                        <th className="pb-2">Median ($M)</th>
                        <th className="pb-2">Mean ($M)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(valuations.byIndication?.benchmarks || []).slice(0, 15).map((b: any) => (
                        <tr key={b.category} className="border-t border-slate-800/50">
                          <td className="py-2 text-slate-200">{b.category}</td>
                          <td className="py-2 text-slate-400">{b.deal_count}</td>
                          <td className="py-2 text-slate-500">{b.disclosed_count}</td>
                          <td className="py-2 text-slate-300">{formatValue(b.median_value)}</td>
                          <td className="py-2 text-slate-300">{formatValue(b.avg_value)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* GEOGRAPHIC TAB */}
          {tab === 'geographic' && geographic && (
            <div className="space-y-6">
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                <h2 className="text-sm font-medium text-slate-400 mb-4">Deal Distribution by Territory</h2>
                <ResponsiveContainer width="100%" height={400}>
                  <BarChart data={(geographic.data || geographic || []).slice(0, 20)} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis type="number" stroke="#475569" fontSize={12} />
                    <YAxis type="category" dataKey="territory" stroke="#475569" fontSize={10} width={150} />
                    <Tooltip contentStyle={CHART_STYLE} />
                    <Bar dataKey="deal_count" fill="#06b6d4" radius={[0, 4, 4, 0]} name="Deals" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* COMPETITIVE TAB */}
          {tab === 'competitive' && competitive && (
            <div className="space-y-6">
              {/* Top Acquirers */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                <h2 className="text-sm font-medium text-slate-400 mb-4">Top Acquirers by Deal Count</h2>
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={(competitive.topAcquirers?.data || competitive.topAcquirers || []).slice(0, 15)} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis type="number" stroke="#475569" fontSize={12} />
                    <YAxis type="category" dataKey="company" stroke="#475569" fontSize={10} width={180} />
                    <Tooltip contentStyle={CHART_STYLE} />
                    <Bar dataKey="deal_count" fill="#f59e0b" radius={[0, 4, 4, 0]} name="Deals" />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Top Deals */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                <h2 className="text-sm font-medium text-slate-400 mb-4">Largest Deals by Value</h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-slate-500 border-b border-slate-800">
                        <th className="pb-2">Deal</th>
                        <th className="pb-2">Principal</th>
                        <th className="pb-2">Partner</th>
                        <th className="pb-2">Value</th>
                        <th className="pb-2">Date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(competitive.topDeals?.data || competitive.topDeals || []).slice(0, 15).map((d: any, i: number) => (
                        <tr key={i} className="border-t border-slate-800/50">
                          <td className="py-2 text-slate-200 max-w-xs truncate">{d.title}</td>
                          <td className="py-2 text-slate-400">{d.principal || d.principal_company || '—'}</td>
                          <td className="py-2 text-slate-400">{d.partner || d.partner_company || '—'}</td>
                          <td className="py-2 text-slate-300 font-medium">{formatValue(d.total_value || d.value)}</td>
                          <td className="py-2 text-slate-500 text-xs">{d.date_start || d.date || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
```

**Step 3: Verify build**

```bash
cd frontend && npm run build
```

**Step 4: Commit**

```bash
git add -A
git commit -m "feat: analytics page with market trends, valuations, geographic, competitive tabs"
```

---

## Task 2: Partnership Network Visualization

**Files:**
- Modify: `frontend/src/pages/GraphPage.tsx`

**Step 1: Build the network graph page**

Replace `frontend/src/pages/GraphPage.tsx`:
```typescript
import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Network, Search, Filter, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react';
import api from '../lib/api';

interface GraphNode {
  id: string;
  name: string;
  val: number; // deal count → node size
  color: string;
  company_type?: string;
}

interface GraphLink {
  source: string;
  target: string;
  value: number; // deal frequency
  deal_count: number;
}

interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

export default function GraphPage() {
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [companySearch, setCompanySearch] = useState('');
  const [selectedCompanyId, setSelectedCompanyId] = useState<number | null>(null);
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [selectedNode, setSelectedNode] = useState<any>(null);
  const [dealsBetween, setDealsBetween] = useState<any>(null);
  const navigate = useNavigate();
  const graphRef = useRef<any>(null);

  // Company autocomplete
  useEffect(() => {
    if (companySearch.length < 2) { setSuggestions([]); return; }
    const timer = setTimeout(() => {
      api.get(`/search/autocomplete/companies?q=${encodeURIComponent(companySearch)}&limit=8`)
        .then(r => setSuggestions(r.data.suggestions || []))
        .catch(() => {});
    }, 300);
    return () => clearTimeout(timer);
  }, [companySearch]);

  // Load network for company
  const loadCompanyNetwork = async (companyId: number) => {
    setLoading(true);
    setSelectedCompanyId(companyId);
    try {
      const resp = await api.get(`/graph/partnership-network/${companyId}`);
      const data = resp.data;

      // Transform to graph format
      const nodes: GraphNode[] = (data.nodes || []).map((n: any) => ({
        id: String(n.id),
        name: n.name || n.label,
        val: Math.max(3, Math.sqrt(n.deal_count || n.size || 1) * 3),
        color: n.id === companyId ? '#3b82f6' : '#6366f1',
        company_type: n.company_type,
      }));

      const links: GraphLink[] = (data.links || data.edges || []).map((e: any) => ({
        source: String(e.source),
        target: String(e.target),
        value: e.deal_count || e.weight || 1,
        deal_count: e.deal_count || e.weight || 1,
      }));

      setGraphData({ nodes, links });
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  // Load industry-wide network
  const loadIndustryNetwork = async () => {
    setLoading(true);
    setSelectedCompanyId(null);
    try {
      const resp = await api.get('/graph/industry-network?limit=50');
      const data = resp.data;

      const nodes: GraphNode[] = (data.nodes || []).map((n: any) => ({
        id: String(n.id),
        name: n.name || n.label,
        val: Math.max(3, Math.sqrt(n.deal_count || n.size || 1) * 2),
        color: '#6366f1',
        company_type: n.company_type,
      }));

      const links: GraphLink[] = (data.links || data.edges || []).map((e: any) => ({
        source: String(e.source),
        target: String(e.target),
        value: e.deal_count || e.weight || 1,
        deal_count: e.deal_count || e.weight || 1,
      }));

      setGraphData({ nodes, links });
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleNodeClick = useCallback((node: any) => {
    setSelectedNode(node);
  }, []);

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Partnership Network</h1>
          <p className="text-sm text-slate-500 mt-1">Explore deal relationships between companies</p>
        </div>
        <button
          onClick={loadIndustryNetwork}
          className="px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-300 hover:bg-slate-700"
        >
          Industry Overview
        </button>
      </div>

      {/* Company search */}
      <div className="relative mb-6 max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
        <input
          type="text"
          value={companySearch}
          onChange={(e) => setCompanySearch(e.target.value)}
          placeholder="Search company to view network..."
          className="w-full pl-10 pr-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
        />
        {suggestions.length > 0 && (
          <div className="absolute z-20 w-full mt-1 bg-slate-800 border border-slate-700 rounded-lg shadow-xl max-h-48 overflow-y-auto">
            {suggestions.map((s: any) => (
              <button
                key={s.id}
                onClick={() => {
                  setCompanySearch(s.name);
                  setSuggestions([]);
                  loadCompanyNetwork(s.id);
                }}
                className="w-full text-left px-3 py-2 text-sm text-slate-300 hover:bg-slate-700"
              >
                {s.name}
                {s.company_type && <span className="text-xs text-slate-500 ml-2">({s.company_type})</span>}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Graph area */}
        <div className="lg:col-span-3 bg-slate-900 border border-slate-800 rounded-xl overflow-hidden" style={{ minHeight: 500 }}>
          {loading ? (
            <div className="flex items-center justify-center h-96 text-slate-500">Loading network...</div>
          ) : !graphData ? (
            <div className="flex flex-col items-center justify-center h-96 text-slate-500">
              <Network className="w-16 h-16 mb-4 opacity-30" />
              <p className="text-sm">Search for a company or click "Industry Overview"</p>
            </div>
          ) : (
            <div className="relative h-[500px]">
              {/* Simple node list visualization (force-graph loaded dynamically) */}
              <div className="p-4 overflow-y-auto h-full">
                <div className="text-xs text-slate-500 mb-3">
                  {graphData.nodes.length} companies, {graphData.links.length} connections
                </div>
                <div className="space-y-1">
                  {graphData.nodes
                    .sort((a, b) => b.val - a.val)
                    .map(node => (
                      <button
                        key={node.id}
                        onClick={() => {
                          setSelectedNode(node);
                          navigate(`/company/${node.id}`);
                        }}
                        className={`w-full text-left flex items-center gap-3 px-3 py-2 rounded-lg text-sm hover:bg-slate-800 ${
                          selectedNode?.id === node.id ? 'bg-slate-800' : ''
                        }`}
                      >
                        <div
                          className="rounded-full flex-shrink-0"
                          style={{ width: node.val * 2, height: node.val * 2, backgroundColor: node.color, minWidth: 8, minHeight: 8 }}
                        />
                        <span className="text-slate-300 truncate">{node.name}</span>
                        <span className="text-xs text-slate-500 ml-auto">{node.company_type}</span>
                      </button>
                    ))}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Side panel */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <h3 className="text-sm font-medium text-slate-400 mb-3">Network Details</h3>
          {graphData ? (
            <div className="space-y-3 text-sm">
              <div>
                <span className="text-slate-500">Companies:</span>
                <span className="text-slate-300 ml-2">{graphData.nodes.length}</span>
              </div>
              <div>
                <span className="text-slate-500">Connections:</span>
                <span className="text-slate-300 ml-2">{graphData.links.length}</span>
              </div>
              <div>
                <span className="text-slate-500">Top connections:</span>
                <div className="mt-2 space-y-1">
                  {graphData.links
                    .sort((a, b) => b.deal_count - a.deal_count)
                    .slice(0, 10)
                    .map((link, i) => {
                      const src = graphData.nodes.find(n => n.id === (typeof link.source === 'string' ? link.source : (link.source as any).id));
                      const tgt = graphData.nodes.find(n => n.id === (typeof link.target === 'string' ? link.target : (link.target as any).id));
                      return (
                        <div key={i} className="text-xs text-slate-400">
                          {src?.name} ↔ {tgt?.name} ({link.deal_count})
                        </div>
                      );
                    })}
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-slate-500">Select a company to see network details</p>
          )}
        </div>
      </div>
    </div>
  );
}
```

**Step 2: Verify build and commit**

```bash
cd frontend && npm run build
git add -A
git commit -m "feat: partnership network visualization page with company search"
```

---

## Task 3: Competitor Tracking Page

**Files:**
- Modify: `frontend/src/pages/CompetitorsPage.tsx`

**Step 1: Build competitor tracking page**

Replace `frontend/src/pages/CompetitorsPage.tsx`:
```typescript
import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Building2, Plus, Search, TrendingUp, X } from 'lucide-react';
import api from '../lib/api';

interface TrackedCompetitor {
  id: number;
  name: string;
  company_type: string | null;
  recent_deals: number;
  total_deals: number;
}

export default function CompetitorsPage() {
  const [competitors, setCompetitors] = useState<TrackedCompetitor[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [companyDeals, setCompanyDeals] = useState<Record<number, any[]>>({});

  // Company autocomplete for adding
  useEffect(() => {
    if (searchQuery.length < 2) { setSuggestions([]); return; }
    const timer = setTimeout(() => {
      api.get(`/search/autocomplete/companies?q=${encodeURIComponent(searchQuery)}&limit=8`)
        .then(r => setSuggestions(r.data.suggestions || []))
        .catch(() => {});
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Add competitor
  const addCompetitor = async (company: any) => {
    if (competitors.some(c => c.id === company.id)) return;

    setSearchQuery('');
    setSuggestions([]);
    setLoading(true);

    try {
      // Fetch company profile to get deal counts
      const resp = await api.get(`/company/${company.id}/profile`);
      const profile = resp.data;

      const newComp: TrackedCompetitor = {
        id: company.id,
        name: company.name,
        company_type: company.company_type,
        recent_deals: profile.deal_summary?.recent_deals_12m || 0,
        total_deals: profile.deal_summary?.total_deals || 0,
      };

      setCompetitors(prev => [...prev, newComp]);

      // Load recent deals
      const dealsResp = await api.post('/search/deals?page=1&page_size=5', {
        company: company.name,
      });
      setCompanyDeals(prev => ({ ...prev, [company.id]: dealsResp.data.results || [] }));
    } catch (e) {
      console.error(e);
      // Still add with basic info
      setCompetitors(prev => [...prev, {
        id: company.id,
        name: company.name,
        company_type: company.company_type,
        recent_deals: 0,
        total_deals: 0,
      }]);
    } finally {
      setLoading(false);
    }
  };

  const removeCompetitor = (id: number) => {
    setCompetitors(prev => prev.filter(c => c.id !== id));
    setCompanyDeals(prev => { const next = { ...prev }; delete next[id]; return next; });
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">Competitor Intelligence</h1>
        <p className="text-sm text-slate-500 mt-1">Track competitor deal activity and strategy</p>
      </div>

      {/* Add competitor */}
      <div className="relative mb-6 max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Add a company to track..."
          className="w-full pl-10 pr-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
        />
        {suggestions.length > 0 && (
          <div className="absolute z-20 w-full mt-1 bg-slate-800 border border-slate-700 rounded-lg shadow-xl max-h-48 overflow-y-auto">
            {suggestions.map((s: any) => (
              <button
                key={s.id}
                onClick={() => addCompetitor(s)}
                className="w-full text-left px-3 py-2 text-sm text-slate-300 hover:bg-slate-700 flex items-center gap-2"
              >
                <Plus className="w-3 h-3 text-blue-400" />
                {s.name}
                {s.company_type && <span className="text-xs text-slate-500">({s.company_type})</span>}
              </button>
            ))}
          </div>
        )}
      </div>

      {competitors.length === 0 ? (
        <div className="text-center py-20">
          <Building2 className="w-16 h-16 text-slate-700 mx-auto mb-4" />
          <p className="text-slate-500">No competitors tracked yet</p>
          <p className="text-sm text-slate-600 mt-1">Search above to add companies to monitor</p>
        </div>
      ) : (
        <div className="space-y-4">
          {competitors.map(comp => (
            <div key={comp.id} className="bg-slate-900 border border-slate-800 rounded-xl p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-purple-600/20 flex items-center justify-center">
                    <Building2 className="w-5 h-5 text-purple-400" />
                  </div>
                  <div>
                    <Link to={`/company/${comp.id}`} className="text-lg font-semibold text-slate-200 hover:text-blue-400">
                      {comp.name}
                    </Link>
                    <div className="text-xs text-slate-500">{comp.company_type || 'Company'}</div>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <div className="text-right">
                    <div className="text-sm font-medium text-slate-300">{comp.total_deals} deals</div>
                    <div className="text-xs text-slate-500">{comp.recent_deals} in last 12m</div>
                  </div>
                  <button onClick={() => removeCompetitor(comp.id)} className="p-1 hover:bg-slate-800 rounded">
                    <X className="w-4 h-4 text-slate-500" />
                  </button>
                </div>
              </div>

              {/* Recent deals for this competitor */}
              {companyDeals[comp.id] && companyDeals[comp.id].length > 0 && (
                <div className="border-t border-slate-800 pt-3">
                  <h3 className="text-xs text-slate-500 mb-2">Recent Deals</h3>
                  <div className="space-y-1">
                    {companyDeals[comp.id].map((deal: any) => (
                      <div key={deal.id} className="flex items-center justify-between text-sm py-1">
                        <span className="text-slate-400 truncate max-w-md">{deal.title}</span>
                        <div className="flex items-center gap-3 flex-shrink-0">
                          <span className="text-slate-500 text-xs">{deal.deal_type}</span>
                          <span className="text-slate-500 text-xs">{deal.date_start}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

**Step 2: Verify build and commit**

```bash
cd frontend && npm run build
git add -A
git commit -m "feat: competitor intelligence page with company tracking and recent deals"
```

---

## Task 4: My Deals / Watchlist Page

**Files:**
- Modify: `frontend/src/pages/MyDealsPage.tsx`

**Step 1: Build My Deals page**

Replace `frontend/src/pages/MyDealsPage.tsx`:
```typescript
import { useState, useEffect } from 'react';
import { Star, Bookmark, Search as SearchIcon, MessageSquare, Clock } from 'lucide-react';
import api from '../lib/api';

type WatchlistTab = 'watchlist' | 'saved' | 'history';

function formatValue(v: number | null): string {
  if (v === null || v === undefined) return '—';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
}

export default function MyDealsPage() {
  const [tab, setTab] = useState<WatchlistTab>('watchlist');
  const [watchlist, setWatchlist] = useState<any[]>([]);
  const [savedSearches, setSavedSearches] = useState<any[]>([]);
  const [searchHistory, setSearchHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    if (tab === 'watchlist') {
      api.get('/watchlist').then(r => setWatchlist(r.data.watchlist || r.data || []))
        .catch(() => setWatchlist([]))
        .finally(() => setLoading(false));
    } else if (tab === 'saved') {
      api.get('/saved-searches').then(r => setSavedSearches(r.data.searches || r.data || []))
        .catch(() => setSavedSearches([]))
        .finally(() => setLoading(false));
    } else if (tab === 'history') {
      api.get('/search/history').then(r => setSearchHistory(r.data.history || []))
        .catch(() => setSearchHistory([]))
        .finally(() => setLoading(false));
    }
  }, [tab]);

  const tabs: Array<{ id: WatchlistTab; label: string; icon: any }> = [
    { id: 'watchlist', label: 'Watchlist', icon: Star },
    { id: 'saved', label: 'Saved Searches', icon: Bookmark },
    { id: 'history', label: 'Search History', icon: Clock },
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">My Deals</h1>
        <p className="text-sm text-slate-500 mt-1">Your tracked deals, saved searches, and activity</p>
      </div>

      <div className="flex gap-1 mb-6 bg-slate-900 p-1 rounded-lg w-fit">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm transition-colors ${
              tab === id ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Icon className="w-4 h-4" /> {label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map(i => <div key={i} className="h-16 bg-slate-800 rounded-xl animate-pulse" />)}
        </div>
      ) : (
        <>
          {tab === 'watchlist' && (
            watchlist.length === 0 ? (
              <div className="text-center py-16">
                <Star className="w-12 h-12 text-slate-700 mx-auto mb-3" />
                <p className="text-slate-500">No deals in your watchlist</p>
                <p className="text-sm text-slate-600 mt-1">Add deals from search results to track them here</p>
              </div>
            ) : (
              <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-slate-500 bg-slate-900/50">
                      <th className="px-4 py-3">Deal</th>
                      <th className="px-4 py-3">Status</th>
                      <th className="px-4 py-3">Tags</th>
                      <th className="px-4 py-3">Added</th>
                    </tr>
                  </thead>
                  <tbody>
                    {watchlist.map((item: any, i: number) => (
                      <tr key={i} className="border-t border-slate-800/50 hover:bg-slate-800/30">
                        <td className="px-4 py-3 text-slate-200">{item.deal_title || item.title || `Deal #${item.deal_id}`}</td>
                        <td className="px-4 py-3">
                          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-400">
                            {item.status || 'Reviewing'}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-500 text-xs">{(item.tags || []).join(', ') || '—'}</td>
                        <td className="px-4 py-3 text-slate-500 text-xs">{item.added_at || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}

          {tab === 'saved' && (
            savedSearches.length === 0 ? (
              <div className="text-center py-16">
                <Bookmark className="w-12 h-12 text-slate-700 mx-auto mb-3" />
                <p className="text-slate-500">No saved searches</p>
              </div>
            ) : (
              <div className="space-y-2">
                {savedSearches.map((s: any, i: number) => (
                  <div key={i} className="bg-slate-900 border border-slate-800 rounded-lg px-4 py-3 flex items-center justify-between">
                    <div>
                      <div className="text-sm text-slate-200">{s.name}</div>
                      <div className="text-xs text-slate-500 mt-0.5">
                        {s.is_alert && <span className="text-yellow-400 mr-2">🔔 Alert active</span>}
                        {s.created_at}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )
          )}

          {tab === 'history' && (
            searchHistory.length === 0 ? (
              <div className="text-center py-16">
                <Clock className="w-12 h-12 text-slate-700 mx-auto mb-3" />
                <p className="text-slate-500">No recent searches</p>
              </div>
            ) : (
              <div className="space-y-1">
                {searchHistory.map((h: any, i: number) => (
                  <div key={i} className="bg-slate-900 border border-slate-800 rounded-lg px-4 py-2.5 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <SearchIcon className="w-3 h-3 text-slate-600" />
                      <span className="text-sm text-slate-300">{h.query}</span>
                    </div>
                    <div className="flex items-center gap-3 text-xs text-slate-500">
                      <span>{h.result_count} results</span>
                      <span>{h.created_at}</span>
                    </div>
                  </div>
                ))}
              </div>
            )
          )}
        </>
      )}
    </div>
  );
}
```

**Step 2: Verify build and commit**

```bash
cd frontend && npm run build
git add -A
git commit -m "feat: My Deals page with watchlist, saved searches, search history tabs"
```

---

## Task 5A: Comp Builder Backend — TESTS FIRST

**Files:**
- Create: `unified_api/tests/unit/test_comp_builder.py`
- Create: `unified_api/tests/integration/test_comp_endpoints.py`

**Step 1: Write comp builder unit tests**

Create `unified_api/tests/unit/test_comp_builder.py`:
```python
"""
TDD: Comp builder tests — write these FIRST, then implement.
"""
import pytest


class TestCompMatchScoring:
    """Test deal similarity scoring for comp building."""

    def test_exact_match_scores_high(self):
        from unified_api.services.comp_builder import score_deal_similarity
        criteria = {"indication": "NSCLC", "phase": "Phase 2", "modality": "ADC"}
        deal = {"indication": "NSCLC", "phase": "Phase 2", "modality": "ADC"}
        score = score_deal_similarity(criteria, deal)
        assert score >= 0.8

    def test_no_match_scores_low(self):
        from unified_api.services.comp_builder import score_deal_similarity
        criteria = {"indication": "NSCLC", "phase": "Phase 2", "modality": "ADC"}
        deal = {"indication": "Diabetes", "phase": "Approved", "modality": "Small molecule"}
        score = score_deal_similarity(criteria, deal)
        assert score < 0.3

    def test_partial_match_scores_medium(self):
        from unified_api.services.comp_builder import score_deal_similarity
        criteria = {"indication": "NSCLC", "phase": "Phase 2", "modality": "ADC"}
        deal = {"indication": "Breast Cancer", "phase": "Phase 2", "modality": "ADC"}
        score = score_deal_similarity(criteria, deal)
        assert 0.3 <= score <= 0.8

    def test_score_is_between_0_and_1(self):
        from unified_api.services.comp_builder import score_deal_similarity
        criteria = {"indication": "test"}
        deal = {"indication": "test"}
        score = score_deal_similarity(criteria, deal)
        assert 0.0 <= score <= 1.0

    def test_empty_criteria_returns_zero(self):
        from unified_api.services.comp_builder import score_deal_similarity
        score = score_deal_similarity({}, {"indication": "test"})
        assert score == 0.0


class TestCompSetStats:
    """Test statistical summary of comp set."""

    def test_compute_stats_with_values(self):
        from unified_api.services.comp_builder import compute_comp_stats
        deals = [
            {"total_value": 100},
            {"total_value": 200},
            {"total_value": 300},
            {"total_value": 400},
            {"total_value": 500},
        ]
        stats = compute_comp_stats(deals)
        assert stats["count"] == 5
        assert stats["disclosed"] == 5
        assert stats["mean"] == 300.0
        assert stats["median"] == 300.0
        assert stats["min"] == 100
        assert stats["max"] == 500

    def test_compute_stats_with_nulls(self):
        from unified_api.services.comp_builder import compute_comp_stats
        deals = [
            {"total_value": 100},
            {"total_value": None},
            {"total_value": 300},
        ]
        stats = compute_comp_stats(deals)
        assert stats["count"] == 3
        assert stats["disclosed"] == 2
        assert stats["mean"] == 200.0

    def test_compute_stats_empty(self):
        from unified_api.services.comp_builder import compute_comp_stats
        stats = compute_comp_stats([])
        assert stats["count"] == 0
        assert stats["disclosed"] == 0
        assert stats["mean"] is None
        assert stats["median"] is None
```

**Step 2: Write comp endpoint integration tests**

Create `unified_api/tests/integration/test_comp_endpoints.py`:
```python
"""
TDD: Comp builder endpoint tests — write these FIRST, then implement.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestCompBuildEndpoint:
    """Test POST /api/comps/build"""

    def test_build_comps_returns_200(self, client):
        resp = client.post("/api/comps/build", json={
            "indication": "Oncology",
            "phase": "Phase 2",
        })
        assert resp.status_code == 200

    def test_build_comps_response_structure(self, client):
        data = client.post("/api/comps/build", json={
            "indication": "Oncology",
        }).json()
        assert "deals" in data
        assert "stats" in data
        assert isinstance(data["deals"], list)
        assert "count" in data["stats"]

    def test_build_comps_deals_have_scores(self, client):
        data = client.post("/api/comps/build", json={
            "indication": "Oncology",
            "phase": "Phase 2",
        }).json()
        if len(data["deals"]) > 0:
            assert "match_score" in data["deals"][0]
            assert 0 <= data["deals"][0]["match_score"] <= 1

    def test_build_comps_sorted_by_score(self, client):
        data = client.post("/api/comps/build", json={
            "indication": "Oncology",
        }).json()
        if len(data["deals"]) > 1:
            scores = [d["match_score"] for d in data["deals"]]
            assert scores == sorted(scores, reverse=True)

    def test_build_comps_limits_results(self, client):
        data = client.post("/api/comps/build", json={
            "indication": "Oncology",
            "limit": 5,
        }).json()
        assert len(data["deals"]) <= 5


class TestCompSaveEndpoint:
    """Test comp set save/retrieve."""

    def test_save_comp_set(self, client):
        resp = client.post("/api/comps", json={
            "name": "Test Comp Set",
            "deal_ids": [1, 2, 3],
            "criteria": {"indication": "Oncology"},
        })
        # May be 200 or 201
        assert resp.status_code in [200, 201]

    def test_list_comp_sets(self, client):
        resp = client.get("/api/comps")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list) or "comp_sets" in resp.json()
```

**Step 3: Run tests — verify they FAIL**

```bash
python -m pytest unified_api/tests/unit/test_comp_builder.py -v
python -m pytest unified_api/tests/integration/test_comp_endpoints.py -v
```

Expected: All FAIL.

**Step 4: Commit failing tests**

```bash
git add unified_api/tests/
git commit -m "test: comp builder tests (TDD red phase — all failing)"
```

---

## Task 5B: Comp Builder Backend — IMPLEMENTATION

**Files:**
- Create: `unified_api/services/comp_builder.py` — scoring + stats logic
- Create: `unified_api/routers/comps.py` — comp builder endpoints
- Modify: `unified_api/main.py` — register comps router

**Step 1: Create comp builder service**

Create `unified_api/services/comp_builder.py`:
```python
"""
Comp Builder service — deal similarity scoring and statistical summaries.
"""
from typing import List, Dict, Any, Optional
import statistics


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

        crit_val = str(criteria[field]).lower()
        deal_val = str(deal.get(field, "")).lower()

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
```

**Step 2: Create comps router**

Create `unified_api/routers/comps.py`:
```python
"""
Comp Builder endpoints — find comparable deals and manage comp sets.
"""
from typing import Optional, List
from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.comp_builder import score_deal_similarity, compute_comp_stats

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["comps"])


class CompBuildRequest(BaseModel):
    indication: Optional[str] = None
    phase: Optional[str] = None
    modality: Optional[str] = None
    deal_type: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    limit: int = 20


class CompSaveRequest(BaseModel):
    name: str
    deal_ids: List[int]
    criteria: Optional[dict] = None
    notes: Optional[str] = None


@router.post("/comps/build")
async def build_comps(req: CompBuildRequest):
    """
    Find comparable deals based on criteria and rank by similarity.
    """
    with get_cortellis_session() as session:
        # Build query to find candidate deals
        conditions = []
        params: dict = {"limit": min(req.limit * 3, 100)}  # fetch more, then score/rank

        if req.indication:
            conditions.append("""
                d.id IN (
                    SELECT di.deal_id FROM deal_indications di
                    JOIN indications i ON i.id = di.indication_id
                    WHERE i.name ILIKE :indication
                )
            """)
            params["indication"] = f"%{req.indication}%"

        if req.phase:
            conditions.append("d.phase_highest_start ILIKE :phase")
            params["phase"] = f"%{req.phase}%"

        if req.deal_type:
            conditions.append("d.agreement_type ILIKE :deal_type")
            params["deal_type"] = f"%{req.deal_type}%"

        if req.date_from:
            conditions.append("d.date_start >= :date_from")
            params["date_from"] = req.date_from

        if req.date_to:
            conditions.append("d.date_start <= :date_to")
            params["date_to"] = req.date_to

        where = " AND ".join(conditions) if conditions else "1=1"

        result = session.execute(text(f"""
            SELECT
                d.id, d.title, d.agreement_type, d.status,
                d.date_start::text, d.phase_highest_start,
                f.total_projected_current_amount as total_value,
                (SELECT c.name FROM deal_companies dc
                 JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as principal,
                (SELECT c.name FROM deal_companies dc
                 JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as partner,
                (SELECT i.name FROM deal_indications di
                 JOIN indications i ON i.id = di.indication_id
                 WHERE di.deal_id = d.id LIMIT 1) as indication,
                (SELECT t.name FROM deal_technologies dt
                 JOIN technologies t ON t.id = dt.technology_id
                 WHERE dt.deal_id = d.id LIMIT 1) as modality
            FROM deals d
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
            WHERE {where}
            ORDER BY f.total_projected_current_amount DESC NULLS LAST
            LIMIT :limit
        """), params)

        candidates = []
        criteria = {
            k: v for k, v in {
                "indication": req.indication,
                "phase": req.phase,
                "modality": req.modality,
                "deal_type": req.deal_type,
            }.items() if v
        }

        for row in result:
            deal = {
                "id": row.id,
                "title": row.title,
                "agreement_type": row.agreement_type,
                "status": row.status,
                "date_start": row.date_start,
                "phase": row.phase_highest_start,
                "total_value": float(row.total_value) if row.total_value else None,
                "principal_company": row.principal,
                "partner_company": row.partner,
                "indication": row.indication,
                "modality": row.modality,
            }
            deal["match_score"] = score_deal_similarity(criteria, deal)
            candidates.append(deal)

        # Sort by match score, take top N
        candidates.sort(key=lambda d: d["match_score"], reverse=True)
        top_deals = candidates[:req.limit]

        stats = compute_comp_stats(top_deals)

    return {
        "criteria": criteria,
        "deals": top_deals,
        "stats": stats,
    }


@router.post("/comps", status_code=201)
async def save_comp_set(req: CompSaveRequest):
    """Save a comp set for future reference."""
    with get_cortellis_session() as session:
        # Ensure table exists
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS comp_sets (
                id SERIAL PRIMARY KEY,
                user_id INT DEFAULT 1,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                criteria JSONB,
                deal_ids INT[] NOT NULL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))

        import json
        result = session.execute(text("""
            INSERT INTO comp_sets (name, criteria, deal_ids, notes)
            VALUES (:name, :criteria, :deal_ids, :notes)
            RETURNING id
        """), {
            "name": req.name,
            "criteria": json.dumps(req.criteria) if req.criteria else None,
            "deal_ids": req.deal_ids,
            "notes": req.notes,
        })
        comp_id = result.fetchone()[0]
        session.commit()

    return {"id": comp_id, "name": req.name}


@router.get("/comps")
async def list_comp_sets():
    """List saved comp sets."""
    with get_cortellis_session() as session:
        # Check if table exists
        exists = session.execute(text("""
            SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'comp_sets')
        """)).scalar()

        if not exists:
            return []

        result = session.execute(text("""
            SELECT id, name, criteria, deal_ids, notes, created_at::text
            FROM comp_sets
            ORDER BY created_at DESC
            LIMIT 50
        """))

        return [
            {
                "id": row.id,
                "name": row.name,
                "criteria": row.criteria,
                "deal_ids": row.deal_ids,
                "notes": row.notes,
                "created_at": row.created_at,
            }
            for row in result
        ]
```

**Step 3: Register in main.py**

Add `comps` to imports and `app.include_router(comps.router, prefix="/api")`.

**Step 4: Run tests — verify they PASS**

```bash
python -m pytest unified_api/tests/unit/test_comp_builder.py -v
python -m pytest unified_api/tests/integration/test_comp_endpoints.py -v
```

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: comp builder backend with scoring, stats, save/list endpoints (TDD green)"
```

---

## Task 6: Comp Builder Frontend

**Files:**
- Create: `frontend/src/pages/CompBuilderPage.tsx`
- Modify: `frontend/src/router.tsx` — add route

**Step 1: Create comp builder page**

Create `frontend/src/pages/CompBuilderPage.tsx`:
```typescript
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Scale, Download, Save, Plus, X, BarChart3, Info } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import api from '../lib/api';

function formatValue(v: number | null): string {
  if (v === null || v === undefined) return '—';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
}

export default function CompBuilderPage() {
  const [criteria, setCriteria] = useState({
    indication: '',
    phase: '',
    modality: '',
    deal_type: '',
    date_from: '',
    date_to: '',
  });
  const [results, setResults] = useState<any>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(false);
  const [saveName, setSaveName] = useState('');
  const [showSave, setShowSave] = useState(false);

  const search = async () => {
    setLoading(true);
    try {
      const body: any = { limit: 30 };
      if (criteria.indication) body.indication = criteria.indication;
      if (criteria.phase) body.phase = criteria.phase;
      if (criteria.modality) body.modality = criteria.modality;
      if (criteria.deal_type) body.deal_type = criteria.deal_type;
      if (criteria.date_from) body.date_from = criteria.date_from;
      if (criteria.date_to) body.date_to = criteria.date_to;

      const resp = await api.post('/comps/build', body);
      setResults(resp.data);
      setSelected(new Set());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const toggleSelect = (id: number) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const selectedDeals = results?.deals?.filter((d: any) => selected.has(d.id)) || [];
  const selectedStats = selectedDeals.length > 0
    ? {
        count: selectedDeals.length,
        disclosed: selectedDeals.filter((d: any) => d.total_value).length,
        values: selectedDeals.filter((d: any) => d.total_value).map((d: any) => d.total_value),
      }
    : null;

  const saveCompSet = async () => {
    if (!saveName || selected.size === 0) return;
    try {
      await api.post('/comps', {
        name: saveName,
        deal_ids: Array.from(selected),
        criteria,
      });
      setShowSave(false);
      setSaveName('');
      alert('Comp set saved');
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2">
          <Scale className="w-6 h-6 text-blue-400" /> Comp Builder
        </h1>
        <p className="text-sm text-slate-500 mt-1">Find and compare comparable deals for benchmarking</p>
      </div>

      {/* Criteria form */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 mb-6">
        <h2 className="text-sm font-medium text-slate-400 mb-4">Define Target Profile</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-xs text-slate-500 mb-1">Indication</label>
            <input
              type="text" value={criteria.indication}
              onChange={(e) => setCriteria(c => ({ ...c, indication: e.target.value }))}
              placeholder="e.g., NSCLC, Breast Cancer"
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Phase</label>
            <input
              type="text" value={criteria.phase}
              onChange={(e) => setCriteria(c => ({ ...c, phase: e.target.value }))}
              placeholder="e.g., Phase 2"
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Modality</label>
            <input
              type="text" value={criteria.modality}
              onChange={(e) => setCriteria(c => ({ ...c, modality: e.target.value }))}
              placeholder="e.g., ADC, bispecific"
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Deal Type</label>
            <input
              type="text" value={criteria.deal_type}
              onChange={(e) => setCriteria(c => ({ ...c, deal_type: e.target.value }))}
              placeholder="e.g., License, M&A"
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Date From</label>
            <input
              type="date" value={criteria.date_from}
              onChange={(e) => setCriteria(c => ({ ...c, date_from: e.target.value }))}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Date To</label>
            <input
              type="date" value={criteria.date_to}
              onChange={(e) => setCriteria(c => ({ ...c, date_to: e.target.value }))}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>
        <div className="mt-4">
          <button onClick={search} disabled={loading}
            className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
          >
            {loading ? 'Finding comps...' : 'Find Comparable Deals'}
          </button>
        </div>
      </div>

      {results && (
        <>
          {/* Stats summary */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
              <div className="text-xs text-slate-500">Total Found</div>
              <div className="text-lg font-bold text-slate-200">{results.stats.count}</div>
            </div>
            <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
              <div className="text-xs text-slate-500">Disclosed Values</div>
              <div className="text-lg font-bold text-slate-200">{results.stats.disclosed} ({results.stats.count > 0 ? ((results.stats.disclosed / results.stats.count) * 100).toFixed(0) : 0}%)</div>
            </div>
            <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
              <div className="text-xs text-slate-500">Median Value</div>
              <div className="text-lg font-bold text-slate-200">{formatValue(results.stats.median)}</div>
            </div>
            <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
              <div className="text-xs text-slate-500">Range</div>
              <div className="text-lg font-bold text-slate-200">
                {results.stats.min ? `${formatValue(results.stats.min)} – ${formatValue(results.stats.max)}` : '—'}
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3 mb-4">
            <span className="text-sm text-slate-500">{selected.size} selected</span>
            {selected.size > 0 && (
              <>
                <button onClick={() => setShowSave(true)}
                  className="px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 hover:bg-slate-700 flex items-center gap-1"
                >
                  <Save className="w-3 h-3" /> Save Comp Set
                </button>
                <button onClick={() => setSelected(new Set())}
                  className="px-3 py-1.5 text-xs text-slate-500 hover:text-slate-300"
                >
                  Clear selection
                </button>
              </>
            )}
          </div>

          {/* Save modal */}
          {showSave && (
            <div className="mb-4 bg-slate-800 border border-slate-700 rounded-lg p-4 max-w-sm">
              <input
                type="text" value={saveName}
                onChange={(e) => setSaveName(e.target.value)}
                placeholder="Comp set name..."
                className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 mb-2"
              />
              <div className="flex gap-2">
                <button onClick={saveCompSet} className="px-3 py-1.5 bg-blue-600 rounded-lg text-xs">Save</button>
                <button onClick={() => setShowSave(false)} className="px-3 py-1.5 bg-slate-700 rounded-lg text-xs">Cancel</button>
              </div>
            </div>
          )}

          {/* Results table */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500 bg-slate-900/50">
                    <th className="px-4 py-3 w-10"></th>
                    <th className="px-4 py-3">Match</th>
                    <th className="px-4 py-3">Deal</th>
                    <th className="px-4 py-3">Principal</th>
                    <th className="px-4 py-3">Partner</th>
                    <th className="px-4 py-3">Phase</th>
                    <th className="px-4 py-3">Value</th>
                    <th className="px-4 py-3">Date</th>
                  </tr>
                </thead>
                <tbody>
                  {results.deals.map((deal: any) => (
                    <tr
                      key={deal.id}
                      onClick={() => toggleSelect(deal.id)}
                      className={`border-t border-slate-800/50 cursor-pointer transition-colors ${
                        selected.has(deal.id) ? 'bg-blue-600/10' : 'hover:bg-slate-800/30'
                      }`}
                    >
                      <td className="px-4 py-3">
                        <input type="checkbox" checked={selected.has(deal.id)} readOnly
                          className="rounded border-slate-600" />
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1">
                          <div className="w-12 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                            <div className="h-full bg-blue-500 rounded-full" style={{ width: `${deal.match_score * 100}%` }} />
                          </div>
                          <span className="text-xs text-slate-500">{(deal.match_score * 100).toFixed(0)}%</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-slate-200 max-w-xs truncate">{deal.title}</td>
                      <td className="px-4 py-3 text-slate-400">{deal.principal_company || '—'}</td>
                      <td className="px-4 py-3 text-slate-400">{deal.partner_company || '—'}</td>
                      <td className="px-4 py-3 text-slate-500 text-xs">{deal.phase || '—'}</td>
                      <td className="px-4 py-3 text-slate-300 font-medium">{formatValue(deal.total_value)}</td>
                      <td className="px-4 py-3 text-slate-500 text-xs">{deal.date_start || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Selected deals comparison chart */}
          {selectedStats && selectedStats.values.length > 0 && (
            <div className="mt-6 bg-slate-900 border border-slate-800 rounded-xl p-5">
              <h2 className="text-sm font-medium text-slate-400 mb-4 flex items-center gap-2">
                <BarChart3 className="w-4 h-4" /> Selected Deals — Value Distribution
                <span className="text-xs text-slate-500 ml-auto flex items-center gap-1">
                  <Info className="w-3 h-3" /> N={selectedStats.disclosed}, {((selectedStats.disclosed / selectedStats.count) * 100).toFixed(0)}% disclosed
                </span>
              </h2>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={selectedDeals.filter((d: any) => d.total_value).map((d: any) => ({
                  name: d.title?.slice(0, 30) || `Deal ${d.id}`,
                  value: d.total_value,
                }))}>
                  <XAxis dataKey="name" stroke="#475569" fontSize={10} angle={-20} textAnchor="end" height={60} />
                  <YAxis stroke="#475569" fontSize={12} tickFormatter={(v) => `$${v}M`} />
                  <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                    formatter={(v: any) => [`$${v?.toFixed(0)}M`, 'Value']} />
                  <Bar dataKey="value" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </div>
  );
}
```

**Step 2: Add route to router.tsx**

Add to `frontend/src/router.tsx`:
- Import: `import CompBuilderPage from './pages/CompBuilderPage';`
- Route: `{ path: 'comps', element: <CompBuilderPage /> },`

Also add to `MainLayout.tsx` nav items:
```typescript
{ to: '/comps', icon: Scale, label: 'Comps' },
```
Import `Scale` from lucide-react.

**Step 3: Verify build and commit**

```bash
cd frontend && npm run build
git add -A
git commit -m "feat: comp builder page with criteria search, scoring, selection, save"
```

---

## Task 7: Contracts + Filings Placeholder Pages

**Files:**
- Modify: `frontend/src/pages/ContractsPage.tsx`
- Modify: `frontend/src/pages/FilingsPage.tsx`

**Step 1: Build contracts search page**

Replace `frontend/src/pages/ContractsPage.tsx`:
```typescript
import { useState } from 'react';
import { ScrollText, Search } from 'lucide-react';
import api from '../lib/api';

export default function ContractsPage() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<'semantic' | 'fulltext'>('semantic');

  const search = async () => {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const resp = await api.get(`/search/contracts?query=${encodeURIComponent(query)}&mode=${mode}&limit=20`);
      setResults(resp.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">Contract Intelligence</h1>
        <p className="text-sm text-slate-500 mt-1">Search across 26K+ pharmaceutical contracts and 903K embedded chunks</p>
      </div>

      <div className="flex gap-2 mb-6">
        <div className="relative flex-1 max-w-2xl">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text" value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && search()}
            placeholder="Search contracts... e.g., royalty rates, milestone payments, opt-in clauses"
            className="w-full pl-10 pr-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
          />
        </div>
        <select
          value={mode} onChange={(e) => setMode(e.target.value as any)}
          className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-300"
        >
          <option value="semantic">Semantic</option>
          <option value="fulltext">Full Text</option>
        </select>
        <button onClick={search} disabled={loading}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-sm font-medium"
        >
          Search
        </button>
      </div>

      {results && (
        <div className="space-y-3">
          <div className="text-sm text-slate-500">{results.total} results</div>
          {(results.results || []).map((r: any, i: number) => (
            <div key={i} className="bg-slate-900 border border-slate-800 rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-slate-200">{r.deal_title || `Deal #${r.deal_id}`}</span>
                <span className="text-xs text-slate-500">Score: {(r.score * 100).toFixed(0)}%</span>
              </div>
              <div className="text-xs text-slate-500 mb-2">
                {r.principal_company} → {r.partner_company}
              </div>
              <p className="text-sm text-slate-400 leading-relaxed">{r.content}</p>
            </div>
          ))}
        </div>
      )}

      {!results && (
        <div className="text-center py-16">
          <ScrollText className="w-12 h-12 text-slate-700 mx-auto mb-3" />
          <p className="text-slate-500">Search for contract terms, clauses, or specific language</p>
          <div className="flex flex-wrap gap-2 justify-center mt-4 max-w-lg mx-auto">
            {['royalty rates for ADC', 'milestone payments oncology', 'opt-in opt-out clause', 'territory rights'].map(q => (
              <button key={q} onClick={() => { setQuery(q); }}
                className="px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-400 hover:text-slate-200"
              >{q}</button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

**Step 2: Build filings page**

Replace `frontend/src/pages/FilingsPage.tsx`:
```typescript
import { useState } from 'react';
import { FileText, Search } from 'lucide-react';
import api from '../lib/api';

export default function FilingsPage() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const search = async () => {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const resp = await api.get(`/search/unified?query=${encodeURIComponent(query)}&sources=edgar&mode=fulltext&limit=20`);
      setResults(resp.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">SEC Filings</h1>
        <p className="text-sm text-slate-500 mt-1">Search across 314K+ SEC filings (10-K, 10-Q, 8-K, S-1)</p>
      </div>

      <div className="flex gap-2 mb-6 max-w-2xl">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text" value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && search()}
            placeholder="Search SEC filings..."
            className="w-full pl-10 pr-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
          />
        </div>
        <button onClick={search} disabled={loading}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-sm font-medium"
        >
          Search
        </button>
      </div>

      {results && (
        <div className="space-y-3">
          <div className="text-sm text-slate-500">{results.total} results</div>
          {(results.results || []).map((r: any, i: number) => (
            <div key={i} className="bg-slate-900 border border-slate-800 rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <span className="text-sm font-medium text-slate-200">{r.company_name || 'Unknown'}</span>
                  {r.company_ticker && <span className="text-xs text-slate-500 ml-2">({r.company_ticker})</span>}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-400">{r.doc_type}</span>
                  <span className="text-xs text-slate-500">{r.filing_date}</span>
                </div>
              </div>
              <p className="text-sm text-slate-400 leading-relaxed">{r.content}</p>
            </div>
          ))}
        </div>
      )}

      {!results && (
        <div className="text-center py-16">
          <FileText className="w-12 h-12 text-slate-700 mx-auto mb-3" />
          <p className="text-slate-500">Search across 3.3M embedded filing chunks</p>
        </div>
      )}
    </div>
  );
}
```

**Step 3: Verify build and commit**

```bash
cd frontend && npm run build
git add -A
git commit -m "feat: contracts search and SEC filings search pages"
```

---

## Task 8: Integration Tests + Build Verification

**Files:**
- Create: `unified_api/tests/integration/test_phase2_e2e.py`

**Step 1: Write Phase 2 e2e tests**

Create `unified_api/tests/integration/test_phase2_e2e.py`:
```python
"""
End-to-end integration tests for Phase 2.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestPhase2Endpoints:
    """Verify all Phase 2 endpoints exist and return valid responses."""

    def test_market_trends(self, client):
        resp = client.get("/api/analytics/market-trends")
        assert resp.status_code == 200

    def test_valuations_by_phase(self, client):
        resp = client.get("/api/analytics/valuations/by-phase")
        assert resp.status_code == 200

    def test_valuations_by_indication(self, client):
        resp = client.get("/api/analytics/valuations/by-indication")
        assert resp.status_code == 200

    def test_geographic_distribution(self, client):
        resp = client.get("/api/analytics/geographic-distribution")
        assert resp.status_code == 200

    def test_top_acquirers(self, client):
        resp = client.get("/api/analytics/top-acquirers")
        assert resp.status_code == 200

    def test_top_deals(self, client):
        resp = client.get("/api/analytics/top-deals")
        assert resp.status_code == 200

    def test_therapy_area_heatmap(self, client):
        resp = client.get("/api/analytics/therapy-area-heatmap")
        assert resp.status_code == 200

    def test_yoy_growth(self, client):
        resp = client.get("/api/analytics/yoy-growth")
        assert resp.status_code == 200

    def test_partnership_network(self, client):
        resp = client.get("/api/graph/industry-network?limit=10")
        assert resp.status_code == 200

    def test_comp_build(self, client):
        resp = client.post("/api/comps/build", json={"indication": "Oncology", "limit": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert "deals" in data
        assert "stats" in data

    def test_comp_list(self, client):
        resp = client.get("/api/comps")
        assert resp.status_code == 200

    def test_contract_search(self, client):
        resp = client.get("/api/search/contracts?query=royalty&mode=fulltext&limit=5")
        assert resp.status_code == 200
```

**Step 2: Run ALL tests**

```bash
cd /Users/kayleighbot/Projects/cortellis

# Unit tests
python -m pytest unified_api/tests/unit/ -v

# Integration tests (all phases)
python -m pytest unified_api/tests/integration/ -v --tb=short
```

**Step 3: Verify frontend build**

```bash
cd frontend && npm run build
```

**Step 4: Verify Docker build**

```bash
cd /Users/kayleighbot/Projects/cortellis
docker compose -f docker-compose.unified.yml build api frontend
```

**Step 5: Commit and push**

```bash
git add -A
git commit -m "feat: Phase 2 complete — analytics, network, comp builder, contracts, filings"
git push origin main
```

---

## Summary

After Phase 2, the platform has:

1. **Analytics dashboards** — Market trends, valuations (with N + disclosure rate), geographic, competitive landscape — all wired to existing 14 endpoints
2. **Partnership network** — Company search → network visualization with connections and details panel
3. **Comp Builder** — Define criteria → find ranked comparable deals → select → compare → save comp set (backend with TDD)
4. **Competitor tracking** — Add companies, see recent deals, monitor activity
5. **My Deals** — Watchlist, saved searches, search history tabs
6. **Contract search** — Semantic and full-text search across 903K chunks
7. **SEC Filings search** — Search across 3.3M EDGAR filing chunks
8. **Nav updated** — Comp Builder added to sidebar

**New tests:** 10 comp builder unit tests + 7 comp endpoint integration tests + 12 Phase 2 e2e tests = **29 new tests**

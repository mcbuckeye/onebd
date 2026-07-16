import { useState, useEffect } from 'react';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, AreaChart, Area
} from 'recharts';
import { TrendingUp, DollarSign, Globe, Building2, Info } from 'lucide-react';
import { Link } from 'react-router-dom';
import api from '../lib/api';
import { decodeSourceEntities, formatDate } from '../lib/format';

type Tab = 'trends' | 'valuations' | 'geographic' | 'competitive';

function DataBadge({ n, disclosed }: { n: number; disclosed?: number }) {
  const disclosureLabel = disclosed !== undefined
    ? `, ${n > 0 ? ((disclosed / n) * 100).toFixed(0) : '0'}% disclosed`
    : '';
  return (
    <span className="inline-flex items-center gap-1 text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full">
      <Info className="w-3 h-3" />
      N={n}{disclosureLabel}
    </span>
  );
}

function formatValue(v: number | null): string {
  if (v === null || v === undefined) return '—';
  if (v === 0) return '$0';
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
  const [error, setError] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);
  const [therapyFilter, setTherapyFilter] = useState('');
  const [filterOptions, setFilterOptions] = useState<string[]>([]);

  const geographicRows = Array.isArray(geographic?.territories)
    ? geographic.territories
    : Array.isArray(geographic?.data)
      ? geographic.data
      : Array.isArray(geographic)
        ? geographic
        : [];
  const acquirerRows = Array.isArray(competitive?.topAcquirers?.acquirers)
    ? competitive.topAcquirers.acquirers
    : Array.isArray(competitive?.topAcquirers?.data)
      ? competitive.topAcquirers.data
      : Array.isArray(competitive?.topAcquirers)
        ? competitive.topAcquirers
        : [];
  const topDealRows = Array.isArray(competitive?.topDeals?.deals)
    ? competitive.topDeals.deals
    : Array.isArray(competitive?.topDeals?.data)
      ? competitive.topDeals.data
      : Array.isArray(competitive?.topDeals)
        ? competitive.topDeals
        : [];

  // Load filter options
  useEffect(() => {
    api.get('/search/filters').then(r => setFilterOptions(r.data.therapy_areas)).catch(() => {});
  }, []);

  // Load data based on tab
  useEffect(() => {
    setLoading(true);
    setError('');
    const params = therapyFilter ? `?therapy_area=${encodeURIComponent(therapyFilter)}` : '';
    const message = 'Analytics could not be loaded. Please retry.';

    if (tab === 'trends') {
      Promise.all([
        api.get(`/analytics/market-trends${params}`),
        api.get(`/analytics/agreement-type-distribution${params}`),
        api.get(`/analytics/yoy-growth${params}`),
      ]).then(([t, a, y]) => {
        setTrends(t.data);
        setAgreementTypes(a.data);
        setYoy(y.data);
      }).catch((requestError) => {
        console.error(requestError);
        setError(message);
      }).finally(() => setLoading(false));
    } else if (tab === 'valuations') {
      Promise.all([
        api.get('/analytics/valuations/by-phase'),
        api.get('/analytics/valuations/by-indication'),
      ]).then(([p, i]) => {
        setValuations({ byPhase: p.data, byIndication: i.data });
      }).catch((requestError) => {
        console.error(requestError);
        setError(message);
      }).finally(() => setLoading(false));
    } else if (tab === 'geographic') {
      api.get('/analytics/geographic-distribution')
        .then(r => setGeographic(r.data))
        .catch((requestError) => {
          console.error(requestError);
          setError(message);
        }).finally(() => setLoading(false));
    } else if (tab === 'competitive') {
      Promise.all([
        api.get('/analytics/top-acquirers'),
        api.get('/analytics/top-deals'),
      ]).then(([acq, deals]) => {
        setCompetitive({ topAcquirers: acq.data, topDeals: deals.data });
      }).catch((requestError) => {
        console.error(requestError);
        setError(message);
      }).finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, [tab, therapyFilter, refreshKey]);

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
          <p className="text-sm text-slate-500 mt-1">
            Market intelligence dashboards. Financial values are disclosed current
            projected totals in USD millions, not realized payments.
          </p>
        </div>
        {tab === 'trends' && (
          <select
            aria-label="Filter market trends by therapy area"
            value={therapyFilter}
            onChange={(e) => setTherapyFilter(e.target.value)}
            className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-300"
          >
            <option value="">All Therapy Areas</option>
            {filterOptions.map(ta => <option key={ta} value={ta}>{ta}</option>)}
          </select>
        )}
      </div>

      {error && (
        <div className="mb-6 flex items-center justify-between gap-3 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          <span>{error}</span>
          <button type="button" onClick={() => setRefreshKey(value => value + 1)} className="rounded border border-red-400/30 px-3 py-1 hover:bg-red-500/10">
            Retry
          </button>
        </div>
      )}

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
                  <DataBadge n={(trends.data || []).reduce((sum: number, row: any) => sum + (row.deal_count || 0), 0)} />
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
                  <h2 className="text-sm font-medium text-slate-400 mb-1">Year-over-Year Growth</h2>
                  <p className="mb-4 text-xs text-slate-600">The current year is compared with the same calendar period of the prior year.</p>
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
                        {yoy.data.map((row: any) => {
                          const growthRate = row.deal_count_growth_pct ?? row.growth_rate ?? null;
                          return (
                          <tr key={row.year} className="border-t border-slate-800/50">
                            <td className="py-2 text-slate-300">{row.year}{row.is_ytd ? ' YTD' : ''}</td>
                            <td className="py-2 text-slate-300">{row.deal_count?.toLocaleString()}</td>
                            <td className={`py-2 ${growthRate > 0 ? 'text-green-400' : growthRate < 0 ? 'text-red-400' : 'text-slate-500'}`}>
                              {growthRate !== null ? `${growthRate > 0 ? '+' : ''}${growthRate.toFixed(1)}%` : '—'}
                            </td>
                            <td className="py-2 text-slate-400">{formatValue(row.avg_value)}</td>
                          </tr>
                          );
                        })}
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
                          <td className="py-2 text-slate-400">{b.q1_value != null && b.q3_value != null ? `${formatValue(b.q1_value)} – ${formatValue(b.q3_value)}` : '—'}</td>
                          <td className="py-2 text-slate-500">{b.min_value != null && b.max_value != null ? `${formatValue(b.min_value)} – ${formatValue(b.max_value)}` : '—'}</td>
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
                  <BarChart data={geographicRows.slice(0, 20)} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis type="number" stroke="#475569" fontSize={12} />
                    <YAxis type="category" dataKey="territory_name" stroke="#475569" fontSize={10} width={150} />
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
                <h2 className="text-sm font-medium text-slate-400 mb-1">Top Partner-Role Organizations by Deal Count</h2>
                <p className="mb-4 text-xs text-slate-600">Cortellis “Partner” roles include licensees, collaborators, funders, and other counterparties; this is not limited to legal acquirers.</p>
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={acquirerRows.slice(0, 15)} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis type="number" stroke="#475569" fontSize={12} />
                    <YAxis type="category" dataKey="name" stroke="#475569" fontSize={10} width={180} />
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
                      {topDealRows.slice(0, 15).map((d: any, i: number) => (
                        <tr key={i} className="border-t border-slate-800/50">
                          <td className="py-2 text-slate-200 max-w-xs truncate">
                            <Link to={`/deals/${d.id}`} className="hover:text-blue-400 hover:underline">{decodeSourceEntities(d.title || `Deal ${d.id}`)}</Link>
                          </td>
                          <td className="py-2 text-slate-400">{d.principal || d.principal_company || '—'}</td>
                          <td className="py-2 text-slate-400">{d.partner || d.partner_company || '—'}</td>
                          <td className="py-2 text-slate-300 font-medium">{formatValue(d.total_value ?? d.value)}</td>
                          <td className="py-2 text-slate-500 text-xs">{formatDate(d.date_start || d.date)}</td>
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

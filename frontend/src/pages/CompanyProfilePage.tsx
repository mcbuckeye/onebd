import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  Activity,
  ArrowLeft,
  Building2,
  FileText,
  Network,
  Pill,
  TrendingUp,
  UserPlus,
  Users,
} from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import api, { CompanyProfile, CompanyStrategyIntelligence } from '../lib/api';

const COLORS = ['#3b82f6', '#8b5cf6', '#06b6d4', '#10b981', '#f59e0b', '#ef4444', '#ec4899', '#6366f1'];

function formatValue(v: number | null): string {
  if (v === null || v === undefined) return 'N/A';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
}

export default function CompanyProfilePage() {
  const { companyId } = useParams();
  const [profile, setProfile] = useState<CompanyProfile | null>(null);
  const [strategy, setStrategy] = useState<CompanyStrategyIntelligence | null>(null);
  const [strategyError, setStrategyError] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!companyId) return;
    setLoading(true);
    setError('');
    setProfile(null);
    setStrategy(null);
    setStrategyError('');
    api.get(`/company/${companyId}/profile`)
      .then(res => setProfile(res.data))
      .catch(err => setError(err.response?.data?.detail || 'Failed to load'))
      .finally(() => setLoading(false));
    api.get(`/company/${companyId}/strategy-intelligence?years=5&entrant_days=365`)
      .then(res => setStrategy(res.data))
      .catch(err => setStrategyError(
        err.response?.data?.detail || 'Strategy intelligence is unavailable',
      ));
  }, [companyId]);

  if (loading) return <div className="p-6 animate-pulse"><div className="h-8 w-64 bg-slate-800 rounded" /></div>;
  if (error) return <div className="p-6 text-red-400">{error}</div>;
  if (!profile) return null;

  const company = profile;
  const deal_summary = {
    total_deals: profile.total_deals,
    as_principal: profile.deals_as_principal,
    as_partner: profile.deals_as_partner,
    avg_deal_value: profile.avg_deal_value,
    total_deal_value: profile.total_deal_value,
  };
  const deal_timeline = profile.deals_by_year.map(item => ({
    year: item.year,
    count: item.deal_count,
  }));
  const {
    top_partners,
    therapeutic_focus,
    recent_deals,
    drugs,
    recent_sec_filings: sec_filings,
  } = profile;

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Back link */}
      <Link to="/search" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-300 mb-4">
        <ArrowLeft className="w-4 h-4" /> Back to search
      </Link>

      {/* Header */}
      <div className="flex items-start gap-4 mb-6">
        <div className="w-12 h-12 rounded-xl bg-blue-600/20 flex items-center justify-center">
          <Building2 className="w-6 h-6 text-blue-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-slate-100">{company.name}</h1>
          <div className="flex gap-3 mt-1 text-sm text-slate-500">
            {company.company_type && <span>{company.company_type}</span>}
            {company.ticker && <span>({company.ticker})</span>}
          </div>
        </div>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
        {[
          { label: 'Total Deals', value: deal_summary.total_deals?.toString() || '0' },
          { label: 'As Principal', value: deal_summary.as_principal?.toString() || '0' },
          { label: 'As Partner', value: deal_summary.as_partner?.toString() || '0' },
          { label: 'Avg Deal Value', value: formatValue(deal_summary.avg_deal_value) },
          { label: 'Total Value', value: formatValue(deal_summary.total_deal_value) },
        ].map(kpi => (
          <div key={kpi.label} className="bg-slate-900 border border-slate-800 rounded-lg p-3">
            <div className="text-xs text-slate-500">{kpi.label}</div>
            <div className="text-lg font-bold text-slate-200 mt-1">{kpi.value}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Deal timeline */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-slate-400 mb-4 flex items-center gap-2">
            <TrendingUp className="w-4 h-4" /> Deal Activity Over Time
          </h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={deal_timeline}>
              <XAxis dataKey="year" stroke="#475569" fontSize={12} />
              <YAxis stroke="#475569" fontSize={12} />
              <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }} />
              <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Therapeutic focus */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-slate-400 mb-4">Therapeutic Focus</h2>
          {therapeutic_focus?.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie
                  data={therapeutic_focus.slice(0, 8)}
                  dataKey="deal_count"
                  nameKey="indication"
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                  label={(props: any) => `${props.name?.slice(0, 15) || ''} (${((props.percent || 0) * 100).toFixed(0)}%)`}
                  labelLine={false}
                  fontSize={10}
                >
                  {therapeutic_focus.slice(0, 8).map((_: any, i: number) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-slate-500 text-sm">No indication data available</p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Top partners */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-slate-400 mb-4 flex items-center gap-2">
            <Users className="w-4 h-4" /> Top Partners
          </h2>
          <div className="space-y-2">
            {top_partners?.slice(0, 10).map(p => (
              <div key={p.company_id} className="flex items-center justify-between text-sm">
                <Link
                  to={`/company/${p.company_id}`}
                  className="text-slate-300 truncate hover:text-blue-400"
                >
                  {p.company_name}
                </Link>
                <span className="text-slate-500 text-xs">{p.deal_count} deals</span>
              </div>
            ))}
          </div>
        </div>

        {/* Drugs / Assets */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-slate-400 mb-4 flex items-center gap-2">
            <Pill className="w-4 h-4" /> Drug Portfolio
          </h2>
          <div className="space-y-2">
            {drugs?.slice(0, 10).map(d => (
              <Link key={d.id} to={`/drug/${d.id}`} className="flex items-center justify-between text-sm hover:bg-slate-800 rounded px-2 py-1 -mx-2">
                <span className="text-slate-300 truncate">{d.name}</span>
                <span className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-400">{d.phase_current || '—'}</span>
              </Link>
            ))}
          </div>
        </div>

        {/* SEC Filings */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-slate-400 mb-4 flex items-center gap-2">
            <FileText className="w-4 h-4" /> SEC Filings
          </h2>
          {sec_filings?.length > 0 ? (
            <div className="space-y-2">
              {sec_filings.slice(0, 10).map(f => (
                <div key={f.id} className="flex items-center justify-between gap-3 text-sm">
                  <Link to={`/filings/${f.id}`} className="text-slate-300 hover:text-blue-400">
                    {f.doc_type || 'Filing'}
                  </Link>
                  <span className="text-slate-500 text-xs">{f.filing_date}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-slate-500 text-sm">No SEC filings linked</p>
          )}
        </div>
      </div>

      {/* Grounded strategy and competitive intelligence */}
      {strategy && (
        <div className="mt-6 space-y-6">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
              <div>
                <h2 className="text-sm font-medium text-slate-300 flex items-center gap-2">
                  <Activity className="w-4 h-4 text-blue-400" />
                  Observed Deal Strategy
                </h2>
                <p className="text-xs text-slate-500 mt-1">
                  Deterministic patterns from {strategy.window.years} years of Cortellis deal evidence
                </p>
              </div>
              <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                strategy.activity.momentum === 'accelerating'
                  ? 'bg-green-500/15 text-green-400'
                  : strategy.activity.momentum === 'slowing'
                    ? 'bg-amber-500/15 text-amber-300'
                    : 'bg-blue-500/15 text-blue-300'
              }`}>
                {strategy.activity.momentum}
              </span>
            </div>
            <div className="space-y-3">
              {strategy.strategy_statements.map((statement, index) => (
                <div key={`${statement.evidence_type}:${index}`} className="border-l-2 border-blue-500/50 pl-3">
                  <p className="text-sm text-slate-300">{statement.claim}</p>
                  <p className="mt-1 text-[11px] text-slate-600">
                    {statement.evidence_type}
                    {statement.evidence_deal_ids?.length
                      ? ` · deal IDs ${statement.evidence_deal_ids.join(', ')}`
                      : ''}
                  </p>
                </div>
              ))}
            </div>
            <div className="mt-4 grid grid-cols-1 gap-3 border-t border-slate-800 pt-4 md:grid-cols-3">
              {[
                {
                  label: 'Indications',
                  values: strategy.focus.indications.slice(0, 5).map(item => `${item.name} (${item.deal_count})`),
                },
                {
                  label: 'Technologies',
                  values: strategy.focus.technologies.slice(0, 5).map(item => `${item.name} (${item.deal_count})`),
                },
                {
                  label: 'Agreement types',
                  values: strategy.focus.agreement_types.slice(0, 5).map(item => `${item.name} (${item.deal_count})`),
                },
              ].map(group => (
                <div key={group.label}>
                  <p className="mb-2 text-xs font-medium text-slate-500">{group.label}</p>
                  <div className="flex flex-wrap gap-1">
                    {group.values.length > 0 ? group.values.map(value => (
                      <span key={value} className="rounded bg-slate-800 px-2 py-1 text-[11px] text-slate-400">
                        {value}
                      </span>
                    )) : <span className="text-xs text-slate-600">No normalized data</span>}
                  </div>
                </div>
              ))}
            </div>
            <p className="mt-4 text-xs text-slate-500">{strategy.methodology.strategy_scope}</p>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
              <h2 className="text-sm font-medium text-slate-300 flex items-center gap-2 mb-1">
                <Network className="w-4 h-4 text-purple-400" />
                Deal-Portfolio Overlap Map
              </h2>
              <p className="text-xs text-slate-500 mb-4">{strategy.methodology.competitive_map}</p>
              {strategy.competitive_map.length > 0 ? (
                <div className="space-y-3">
                  {strategy.competitive_map.slice(0, 10).map(peer => (
                    <div key={peer.company_id} className="rounded-lg bg-slate-800/50 p-3">
                      <div className="flex items-center justify-between gap-3">
                        <Link to={`/company/${peer.company_id}`} className="font-medium text-slate-200 hover:text-blue-400">
                          {peer.company_name}
                        </Link>
                        <span className="text-sm font-semibold text-purple-300">{peer.overlap_score}%</span>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1">
                        {peer.shared_indications.slice(0, 3).map(item => (
                          <span key={`i:${item.id}`} className="rounded bg-blue-500/10 px-2 py-0.5 text-[11px] text-blue-300">{item.name}</span>
                        ))}
                        {peer.shared_technologies.slice(0, 3).map(item => (
                          <span key={`t:${item.id}`} className="rounded bg-cyan-500/10 px-2 py-0.5 text-[11px] text-cyan-300">{item.name}</span>
                        ))}
                        {peer.shared_assets.slice(0, 2).map(item => (
                          <span key={`d:${item.id}`} className="rounded bg-green-500/10 px-2 py-0.5 text-[11px] text-green-300">{item.name}</span>
                        ))}
                      </div>
                      <p className="mt-2 text-[11px] text-slate-600">
                        {peer.direct_partner_deals} direct shared deals · evidence deals {peer.evidence_deal_ids.slice(0, 5).join(', ')}
                      </p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-500">No recent normalized focus overlap was found.</p>
              )}
            </div>

            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
              <h2 className="text-sm font-medium text-slate-300 flex items-center gap-2 mb-1">
                <UserPlus className="w-4 h-4 text-green-400" />
                First-Observed Indication Entrants
              </h2>
              <p className="text-xs text-slate-500 mb-4">{strategy.methodology.new_entrant}</p>
              {strategy.new_indication_entrants.length > 0 ? (
                <div className="space-y-3">
                  {strategy.new_indication_entrants.slice(0, 12).map(entrant => (
                    <div key={`${entrant.company_id}:${entrant.indication_id}`} className="flex items-start justify-between gap-3 border-b border-slate-800 pb-3 last:border-0">
                      <div>
                        <Link to={`/company/${entrant.company_id}`} className="text-sm font-medium text-slate-200 hover:text-blue-400">
                          {entrant.company_name}
                        </Link>
                        <p className="mt-1 text-xs text-slate-500">{entrant.indication_name}</p>
                        <p className="mt-1 text-[11px] text-slate-600">Evidence deals {entrant.evidence_deal_ids.join(', ')}</p>
                      </div>
                      <div className="text-right text-xs text-slate-500">
                        <p>{new Date(`${entrant.first_observed_date}T00:00:00`).toLocaleDateString()}</p>
                        <p className="mt-1">{entrant.observed_deals} deals</p>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-500">No first-observed entrants in the selected period.</p>
              )}
            </div>
          </div>
        </div>
      )}

      {strategyError && (
        <div className="mt-6 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-300">
          {strategyError}
        </div>
      )}

      {/* Recent deals */}
      <div className="mt-6 bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h2 className="text-sm font-medium text-slate-400 mb-4">Recent Deals</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500 border-b border-slate-800">
              <th className="pb-2">Title</th>
              <th className="pb-2">Type</th>
              <th className="pb-2">Value</th>
              <th className="pb-2">Date</th>
            </tr>
          </thead>
          <tbody>
            {recent_deals?.map((d: any) => (
              <tr key={d.id} className="border-t border-slate-800/50">
                <td className="py-2 text-slate-200">{d.title}</td>
                <td className="py-2 text-slate-400 text-xs">{d.deal_type || d.agreement_type || '—'}</td>
                <td className="py-2 text-slate-300">{formatValue(d.total_value)}</td>
                <td className="py-2 text-slate-500 text-xs">{d.date_start || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

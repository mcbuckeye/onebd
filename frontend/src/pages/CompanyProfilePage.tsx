import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Building2, TrendingUp, Users, Pill, FileText, ArrowLeft } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import api from '../lib/api';

const COLORS = ['#3b82f6', '#8b5cf6', '#06b6d4', '#10b981', '#f59e0b', '#ef4444', '#ec4899', '#6366f1'];

function formatValue(v: number | null): string {
  if (v === null || v === undefined) return 'N/A';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
}

export default function CompanyProfilePage() {
  const { companyId } = useParams();
  const [profile, setProfile] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!companyId) return;
    setLoading(true);
    api.get(`/company/${companyId}/profile`)
      .then(res => setProfile(res.data))
      .catch(err => setError(err.response?.data?.detail || 'Failed to load'))
      .finally(() => setLoading(false));
  }, [companyId]);

  if (loading) return <div className="p-6 animate-pulse"><div className="h-8 w-64 bg-slate-800 rounded" /></div>;
  if (error) return <div className="p-6 text-red-400">{error}</div>;
  if (!profile) return null;

  const { company, deal_summary, deal_timeline, top_partners, therapeutic_focus, recent_deals, drugs, sec_filings } = profile;

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
                  dataKey="count"
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
            {top_partners?.slice(0, 10).map((p: any) => (
              <div key={p.name} className="flex items-center justify-between text-sm">
                <span className="text-slate-300 truncate">{p.name}</span>
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
            {drugs?.slice(0, 10).map((d: any) => (
              <Link key={d.id} to={`/drug/${d.id}`} className="flex items-center justify-between text-sm hover:bg-slate-800 rounded px-2 py-1 -mx-2">
                <span className="text-slate-300 truncate">{d.name}</span>
                <span className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-400">{d.phase}</span>
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
              {sec_filings.slice(0, 10).map((f: any) => (
                <div key={f.id} className="flex items-center justify-between text-sm">
                  <span className="text-slate-300">{f.doc_type}</span>
                  <span className="text-slate-500 text-xs">{f.filing_date}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-slate-500 text-sm">No SEC filings linked</p>
          )}
        </div>
      </div>

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

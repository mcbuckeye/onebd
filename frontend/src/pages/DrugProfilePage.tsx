import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Pill, ArrowLeft, Building2, Globe, DollarSign } from 'lucide-react';
import api from '../lib/api';

function formatValue(v: number | null): string {
  if (v === null || v === undefined) return 'N/A';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
}

export default function DrugProfilePage() {
  const { drugId } = useParams();
  const [profile, setProfile] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!drugId) return;
    api.get(`/drug/${drugId}/profile`)
      .then(res => setProfile(res.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [drugId]);

  if (loading) return <div className="p-6 animate-pulse"><div className="h-8 w-64 bg-slate-800 rounded" /></div>;
  if (!profile) return <div className="p-6 text-red-400">Drug not found</div>;

  const { drug, deal_history, territory_rights, financial_summary, related_companies } = profile;

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <Link to="/search" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-300 mb-4">
        <ArrowLeft className="w-4 h-4" /> Back
      </Link>

      <div className="flex items-start gap-4 mb-6">
        <div className="w-12 h-12 rounded-xl bg-purple-600/20 flex items-center justify-center">
          <Pill className="w-6 h-6 text-purple-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-slate-100">{drug.name}</h1>
          <div className="flex gap-3 mt-1">
            {drug.phase && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-400">{drug.phase}</span>
            )}
          </div>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-6">
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
          <div className="text-xs text-slate-500">Total Deals</div>
          <div className="text-lg font-bold text-slate-200 mt-1">{financial_summary?.deal_count || 0}</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
          <div className="text-xs text-slate-500">Total Deal Value</div>
          <div className="text-lg font-bold text-slate-200 mt-1">{formatValue(financial_summary?.total_value)}</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
          <div className="text-xs text-slate-500">Related Companies</div>
          <div className="text-lg font-bold text-slate-200 mt-1">{related_companies?.length || 0}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        {/* Related companies */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-slate-400 mb-4 flex items-center gap-2">
            <Building2 className="w-4 h-4" /> Related Companies
          </h2>
          <div className="space-y-2">
            {related_companies?.map((c: any, i: number) => (
              <div key={i} className="flex items-center justify-between text-sm">
                <span className="text-slate-300 truncate">{c.name}</span>
                <span className="text-xs text-slate-500">{c.role}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Territory rights */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-slate-400 mb-4 flex items-center gap-2">
            <Globe className="w-4 h-4" /> Territory Rights
          </h2>
          {territory_rights?.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500 border-b border-slate-800">
                    <th className="pb-2">Territory</th>
                    <th className="pb-2">Rights Holder</th>
                    <th className="pb-2">Deal</th>
                  </tr>
                </thead>
                <tbody>
                  {territory_rights.map((t: any, i: number) => (
                    <tr key={i} className="border-t border-slate-800/50">
                      <td className="py-2 text-slate-300">{t.territory}</td>
                      <td className="py-2 text-slate-400">{t.holder}</td>
                      <td className="py-2 text-slate-500 text-xs">#{t.deal_id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-slate-500 text-sm">No territory data available</p>
          )}
        </div>
      </div>

      {/* Deal history */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h2 className="text-sm font-medium text-slate-400 mb-4 flex items-center gap-2">
          <DollarSign className="w-4 h-4" /> Deal History
        </h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500 border-b border-slate-800">
              <th className="pb-2">Title</th>
              <th className="pb-2">Principal</th>
              <th className="pb-2">Partner</th>
              <th className="pb-2">Value</th>
              <th className="pb-2">Date</th>
            </tr>
          </thead>
          <tbody>
            {deal_history?.map((d: any) => (
              <tr key={d.id} className="border-t border-slate-800/50">
                <td className="py-2 text-slate-200">{d.title}</td>
                <td className="py-2 text-slate-400">{d.principal_company || '—'}</td>
                <td className="py-2 text-slate-400">{d.partner_company || '—'}</td>
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

import { useState } from 'react';
import { Scale, Save, Info, TrendingUp, FileDown } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import api from '../lib/api';
import EmptyState from '../components/EmptyState';
import { useToast } from '../contexts/ToastContext';

function formatValue(v: number | null): string {
  if (v === null || v === undefined) return '—';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
}

export default function CompBuilderPage() {
  const toast = useToast();
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
      toast.success('Comp set saved successfully');
    } catch (e) {
      console.error(e);
      toast.error('Failed to save comp set');
    }
  };

  const exportPptx = async () => {
    const selectedDealsList = results?.deals?.filter((d: any) => selected.has(d.id)) || [];
    try {
      const res = await api.post('/export/comps/pptx', {
        title: saveName || 'Comparable Deal Analysis',
        criteria,
        deals: selectedDealsList,
        stats: results?.stats || {},
      }, { responseType: 'blob' });
      
      const blob = new Blob([res.data]);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'comp-analysis.pptx';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      toast.success('PowerPoint exported successfully');
    } catch (e) {
      console.error('PPTX export failed:', e);
      toast.error('Failed to export PowerPoint');
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

      {!results && !loading && (
        <EmptyState
          icon={TrendingUp}
          title="Ready to build your comp set"
          description="Define your target deal profile above and we'll find comparable deals for benchmarking"
        />
      )}

      {results && (
        <>
          {results.deals.length === 0 ? (
            <EmptyState
              icon={Scale}
              title="No comparable deals found"
              description="Try broadening your criteria or adjusting the date range"
            />
          ) : (
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
                <button onClick={exportPptx} disabled={selected.size === 0}
                  className="px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 hover:bg-slate-700 flex items-center gap-1 disabled:opacity-50"
                >
                  <FileDown className="w-3 h-3" /> Export PPTX
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
                <Scale className="w-4 h-4" /> Selected Deals — Value Distribution
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
        </>
      )}
    </div>
  );
}

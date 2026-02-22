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

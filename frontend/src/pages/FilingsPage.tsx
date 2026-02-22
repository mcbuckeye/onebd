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

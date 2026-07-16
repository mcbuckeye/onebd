import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Building2, FileText, Search } from 'lucide-react';
import api from '../lib/api';
import { formatDate } from '../lib/format';

interface FilingResult {
  document_id: number;
  chunk_id?: number;
  content: string;
  company_name?: string;
  company_ticker?: string;
  doc_type?: string;
  accession_no?: string;
  filing_date?: string;
}

export default function FilingsPage() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<FilingResult[]>([]);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadRecent = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await api.get('/edgar/filings', {
        params: { limit: 20 },
      });
      setResults(response.data.map((filing: any) => ({
        document_id: filing.id,
        content: filing.title || `${filing.doc_type || 'SEC'} filing`,
        company_name: filing.company_name,
        company_ticker: filing.company_ticker,
        doc_type: filing.doc_type,
        accession_no: filing.accession_no,
        filing_date: filing.filing_date || filing.published_at,
      })));
      setSearched(false);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load recent filings');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadRecent();
  }, []);

  const search = async () => {
    const normalized = query.trim();
    if (normalized.length < 3) {
      setError('Enter at least three characters to search filing content.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const response = await api.get('/edgar/search', {
        params: {
          query: normalized,
          mode: 'fulltext',
          limit: 40,
        },
      });
      setResults((response.data || []).map((item: any) => ({
        ...item,
        content: item.text,
      })));
      setSearched(true);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Filing search failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">SEC Filings</h1>
        <p className="text-sm text-slate-500 mt-1">Search SEC filing content and open source documents with filing-level deduplication</p>
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
        <button type="button" onClick={search} disabled={loading}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-sm font-medium"
        >
          {loading ? 'Searching…' : 'Search'}
        </button>
      </div>

      {error && (
        <div className="mb-5 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {results.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between text-sm text-slate-500">
            <span>{searched ? `${results.length} matching documents (best excerpt from each)` : 'Recently filed documents'}</span>
            {searched && (
              <button type="button" onClick={loadRecent} className="hover:text-slate-300">
                Show recent filings
              </button>
            )}
          </div>
          {results.map((result, index) => (
            <Link
              key={`${result.document_id}-${result.chunk_id ?? index}`}
              to={`/filings/${result.document_id}${result.chunk_id
                ? `?chunk=${result.chunk_id}&q=${encodeURIComponent(query.trim())}`
                : ''}`}
              className="group block rounded-xl border border-slate-800 bg-slate-900 p-4 transition-colors hover:border-blue-500/50 hover:bg-slate-800/70"
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex min-w-0 items-center gap-2">
                  <Building2 className="h-4 w-4 shrink-0 text-slate-500" />
                  <span className="truncate text-sm font-medium text-slate-200">{result.company_name || 'Unknown company'}</span>
                  {result.company_ticker && <span className="text-xs text-slate-500">({result.company_ticker})</span>}
                </div>
                <div className="ml-3 flex shrink-0 items-center gap-2">
                  <span className="rounded-full bg-slate-700 px-2 py-0.5 text-xs text-slate-300">{result.doc_type || 'Filing'}</span>
                  <span className="hidden text-xs text-slate-500 sm:inline">{formatDate(result.filing_date)}</span>
                  <ArrowRight className="h-4 w-4 text-slate-600 transition-transform group-hover:translate-x-0.5 group-hover:text-blue-400" />
                </div>
              </div>
              <p className="line-clamp-4 text-sm leading-relaxed text-slate-400">{result.content}</p>
              {result.accession_no && (
                <p className="mt-2 font-mono text-[11px] text-slate-600">{result.accession_no}</p>
              )}
            </Link>
          ))}
        </div>
      )}

      {!loading && !error && results.length === 0 && (
        <div className="text-center py-16">
          <FileText className="w-12 h-12 text-slate-700 mx-auto mb-3" />
          <p className="text-slate-500">No filing excerpts matched that query.</p>
        </div>
      )}
    </div>
  );
}

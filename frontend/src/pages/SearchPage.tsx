import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Filter, ChevronDown, X, Search as SearchIcon, Download } from 'lucide-react';
import api, { SearchFilters, SearchResponse, FilterOptions } from '../lib/api';
import EmptyState from '../components/EmptyState';
import DealDetailSlidePanel from '../components/DealDetailSlidePanel';

function FilterSelect({ label, options, value, onChange, multi = false }: {
  label: string;
  options: string[];
  value: string | string[];
  onChange: (v: any) => void;
  multi?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const selected = multi ? (value as string[]) : (value ? [value as string] : []);

  const toggle = (opt: string) => {
    if (multi) {
      const cur = value as string[];
      onChange(cur.includes(opt) ? cur.filter(v => v !== opt) : [...cur, opt]);
    } else {
      onChange(opt === value ? '' : opt);
      setOpen(false);
    }
  };

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs transition-colors ${
          selected.length > 0
            ? 'border-blue-500/50 bg-blue-500/10 text-blue-400'
            : 'border-slate-700 bg-slate-800 text-slate-400 hover:border-slate-600'
        }`}
      >
        {label}{selected.length > 0 && ` (${selected.length})`}
        <ChevronDown className="w-3 h-3" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute z-20 mt-1 w-64 max-w-[calc(100vw-2rem)] max-h-60 overflow-y-auto bg-slate-800 border border-slate-700 rounded-lg shadow-xl">
            {options.map(opt => (
              <button
                key={opt}
                onClick={() => toggle(opt)}
                className={`w-full text-left px-3 py-2 text-xs hover:bg-slate-700 ${
                  selected.includes(opt) ? 'text-blue-400 bg-blue-500/10' : 'text-slate-300'
                }`}
              >
                {opt}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function formatValue(v: number | null): string {
  if (v === null || v === undefined) return '—';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
}

export default function SearchPage() {
  const [filterOptions, setFilterOptions] = useState<FilterOptions | null>(null);
  const [filters, setFilters] = useState<SearchFilters>({});
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [disclosedOnly, setDisclosedOnly] = useState(false);
  const [selectedDealId, setSelectedDealId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [indicationText, setIndicationText] = useState('');
  const [technologyText, setTechnologyText] = useState('');

  useEffect(() => {
    api.get('/search/filters').then(res => setFilterOptions(res.data)).catch(console.error);
  }, []);

  const search = useCallback(async (p = 1) => {
    if (filters.date_from && filters.date_to && filters.date_from > filters.date_to) {
      setError('Deal date from must be on or before deal date to.');
      return;
    }
    if (filters.value_min !== undefined && filters.value_max !== undefined && filters.value_min > filters.value_max) {
      setError('Minimum disclosed total must not exceed the maximum.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const res = await api.post(`/search/deals?page=${p}&page_size=25`, {
        ...filters,
        disclosed_only: disclosedOnly,
      });
      setResults(res.data);
      setPage(p);
      const activeFilters = {
        ...filters,
        ...(disclosedOnly ? { disclosed_only: true } : {}),
      };
      if (p === 1 && Object.keys(activeFilters).length > 0) {
        const query = Object.entries(activeFilters)
          .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(', ') : value}`)
          .join(' · ');
        api.post('/search/history', null, {
          params: { query, search_type: 'deals', result_count: res.data.total },
        }).catch(() => undefined);
      }
    } catch (e: any) {
      console.error(e);
      const detail = e.response?.data?.detail;
      setError(
        typeof detail === 'string'
          ? detail
          : Array.isArray(detail)
            ? detail.map(item => item?.msg || 'Invalid filter').join('; ')
            : 'Deal search failed',
      );
    } finally {
      setLoading(false);
    }
  }, [filters, disclosedOnly]);

  useEffect(() => {
    search(1);
  }, []);

  const clearFilters = () => {
    setFilters({});
    setDisclosedOnly(false);
    setIndicationText('');
    setTechnologyText('');
  };

  const hasFilters = Object.values(filters).some(v =>
    Array.isArray(v) ? v.length > 0 : v !== undefined && v !== '' && v !== null
  ) || disclosedOnly;

  const exportResults = async (format: 'csv' | 'excel') => {
    try {
      const endpoint = format === 'csv' ? '/export/deals/csv' : '/export/deals/excel';
      const res = await api.post(endpoint, {
        ...filters,
        disclosed_only: disclosedOnly,
      }, { responseType: 'blob' });
      
      const ext = format === 'csv' ? 'csv' : 'xlsx';
      const blob = new Blob([res.data]);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `deals-export.${ext}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (e) {
      console.error('Export failed:', e);
      setError('Export failed. Narrow the filters and try again.');
    }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Deal Search</h1>
          <p className="text-sm text-slate-500 mt-1">
            {results ? `${results.total.toLocaleString()} deals` : 'Search synchronized pharmaceutical deals'}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => exportResults('csv')}
            disabled={!results || results.total === 0}
            className="flex items-center gap-2 px-4 py-2 bg-slate-800 border border-slate-700 hover:bg-slate-700 rounded-lg text-sm text-slate-300 transition-colors disabled:opacity-50"
          >
            <Download className="w-4 h-4" />
            Export CSV
          </button>
          <button
            onClick={() => exportResults('excel')}
            disabled={!results || results.total === 0}
            className="flex items-center gap-2 px-4 py-2 bg-slate-800 border border-slate-700 hover:bg-slate-700 rounded-lg text-sm text-slate-300 transition-colors disabled:opacity-50"
          >
            <Download className="w-4 h-4" />
            Export Excel
          </button>
          <button
            onClick={() => search(1)}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm font-medium transition-colors"
          >
            Search
          </button>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2 mb-4 overflow-x-auto pb-2">
        <Filter className="w-4 h-4 text-slate-500 flex-shrink-0" />
        {filterOptions && (
          <>
            <FilterSelect
              label="Therapy Area"
              options={filterOptions.therapy_areas}
              value={filters.therapy_area || ''}
              onChange={(v: string) => setFilters(f => ({ ...f, therapy_area: v || undefined }))}
            />
            <FilterSelect
              label="Agreement Type"
              options={filterOptions.deal_types}
              value={filters.deal_type || []}
              onChange={(v: string[]) => setFilters(f => ({ ...f, deal_type: v.length ? v : undefined }))}
              multi
            />
            <FilterSelect
              label="Phase"
              options={filterOptions.phases}
              value={filters.phase || []}
              onChange={(v: string[]) => setFilters(f => ({ ...f, phase: v.length ? v : undefined }))}
              multi
            />
            <FilterSelect
              label="Status"
              options={filterOptions.statuses}
              value={filters.status || []}
              onChange={(v: string[]) => setFilters(f => ({ ...f, status: v.length ? v : undefined }))}
              multi
            />
          </>
        )}

        {/* Disclosed only toggle */}
        <button
          type="button"
          role="switch"
          aria-checked={disclosedOnly}
          onClick={() => setDisclosedOnly(!disclosedOnly)}
          className={`px-3 py-1.5 rounded-lg border text-xs transition-colors ${
            disclosedOnly
              ? 'border-green-500/50 bg-green-500/10 text-green-400'
              : 'border-slate-700 bg-slate-800 text-slate-400 hover:border-slate-600'
          }`}
        >
          Disclosed Only
        </button>

        {hasFilters && (
          <button onClick={clearFilters} className="px-2 py-1.5 text-xs text-slate-500 hover:text-slate-300">
            <X className="w-3 h-3 inline mr-1" /> Clear
          </button>
        )}
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Company search input */}
      <div className="flex flex-wrap gap-2 mb-3">
        <input
          type="text"
          placeholder="Filter by company name..."
          value={filters.company || ''}
          onChange={(e) => setFilters(f => ({ ...f, company: e.target.value || undefined }))}
          onKeyDown={(e) => e.key === 'Enter' && search(1)}
          className="flex-1 max-w-sm min-w-0 px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
        />
        <button
          type="button"
          onClick={() => setShowAdvanced(current => !current)}
          aria-expanded={showAdvanced}
          className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-400 hover:text-slate-200"
        >
          {showAdvanced ? 'Hide advanced filters' : 'Advanced filters'}
        </button>
      </div>

      {showAdvanced && (
        <div className="mb-6 grid gap-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-xs text-slate-500">
            Indications (comma-separated)
            <input
              type="text"
              value={indicationText}
              onChange={(event) => {
                setIndicationText(event.target.value);
                const values = event.target.value.split(',').map(value => value.trim()).filter(Boolean);
                setFilters(current => ({ ...current, indication: values.length ? values : undefined }));
              }}
              className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
            />
          </label>
          <label className="text-xs text-slate-500">
            Technologies or modalities (comma-separated)
            <input
              type="text"
              value={technologyText}
              onChange={(event) => {
                setTechnologyText(event.target.value);
                const values = event.target.value.split(',').map(value => value.trim()).filter(Boolean);
                setFilters(current => ({ ...current, technology: values.length ? values : undefined }));
              }}
              className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
            />
          </label>
          <label className="text-xs text-slate-500">
            Deal date from
            <input type="date" value={filters.date_from || ''} onChange={(event) => setFilters(current => ({ ...current, date_from: event.target.value || undefined }))} className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200" />
          </label>
          <label className="text-xs text-slate-500">
            Deal date to
            <input type="date" value={filters.date_to || ''} onChange={(event) => setFilters(current => ({ ...current, date_to: event.target.value || undefined }))} className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200" />
          </label>
          <label className="text-xs text-slate-500">
            Minimum disclosed total (USD millions)
            <input type="number" min="0" step="any" value={filters.value_min ?? ''} onChange={(event) => setFilters(current => ({ ...current, value_min: event.target.value === '' ? undefined : Number(event.target.value) }))} className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200" />
          </label>
          <label className="text-xs text-slate-500">
            Maximum disclosed total (USD millions)
            <input type="number" min="0" step="any" value={filters.value_max ?? ''} onChange={(event) => setFilters(current => ({ ...current, value_max: event.target.value === '' ? undefined : Number(event.target.value) }))} className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200" />
          </label>
          <p className="self-end text-xs leading-5 text-slate-600 sm:col-span-2">
            Text filters use case-insensitive contains matching. Financial values
            are disclosed current projected totals in USD millions, not realized payments.
          </p>
        </div>
      )}

      {/* Results table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500 bg-slate-900/50">
                <th className="px-4 py-3 font-medium">Deal</th>
                <th className="px-4 py-3 font-medium">Principal</th>
                <th className="px-4 py-3 font-medium">Partner</th>
                <th className="px-4 py-3 font-medium">Type</th>
                <th className="px-4 py-3 font-medium">Value (USD M)</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Date</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i}>
                    <td colSpan={7} className="px-4 py-3"><div className="h-4 bg-slate-800 rounded animate-pulse" /></td>
                  </tr>
                ))
              ) : results?.results.length === 0 ? (
                <tr>
                  <td colSpan={7}>
                    <EmptyState
                      icon={SearchIcon}
                      title="No deals found"
                      description="Try adjusting your filters or search terms"
                      action={{ label: 'Clear Filters', onClick: clearFilters }}
                    />
                  </td>
                </tr>
              ) : results?.results.map(deal => (
                <tr 
                  key={deal.id} 
                  onClick={() => setSelectedDealId(deal.id)}
                  className="border-t border-slate-800/50 hover:bg-slate-800/30 cursor-pointer"
                >
                  <td className="px-4 py-3">
                    <span className="text-slate-200 hover:text-blue-400 font-medium">
                      {deal.title}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-400">
                    {deal.principal_company ? (
                      deal.principal_company_id ? (
                        <Link to={`/company/${deal.principal_company_id}`} className="hover:text-blue-400">{deal.principal_company}</Link>
                      ) : (
                        <span>{deal.principal_company}</span>
                      )
                    ) : '—'}
                  </td>
                  <td className="px-4 py-3 text-slate-400">
                    {deal.partner_company ? (
                      deal.partner_company_id ? (
                        <Link to={`/company/${deal.partner_company_id}`} className="hover:text-blue-400">{deal.partner_company}</Link>
                      ) : (
                        <span>{deal.partner_company}</span>
                      )
                    ) : '—'}
                  </td>
                  <td className="px-4 py-3 text-slate-500 text-xs">{deal.deal_type || '—'}</td>
                  <td className="px-4 py-3 text-slate-300">{formatValue(deal.total_value)}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${
                      deal.status === 'Active' ? 'bg-green-500/10 text-green-400' :
                      deal.status === 'Completed' ? 'bg-blue-500/10 text-blue-400' :
                      'bg-slate-700 text-slate-400'
                    }`}>{deal.status || '—'}</span>
                  </td>
                  <td className="px-4 py-3 text-slate-500 text-xs">{deal.date_start || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {results && results.total > 25 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-slate-800">
            <span className="text-xs text-slate-500">
              Page {page} of {Math.ceil(results.total / 25)}
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => search(page - 1)}
                disabled={page <= 1}
                className="px-3 py-1 text-xs bg-slate-800 rounded hover:bg-slate-700 disabled:opacity-50"
              >
                Previous
              </button>
              <button
                onClick={() => search(page + 1)}
                disabled={page >= Math.ceil(results.total / 25)}
                className="px-3 py-1 text-xs bg-slate-800 rounded hover:bg-slate-700 disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Deal Detail Slide Panel */}
      <DealDetailSlidePanel 
        dealId={selectedDealId} 
        onClose={() => setSelectedDealId(null)} 
      />
    </div>
  );
}

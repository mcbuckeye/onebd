import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Building2, Plus, Search, X } from 'lucide-react';
import api from '../lib/api';

interface TrackedCompetitor {
  id: number;
  company_id: number;
  company_name: string;
  company_type: string | null;
  total_deals: number;
  created_at: string | null;
}

export default function CompetitorsPage() {
  const [competitors, setCompetitors] = useState<TrackedCompetitor[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [companyDeals, setCompanyDeals] = useState<Record<number, any[]>>({});

  // Load tracked competitors on mount
  useEffect(() => {
    loadCompetitors();
  }, []);

  const loadCompetitors = async () => {
    try {
      setLoading(true);
      const resp = await api.get('/competitors');
      const trackedCompanies = resp.data;
      setCompetitors(trackedCompanies);

      // Load recent deals for each competitor
      for (const comp of trackedCompanies) {
        try {
          const dealsResp = await api.post('/search/deals?page=1&page_size=5', {
            company: comp.company_name,
          });
          setCompanyDeals(prev => ({ ...prev, [comp.company_id]: dealsResp.data.results || [] }));
        } catch (e) {
          console.error(`Failed to load deals for ${comp.company_name}`, e);
        }
      }
    } catch (e) {
      console.error('Failed to load competitors', e);
    } finally {
      setLoading(false);
    }
  };

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
    if (competitors.some(c => c.company_id === company.id)) return;

    setSearchQuery('');
    setSuggestions([]);

    try {
      // Call backend to persist the tracked competitor
      await api.post('/competitors', { company_id: company.id });
      
      // Reload the list from backend
      await loadCompetitors();
    } catch (e: any) {
      console.error('Failed to add competitor', e);
      if (e.response?.status === 409) {
        alert('Already tracking this company');
      } else if (e.response?.status === 404) {
        alert('Company not found');
      } else {
        alert('Failed to add competitor');
      }
    }
  };

  const removeCompetitor = async (companyId: number) => {
    try {
      await api.delete(`/competitors/${companyId}`);
      
      // Update local state
      setCompetitors(prev => prev.filter(c => c.company_id !== companyId));
      setCompanyDeals(prev => { const next = { ...prev }; delete next[companyId]; return next; });
    } catch (e: any) {
      console.error('Failed to remove competitor', e);
      if (e.response?.status === 404) {
        // Already removed, update UI anyway
        setCompetitors(prev => prev.filter(c => c.company_id !== companyId));
        setCompanyDeals(prev => { const next = { ...prev }; delete next[companyId]; return next; });
      } else {
        alert('Failed to remove competitor');
      }
    }
  };

  if (loading) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-slate-100">Competitor Intelligence</h1>
          <p className="text-sm text-slate-500 mt-1">Track competitor deal activity and strategy</p>
        </div>
        <div className="text-center py-20">
          <div className="text-slate-500">Loading competitors...</div>
        </div>
      </div>
    );
  }

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
                    <Link to={`/company/${comp.company_id}`} className="text-lg font-semibold text-slate-200 hover:text-blue-400">
                      {comp.company_name}
                    </Link>
                    <div className="text-xs text-slate-500">{comp.company_type || 'Company'}</div>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <div className="text-right">
                    <div className="text-sm font-medium text-slate-300">{comp.total_deals} deals</div>
                    {comp.created_at && (
                      <div className="text-xs text-slate-500">
                        Added {new Date(comp.created_at).toLocaleDateString()}
                      </div>
                    )}
                  </div>
                  <button onClick={() => removeCompetitor(comp.company_id)} className="p-1 hover:bg-slate-800 rounded">
                    <X className="w-4 h-4 text-slate-500" />
                  </button>
                </div>
              </div>

              {/* Recent deals for this competitor */}
              {companyDeals[comp.company_id] && companyDeals[comp.company_id].length > 0 && (
                <div className="border-t border-slate-800 pt-3">
                  <h3 className="text-xs text-slate-500 mb-2">Recent Deals</h3>
                  <div className="space-y-1">
                    {companyDeals[comp.company_id].map((deal: any) => (
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

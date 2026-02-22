import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Building2, Plus, Search, X } from 'lucide-react';
import api from '../lib/api';

interface TrackedCompetitor {
  id: number;
  name: string;
  company_type: string | null;
  recent_deals: number;
  total_deals: number;
}

export default function CompetitorsPage() {
  const [competitors, setCompetitors] = useState<TrackedCompetitor[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [companyDeals, setCompanyDeals] = useState<Record<number, any[]>>({});

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
    if (competitors.some(c => c.id === company.id)) return;

    setSearchQuery('');
    setSuggestions([]);

    try {
      // Fetch company profile to get deal counts
      const resp = await api.get(`/company/${company.id}/profile`);
      const profile = resp.data;

      const newComp: TrackedCompetitor = {
        id: company.id,
        name: company.name,
        company_type: company.company_type,
        recent_deals: profile.deal_summary?.recent_deals_12m || 0,
        total_deals: profile.deal_summary?.total_deals || 0,
      };

      setCompetitors(prev => [...prev, newComp]);

      // Load recent deals
      const dealsResp = await api.post('/search/deals?page=1&page_size=5', {
        company: company.name,
      });
      setCompanyDeals(prev => ({ ...prev, [company.id]: dealsResp.data.results || [] }));
    } catch (e) {
      console.error(e);
      // Still add with basic info
      setCompetitors(prev => [...prev, {
        id: company.id,
        name: company.name,
        company_type: company.company_type,
        recent_deals: 0,
        total_deals: 0,
      }]);
    }
  };

  const removeCompetitor = (id: number) => {
    setCompetitors(prev => prev.filter(c => c.id !== id));
    setCompanyDeals(prev => { const next = { ...prev }; delete next[id]; return next; });
  };

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
                    <Link to={`/company/${comp.id}`} className="text-lg font-semibold text-slate-200 hover:text-blue-400">
                      {comp.name}
                    </Link>
                    <div className="text-xs text-slate-500">{comp.company_type || 'Company'}</div>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <div className="text-right">
                    <div className="text-sm font-medium text-slate-300">{comp.total_deals} deals</div>
                    <div className="text-xs text-slate-500">{comp.recent_deals} in last 12m</div>
                  </div>
                  <button onClick={() => removeCompetitor(comp.id)} className="p-1 hover:bg-slate-800 rounded">
                    <X className="w-4 h-4 text-slate-500" />
                  </button>
                </div>
              </div>

              {/* Recent deals for this competitor */}
              {companyDeals[comp.id] && companyDeals[comp.id].length > 0 && (
                <div className="border-t border-slate-800 pt-3">
                  <h3 className="text-xs text-slate-500 mb-2">Recent Deals</h3>
                  <div className="space-y-1">
                    {companyDeals[comp.id].map((deal: any) => (
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

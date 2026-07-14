import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Bell, Building2, Check, Plus, Search, UserPlus, X } from 'lucide-react';
import api from '../lib/api';

interface CompetitorDeal {
  id: number;
  title: string;
  agreement_type: string | null;
  status: string | null;
  date_start: string | null;
}

interface TrackedCompetitor {
  id: number;
  company_id: number;
  company_name: string;
  company_type: string | null;
  total_deals: number;
  created_at: string | null;
  entrant_alerts_enabled: boolean;
  entrant_baselined_at: string | null;
  entrant_last_checked_at: string | null;
  unread_entrant_alerts: number;
  recent_deals: CompetitorDeal[];
}

interface EntrantAlert {
  id: number;
  subject_company_id: number;
  subject_company_name: string;
  entrant_company_id: number;
  entrant_company_name: string;
  indication_id: number;
  indication_name: string;
  first_observed_date: string;
  observed_deals: number;
  evidence_deal_ids: number[];
  content: string;
  created_at: string;
  read_at: string | null;
}

interface CompanySuggestion {
  id: number;
  name: string;
  company_type: string | null;
}

export default function CompetitorsPage() {
  const [competitors, setCompetitors] = useState<TrackedCompetitor[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [suggestions, setSuggestions] = useState<CompanySuggestion[]>([]);
  const [entrantAlerts, setEntrantAlerts] = useState<EntrantAlert[]>([]);

  // Load tracked competitors on mount
  useEffect(() => {
    loadCompetitors();
  }, []);

  const loadCompetitors = async () => {
    try {
      setLoading(true);
      // The list call also applies any forward-only alert schema migration.
      const competitorResponse = await api.get('/competitors');
      const alertResponse = await api.get('/competitors/entrant-alerts');
      setCompetitors(competitorResponse.data);
      setEntrantAlerts(alertResponse.data);
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
  const addCompetitor = async (company: CompanySuggestion) => {
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
      setCompetitors(prev => prev.filter(c => c.company_id !== companyId));
      setEntrantAlerts(prev => prev.filter(a => a.subject_company_id !== companyId));
    } catch (e: any) {
      console.error('Failed to remove competitor', e);
      if (e.response?.status === 404) {
        // Already removed, update UI anyway
        setCompetitors(prev => prev.filter(c => c.company_id !== companyId));
        setEntrantAlerts(prev => prev.filter(a => a.subject_company_id !== companyId));
      } else {
        alert('Failed to remove competitor');
      }
    }
  };

  const toggleEntrantAlerts = async (competitor: TrackedCompetitor) => {
    const enabled = !competitor.entrant_alerts_enabled;
    try {
      const response = await api.patch(
        `/competitors/companies/${competitor.company_id}/entrant-alerts`,
        { enabled },
      );
      setCompetitors(prev => prev.map(item => item.company_id === competitor.company_id
        ? {
            ...item,
            entrant_alerts_enabled: response.data.entrant_alerts_enabled,
            entrant_baselined_at: response.data.entrant_baselined_at,
            entrant_last_checked_at: response.data.entrant_last_checked_at,
          }
        : item));
    } catch (error) {
      console.error('Failed to update entrant alerts', error);
    }
  };

  const updateAlert = async (alertId: number, action: 'read' | 'dismiss') => {
    try {
      await api.patch(`/competitors/entrant-alerts/${alertId}`, { action });
      if (action === 'dismiss') {
        setEntrantAlerts(prev => prev.filter(item => item.id !== alertId));
      } else {
        setEntrantAlerts(prev => prev.map(item => item.id === alertId
          ? { ...item, read_at: new Date().toISOString() }
          : item));
      }
      await loadCompetitors();
    } catch (error) {
      console.error('Failed to update entrant alert', error);
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

      <div className="mb-6 rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-medium text-slate-200">
              <UserPlus className="h-4 w-4 text-green-400" />
              First-Observed Entrant Alerts
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              New detections after each tracked company's initial baseline; these are observations in Cortellis deal data, not proof of first-ever market activity.
            </p>
          </div>
          <span className="rounded-full bg-green-500/10 px-2.5 py-1 text-xs text-green-300">
            {entrantAlerts.filter(item => !item.read_at).length} unread
          </span>
        </div>
        {entrantAlerts.length === 0 ? (
          <div className="rounded-lg bg-slate-800/40 px-4 py-5 text-center text-sm text-slate-500">
            No post-baseline entrant alerts yet.
          </div>
        ) : (
          <div className="space-y-3">
            {entrantAlerts.slice(0, 20).map(item => (
              <div key={item.id} className={`rounded-lg border p-3 ${item.read_at ? 'border-slate-800 bg-slate-900' : 'border-green-500/20 bg-green-500/5'}`}>
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-sm text-slate-300">{item.content}</p>
                    <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
                      <Link to={`/company/${item.entrant_company_id}`} className="hover:text-blue-400">{item.entrant_company_name}</Link>
                      <span>{item.indication_name}</span>
                      <span>{item.observed_deals} linked deals</span>
                      <span>Evidence IDs {item.evidence_deal_ids.join(', ')}</span>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    {!item.read_at && (
                      <button onClick={() => updateAlert(item.id, 'read')} title="Mark read" className="rounded p-1.5 text-slate-500 hover:bg-slate-800 hover:text-green-400">
                        <Check className="h-4 w-4" />
                      </button>
                    )}
                    <button onClick={() => updateAlert(item.id, 'dismiss')} title="Dismiss" className="rounded p-1.5 text-slate-500 hover:bg-slate-800 hover:text-red-400">
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
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
            {suggestions.map(s => (
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
                  <button
                    onClick={() => toggleEntrantAlerts(comp)}
                    className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs ${
                      comp.entrant_alerts_enabled
                        ? 'bg-green-500/10 text-green-300'
                        : 'bg-slate-800 text-slate-500'
                    }`}
                    title={comp.entrant_baselined_at ? 'Daily entrant monitoring is active' : 'A historical baseline will be established by the next scan'}
                  >
                    <Bell className="h-3.5 w-3.5" />
                    {comp.entrant_alerts_enabled
                      ? (comp.entrant_baselined_at ? 'Monitoring' : 'Baseline pending')
                      : 'Paused'}
                    {comp.unread_entrant_alerts > 0 && ` · ${comp.unread_entrant_alerts}`}
                  </button>
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
              {comp.recent_deals.length > 0 && (
                <div className="border-t border-slate-800 pt-3">
                  <h3 className="text-xs text-slate-500 mb-2">Recent Deals</h3>
                  <div className="space-y-1">
                    {comp.recent_deals.map(deal => (
                      <div key={deal.id} className="flex items-center justify-between text-sm py-1">
                        <span className="text-slate-400 truncate max-w-md">{deal.title}</span>
                        <div className="flex items-center gap-3 flex-shrink-0">
                          <span className="text-slate-500 text-xs">{deal.agreement_type || deal.status}</span>
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

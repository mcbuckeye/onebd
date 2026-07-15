import { useState, useEffect } from 'react';
import { Search, Globe, MapPin } from 'lucide-react';
import { Link } from 'react-router-dom';
import api from '../lib/api';
import { useToast } from '../contexts/ToastContext';

export default function TerritoryPage() {
  const toast = useToast();
  const [searchQuery, setSearchQuery] = useState('');
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [territoryData, setTerritoryData] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (searchQuery.length < 2) { setSuggestions([]); return; }
    const timer = setTimeout(() => {
      api.get(`/search/autocomplete/drugs?q=${encodeURIComponent(searchQuery)}&limit=8`)
        .then(r => setSuggestions(r.data.suggestions || []))
        .catch(() => {});
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const loadTerritory = async (drugId: number, drugName: string) => {
    setSearchQuery(drugName);
    setSuggestions([]);
    setLoading(true);
    try {
      const resp = await api.get(`/territory/${drugId}/map`);
      setTerritoryData(resp.data);
    } catch (e) {
      console.error(e);
      setTerritoryData(null);
      toast.error('Failed to load territory-scope evidence');
    } finally {
      setLoading(false);
    }
  };

  const statusColor = (scopeDirection: string, dealStatus: string) => {
    if (dealStatus?.toLowerCase().includes('terminat')) return 'bg-slate-700 text-slate-400 border-slate-600';
    switch (scopeDirection) {
      case 'included': return 'bg-blue-500/10 text-blue-300 border-blue-500/30';
      case 'excluded': return 'bg-orange-500/10 text-orange-300 border-orange-500/30';
      default: return 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30';
    }
  };

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">Territory Deal Scope</h1>
        <p className="text-sm text-slate-500 mt-1">Review included and excluded territory evidence from related deals</p>
      </div>

      <div className="relative mb-6 max-w-lg">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
        <input
          type="text" value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search for a drug/asset..."
          className="w-full pl-10 pr-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
        />
        {suggestions.length > 0 && (
          <div className="absolute z-20 w-full mt-1 bg-slate-800 border border-slate-700 rounded-lg shadow-xl max-h-48 overflow-y-auto">
            {suggestions.map((s: any) => (
              <button key={s.id} onClick={() => loadTerritory(s.id, s.name)}
                className="w-full text-left px-3 py-2 text-sm text-slate-300 hover:bg-slate-700"
              >
                {s.name}
                {s.phase && <span className="text-xs text-slate-500 ml-2">({s.phase})</span>}
              </button>
            ))}
          </div>
        )}
      </div>

      {loading && <div className="text-center py-16 text-slate-500">Loading territory data...</div>}

      {territoryData && !loading && (
        <>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 mb-4">
            <h2 className="text-lg font-semibold text-slate-200">{territoryData.drug?.name}</h2>
            <div className="flex gap-4 mt-2 text-sm">
              <span className="text-slate-500">Phase: {territoryData.drug?.phase || '—'}</span>
              <span className="text-blue-300">{territoryData.summary?.included_records} included records</span>
              <span className="text-orange-300">{territoryData.summary?.excluded_records} excluded records</span>
              <span className="text-slate-400">{territoryData.summary?.distinct_territories} distinct territories</span>
            </div>
            <p className="mt-3 text-xs leading-5 text-amber-300/80">{territoryData.methodology}</p>
          </div>

          {territoryData.territories?.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {territoryData.territories.map((t: any, i: number) => (
              <div key={`${t.deal_id}:${t.territory}:${i}`} className={`border rounded-lg px-4 py-3 ${statusColor(t.scope_direction, t.deal_status)}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <MapPin className="w-4 h-4" />
                    <span className="font-medium">{t.territory}</span>
                  </div>
                  <span className="text-xs uppercase">{t.scope_type}</span>
                </div>
                <div className="text-xs mt-2 opacity-80 space-y-1">
                  <div>Deal status: {t.deal_status || 'Unknown'}</div>
                  {t.participants?.length > 0 && (
                    <div>Participants: {t.participants.map((p: any) => `${p.name} (${p.role || 'role unknown'})`).join(', ')}</div>
                  )}
                  <div>
                    <Link to={`/deals/${t.deal_id}`} className="hover:underline">{t.deal_title || `Deal ${t.deal_id}`}</Link>
                    {t.deal_date && <span className="ml-2">({t.deal_date})</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>
          ) : (
            <div className="rounded-lg border border-slate-800 bg-slate-900 p-6 text-sm text-slate-400">
              No deal-territory scope records were found for this asset. This does not mean rights are available or unencumbered.
            </div>
          )}
        </>
      )}

      {!territoryData && !loading && (
        <div className="text-center py-16">
          <Globe className="w-16 h-16 text-slate-700 mx-auto mb-4" />
          <p className="text-slate-500">Search for a drug to review territory-scope evidence</p>
        </div>
      )}
    </div>
  );
}

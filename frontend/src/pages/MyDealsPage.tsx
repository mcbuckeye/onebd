import { useState, useEffect } from 'react';
import { Star, Bookmark, Search as SearchIcon, Clock } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import api from '../lib/api';
import EmptyState from '../components/EmptyState';

type WatchlistTab = 'watchlist' | 'saved' | 'history';

export default function MyDealsPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<WatchlistTab>('watchlist');
  const [watchlist, setWatchlist] = useState<any[]>([]);
  const [savedSearches, setSavedSearches] = useState<any[]>([]);
  const [searchHistory, setSearchHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    if (tab === 'watchlist') {
      api.get('/watchlist').then(r => setWatchlist(r.data.watchlist || r.data || []))
        .catch(() => setWatchlist([]))
        .finally(() => setLoading(false));
    } else if (tab === 'saved') {
      api.get('/saved-searches').then(r => setSavedSearches(r.data.searches || r.data || []))
        .catch(() => setSavedSearches([]))
        .finally(() => setLoading(false));
    } else if (tab === 'history') {
      api.get('/search/history').then(r => setSearchHistory(r.data.history || []))
        .catch(() => setSearchHistory([]))
        .finally(() => setLoading(false));
    }
  }, [tab]);

  const tabs: Array<{ id: WatchlistTab; label: string; icon: any }> = [
    { id: 'watchlist', label: 'Watchlist', icon: Star },
    { id: 'saved', label: 'Saved Searches', icon: Bookmark },
    { id: 'history', label: 'Search History', icon: Clock },
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">My Deals</h1>
        <p className="text-sm text-slate-500 mt-1">Your tracked deals, saved searches, and activity</p>
      </div>

      <div className="flex gap-1 mb-6 bg-slate-900 p-1 rounded-lg w-fit">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm transition-colors ${
              tab === id ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Icon className="w-4 h-4" /> {label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map(i => <div key={i} className="h-16 bg-slate-800 rounded-xl animate-pulse" />)}
        </div>
      ) : (
        <>
          {tab === 'watchlist' && (
            watchlist.length === 0 ? (
              <EmptyState
                icon={Star}
                title="No deals in your watchlist"
                description="Start tracking deals from search results to monitor them here"
                action={{ label: 'Search Deals', onClick: () => navigate('/search') }}
              />
            ) : (
              <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-slate-500 bg-slate-900/50">
                      <th className="px-4 py-3">Deal</th>
                      <th className="px-4 py-3">Status</th>
                      <th className="px-4 py-3">Tags</th>
                      <th className="px-4 py-3">Added</th>
                    </tr>
                  </thead>
                  <tbody>
                    {watchlist.map((item: any, i: number) => (
                      <tr key={i} className="border-t border-slate-800/50 hover:bg-slate-800/30">
                        <td className="px-4 py-3 text-slate-200">{item.deal_title || item.title || `Deal #${item.deal_id}`}</td>
                        <td className="px-4 py-3">
                          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-400">
                            {item.status || 'Reviewing'}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-500 text-xs">{(item.tags || []).join(', ') || '—'}</td>
                        <td className="px-4 py-3 text-slate-500 text-xs">{item.added_at || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}

          {tab === 'saved' && (
            savedSearches.length === 0 ? (
              <EmptyState
                icon={Bookmark}
                title="No saved searches"
                description="Save your search filters to quickly access them later"
                action={{ label: 'Create Search', onClick: () => navigate('/search') }}
              />
            ) : (
              <div className="space-y-2">
                {savedSearches.map((s: any, i: number) => (
                  <div key={i} className="bg-slate-900 border border-slate-800 rounded-lg px-4 py-3 flex items-center justify-between">
                    <div>
                      <div className="text-sm text-slate-200">{s.name}</div>
                      <div className="text-xs text-slate-500 mt-0.5">
                        {s.is_alert && <span className="text-yellow-400 mr-2">🔔 Alert active</span>}
                        {s.created_at}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )
          )}

          {tab === 'history' && (
            searchHistory.length === 0 ? (
              <EmptyState
                icon={Clock}
                title="No recent searches"
                description="Your search history will appear here once you start exploring"
                action={{ label: 'Start Searching', onClick: () => navigate('/search') }}
              />
            ) : (
              <div className="space-y-1">
                {searchHistory.map((h: any, i: number) => (
                  <div key={i} className="bg-slate-900 border border-slate-800 rounded-lg px-4 py-2.5 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <SearchIcon className="w-3 h-3 text-slate-600" />
                      <span className="text-sm text-slate-300">{h.query}</span>
                    </div>
                    <div className="flex items-center gap-3 text-xs text-slate-500">
                      <span>{h.result_count} results</span>
                      <span>{h.created_at}</span>
                    </div>
                  </div>
                ))}
              </div>
            )
          )}
        </>
      )}
    </div>
  );
}

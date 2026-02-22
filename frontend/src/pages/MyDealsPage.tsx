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
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    
    const fetchWatchlist = () => {
      api.get('/watchlist')
        .then(r => setWatchlist(Array.isArray(r.data) ? r.data : (r.data?.watchlist || r.data || [])))
        .catch(err => {
          console.error('Watchlist fetch error:', err);
          setWatchlist([]);
        })
        .finally(() => setLoading(false));
    };
    
    const fetchSavedSearches = () => {
      api.get('/saved-searches')
        .then(r => setSavedSearches(Array.isArray(r.data) ? r.data : (r.data?.searches || r.data || [])))
        .catch(err => {
          console.error('Saved searches fetch error:', err);
          setSavedSearches([]);
        })
        .finally(() => setLoading(false));
    };
    
    const fetchSearchHistory = () => {
      api.get('/search/history')
        .then(r => setSearchHistory(Array.isArray(r.data) ? r.data : (r.data?.history || [])))
        .catch(err => {
          console.error('Search history fetch error:', err);
          setSearchHistory([]);
        })
        .finally(() => setLoading(false));
    };
    
    if (tab === 'watchlist') fetchWatchlist();
    else if (tab === 'saved') fetchSavedSearches();
    else if (tab === 'history') fetchSearchHistory();
    
  }, [tab]);

  const tabs: Array<{ id: WatchlistTab; label: string; icon: any }> = [
    { id: 'watchlist', label: 'Watchlist', icon: Star },
    { id: 'saved', label: 'Saved Searches', icon: Bookmark },
    { id: 'history', label: 'Search History', icon: Clock },
  ];

  if (error) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <h3 className="text-red-700 font-medium">Something went wrong</h3>
          <p className="text-red-600 text-sm mt-1">{error}</p>
        </div>
      </div>
    );
  }

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
                        <td className="px-4 py-3">
                          {item.tags && item.tags.length > 0 ? (
                            <div className="flex flex-wrap gap-1">
                              {item.tags.map((tag: string, idx: number) => (
                                <span key={idx} className="text-xs px-2 py-0.5 bg-slate-700 text-slate-300 rounded-full">
                                  {tag}
                                </span>
                              ))}
                            </div>
                          ) : (
                            <span className="text-slate-500 italic">None</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-slate-400">
                          {item.created_at ? new Date(item.created_at).toLocaleDateString() : 'Unknown'}
                        </td>
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
                description="Save your favorite searches to quickly access them later"
              />
            ) : (
              <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-slate-500 bg-slate-900/50">
                      <th className="px-4 py-3">Search Name</th>
                      <th className="px-4 py-3">Query</th>
                      <th className="px-4 py-3">Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {savedSearches.map((search: any, i: number) => (
                      <tr key={i} className="border-t border-slate-800/50 hover:bg-slate-800/30">
                        <td className="px-4 py-3 text-slate-200">{search.name}</td>
                        <td className="px-4 py-3 text-slate-400">{search.query}</td>
                        <td className="px-4 py-3 text-slate-400">
                          {search.created_at ? new Date(search.created_at).toLocaleDateString() : 'Unknown'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}

          {tab === 'history' && (
            searchHistory.length === 0 ? (
              <EmptyState
                icon={Clock}
                title="No search history"
                description="Your recent searches will appear here"
              />
            ) : (
              <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-slate-500 bg-slate-900/50">
                      <th className="px-4 py-3">Query</th>
                      <th className="px-4 py-3">Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {searchHistory.map((item: any, i: number) => (
                      <tr key={i} className="border-t border-slate-800/50 hover:bg-slate-800/30">
                        <td className="px-4 py-3 text-slate-200">{item.query}</td>
                        <td className="px-4 py-3 text-slate-400">
                          {item.created_at ? new Date(item.created_at).toLocaleString() : 'Unknown'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}
        </>
      )}
    </div>
  );
}

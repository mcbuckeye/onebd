import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Network, Search } from 'lucide-react';
import api from '../lib/api';

interface GraphNode {
  id: string;
  name: string;
  val: number; // deal count → node size
  color: string;
  company_type?: string;
}

interface GraphLink {
  source: string;
  target: string;
  value: number; // deal frequency
  deal_count: number;
}

interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

export default function GraphPage() {
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [companySearch, setCompanySearch] = useState('');
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [selectedNode, setSelectedNode] = useState<any>(null);
  const navigate = useNavigate();

  // Company autocomplete
  useEffect(() => {
    if (companySearch.length < 2) { setSuggestions([]); return; }
    const timer = setTimeout(() => {
      api.get(`/search/autocomplete/companies?q=${encodeURIComponent(companySearch)}&limit=8`)
        .then(r => setSuggestions(r.data.suggestions || []))
        .catch(() => {});
    }, 300);
    return () => clearTimeout(timer);
  }, [companySearch]);

  // Load network for company
  const loadCompanyNetwork = async (companyId: number) => {
    setLoading(true);
    try {
      const resp = await api.get(`/graph/partnership-network/${companyId}`);
      const data = resp.data;

      // Transform to graph format
      const nodes: GraphNode[] = (data.nodes || []).map((n: any) => ({
        id: String(n.id),
        name: n.name || n.label,
        val: Math.max(3, Math.sqrt(n.deal_count || n.size || 1) * 3),
        color: n.id === companyId ? '#3b82f6' : '#6366f1',
        company_type: n.company_type,
      }));

      const links: GraphLink[] = (data.links || data.edges || []).map((e: any) => ({
        source: String(e.source),
        target: String(e.target),
        value: e.deal_count || e.weight || 1,
        deal_count: e.deal_count || e.weight || 1,
      }));

      setGraphData({ nodes, links });
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  // Load industry-wide network
  const loadIndustryNetwork = async () => {
    setLoading(true);
    try {
      const resp = await api.get('/graph/industry-network?limit=50');
      const data = resp.data;

      const nodes: GraphNode[] = (data.nodes || []).map((n: any) => ({
        id: String(n.id),
        name: n.name || n.label,
        val: Math.max(3, Math.sqrt(n.deal_count || n.size || 1) * 2),
        color: '#6366f1',
        company_type: n.company_type,
      }));

      const links: GraphLink[] = (data.links || data.edges || []).map((e: any) => ({
        source: String(e.source),
        target: String(e.target),
        value: e.deal_count || e.weight || 1,
        deal_count: e.deal_count || e.weight || 1,
      }));

      setGraphData({ nodes, links });
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Partnership Network</h1>
          <p className="text-sm text-slate-500 mt-1">Explore deal relationships between companies</p>
        </div>
        <button
          onClick={loadIndustryNetwork}
          className="px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-300 hover:bg-slate-700"
        >
          Industry Overview
        </button>
      </div>

      {/* Company search */}
      <div className="relative mb-6 max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
        <input
          type="text"
          value={companySearch}
          onChange={(e) => setCompanySearch(e.target.value)}
          placeholder="Search company to view network..."
          className="w-full pl-10 pr-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
        />
        {suggestions.length > 0 && (
          <div className="absolute z-20 w-full mt-1 bg-slate-800 border border-slate-700 rounded-lg shadow-xl max-h-48 overflow-y-auto">
            {suggestions.map((s: any) => (
              <button
                key={s.id}
                onClick={() => {
                  setCompanySearch(s.name);
                  setSuggestions([]);
                  loadCompanyNetwork(s.id);
                }}
                className="w-full text-left px-3 py-2 text-sm text-slate-300 hover:bg-slate-700"
              >
                {s.name}
                {s.company_type && <span className="text-xs text-slate-500 ml-2">({s.company_type})</span>}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Graph area */}
        <div className="lg:col-span-3 bg-slate-900 border border-slate-800 rounded-xl overflow-hidden" style={{ minHeight: 500 }}>
          {loading ? (
            <div className="flex items-center justify-center h-96 text-slate-500">Loading network...</div>
          ) : !graphData ? (
            <div className="flex flex-col items-center justify-center h-96 text-slate-500">
              <Network className="w-16 h-16 mb-4 opacity-30" />
              <p className="text-sm">Search for a company or click "Industry Overview"</p>
            </div>
          ) : (
            <div className="relative h-[500px]">
              {/* Simple node list visualization (force-graph loaded dynamically) */}
              <div className="p-4 overflow-y-auto h-full">
                <div className="text-xs text-slate-500 mb-3">
                  {graphData.nodes.length} companies, {graphData.links.length} connections
                </div>
                <div className="space-y-1">
                  {graphData.nodes
                    .sort((a, b) => b.val - a.val)
                    .map(node => (
                      <button
                        key={node.id}
                        onClick={() => {
                          setSelectedNode(node);
                          navigate(`/company/${node.id}`);
                        }}
                        className={`w-full text-left flex items-center gap-3 px-3 py-2 rounded-lg text-sm hover:bg-slate-800 ${
                          selectedNode?.id === node.id ? 'bg-slate-800' : ''
                        }`}
                      >
                        <div
                          className="rounded-full flex-shrink-0"
                          style={{ width: node.val * 2, height: node.val * 2, backgroundColor: node.color, minWidth: 8, minHeight: 8 }}
                        />
                        <span className="text-slate-300 truncate">{node.name}</span>
                        <span className="text-xs text-slate-500 ml-auto">{node.company_type}</span>
                      </button>
                    ))}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Side panel */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <h3 className="text-sm font-medium text-slate-400 mb-3">Network Details</h3>
          {graphData ? (
            <div className="space-y-3 text-sm">
              <div>
                <span className="text-slate-500">Companies:</span>
                <span className="text-slate-300 ml-2">{graphData.nodes.length}</span>
              </div>
              <div>
                <span className="text-slate-500">Connections:</span>
                <span className="text-slate-300 ml-2">{graphData.links.length}</span>
              </div>
              <div>
                <span className="text-slate-500">Top connections:</span>
                <div className="mt-2 space-y-1">
                  {graphData.links
                    .sort((a, b) => b.deal_count - a.deal_count)
                    .slice(0, 10)
                    .map((link, i) => {
                      const src = graphData.nodes.find(n => n.id === (typeof link.source === 'string' ? link.source : (link.source as any).id));
                      const tgt = graphData.nodes.find(n => n.id === (typeof link.target === 'string' ? link.target : (link.target as any).id));
                      return (
                        <div key={i} className="text-xs text-slate-400">
                          {src?.name} ↔ {tgt?.name} ({link.deal_count})
                        </div>
                      );
                    })}
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-slate-500">Select a company to see network details</p>
          )}
        </div>
      </div>
    </div>
  );
}

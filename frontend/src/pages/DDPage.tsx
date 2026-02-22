import { useState, useEffect } from 'react';
import { Search, AlertTriangle, CheckCircle, Info, Building2, Pill, Users, DollarSign, Shield } from 'lucide-react';
import api from '../lib/api';

function formatValue(v: number | null): string {
  if (v === null || v === undefined) return 'N/A';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
}

const SECTION_ICONS: Record<string, any> = {
  company_overview: Building2,
  deal_history: Info,
  drug_portfolio: Pill,
  partnerships: Users,
  financials: DollarSign,
  risk_assessment: Shield,
};

export default function DDPage() {
  const [searchQuery, setSearchQuery] = useState('');
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [ddPackage, setDdPackage] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['company_overview', 'risk_assessment']));

  // Autocomplete
  useEffect(() => {
    if (searchQuery.length < 2) { setSuggestions([]); return; }
    const timer = setTimeout(() => {
      api.get(`/search/autocomplete/companies?q=${encodeURIComponent(searchQuery)}&limit=8`)
        .then(r => setSuggestions(r.data.suggestions || []))
        .catch(() => {});
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const generateDD = async (companyId: number, companyName: string) => {
    setSearchQuery(companyName);
    setSuggestions([]);
    setLoading(true);
    try {
      const resp = await api.post('/dd/generate', { company_id: companyId });
      setDdPackage(resp.data);
      setExpandedSections(new Set(['company_overview', 'risk_assessment']));
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const toggleSection = (type: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type); else next.add(type);
      return next;
    });
  };

  const expandAll = () => setExpandedSections(new Set(ddPackage?.sections?.map((s: any) => s.type) || []));
  const collapseAll = () => setExpandedSections(new Set());

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">Due Diligence</h1>
        <p className="text-sm text-slate-500 mt-1">Generate comprehensive DD packages for acquisition targets</p>
      </div>

      {/* Company search */}
      <div className="relative mb-6 max-w-lg">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
        <input
          type="text" value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search for a company to analyze..."
          className="w-full pl-10 pr-4 py-3 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
        />
        {suggestions.length > 0 && (
          <div className="absolute z-20 w-full mt-1 bg-slate-800 border border-slate-700 rounded-lg shadow-xl max-h-48 overflow-y-auto">
            {suggestions.map((s: any) => (
              <button key={s.id} onClick={() => generateDD(s.id, s.name)}
                className="w-full text-left px-3 py-2 text-sm text-slate-300 hover:bg-slate-700"
              >
                {s.name}
                {s.company_type && <span className="text-xs text-slate-500 ml-2">({s.company_type})</span>}
              </button>
            ))}
          </div>
        )}
      </div>

      {loading && (
        <div className="text-center py-16">
          <div className="animate-spin w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full mx-auto mb-4" />
          <p className="text-slate-400">Generating DD package...</p>
        </div>
      )}

      {ddPackage && !loading && (
        <>
          {/* Header */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 mb-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-xl font-bold text-slate-100">{ddPackage.company?.name}</h2>
                <div className="flex gap-3 mt-1 text-sm text-slate-500">
                  <span>{ddPackage.company?.company_type}</span>
                  {ddPackage.company?.ticker && <span>({ddPackage.company.ticker})</span>}
                  <span>{ddPackage.metadata?.total_deals_analyzed} deals analyzed</span>
                  <span>{ddPackage.metadata?.financial_disclosure_rate} disclosed</span>
                </div>
              </div>
              <div className="flex gap-2">
                <button onClick={expandAll} className="px-3 py-1.5 bg-slate-800 rounded text-xs text-slate-400 hover:text-slate-200">Expand All</button>
                <button onClick={collapseAll} className="px-3 py-1.5 bg-slate-800 rounded text-xs text-slate-400 hover:text-slate-200">Collapse All</button>
              </div>
            </div>
          </div>

          {/* Risk flags banner */}
          {ddPackage.risk_flags?.length > 0 && (
            <div className="mb-4 space-y-2">
              {ddPackage.risk_flags.filter((f: any) => f.severity === 'high').map((f: any, i: number) => (
                <div key={i} className="flex items-center gap-2 px-4 py-2.5 bg-red-500/10 border border-red-500/30 rounded-lg">
                  <AlertTriangle className="w-4 h-4 text-red-400 flex-shrink-0" />
                  <span className="text-sm text-red-300">{f.flag}</span>
                </div>
              ))}
              {ddPackage.risk_flags.filter((f: any) => f.severity === 'medium').map((f: any, i: number) => (
                <div key={i} className="flex items-center gap-2 px-4 py-2.5 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
                  <Info className="w-4 h-4 text-yellow-400 flex-shrink-0" />
                  <span className="text-sm text-yellow-300">{f.flag}</span>
                </div>
              ))}
              {ddPackage.risk_flags.filter((f: any) => f.severity === 'low').map((f: any, i: number) => (
                <div key={i} className="flex items-center gap-2 px-4 py-2.5 bg-green-500/10 border border-green-500/30 rounded-lg">
                  <CheckCircle className="w-4 h-4 text-green-400 flex-shrink-0" />
                  <span className="text-sm text-green-300">{f.flag}</span>
                </div>
              ))}
            </div>
          )}

          {/* Sections */}
          <div className="space-y-2">
            {ddPackage.sections?.map((section: any) => {
              const Icon = SECTION_ICONS[section.type] || Info;
              const isExpanded = expandedSections.has(section.type);

              return (
                <div key={section.type} className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
                  <button
                    onClick={() => toggleSection(section.type)}
                    className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-slate-800/50 transition-colors"
                  >
                    <Icon className="w-5 h-5 text-blue-400 flex-shrink-0" />
                    <span className="font-medium text-slate-200">{section.title}</span>
                    <span className="ml-auto text-xs text-slate-500">{isExpanded ? '▼' : '▶'}</span>
                  </button>

                  {isExpanded && (
                    <div className="px-5 pb-4 border-t border-slate-800">
                      {section.type === 'deal_history' && Array.isArray(section.content) ? (
                        <table className="w-full text-sm mt-3">
                          <thead>
                            <tr className="text-left text-slate-500">
                              <th className="pb-2">Deal</th>
                              <th className="pb-2">Counterparty</th>
                              <th className="pb-2">Type</th>
                              <th className="pb-2">Value</th>
                              <th className="pb-2">Status</th>
                              <th className="pb-2">Date</th>
                            </tr>
                          </thead>
                          <tbody>
                            {section.content.slice(0, 25).map((d: any) => (
                              <tr key={d.id} className="border-t border-slate-800/50">
                                <td className="py-2 text-slate-300 max-w-xs truncate">{d.title}</td>
                                <td className="py-2 text-slate-400">{d.counterparty || '—'}</td>
                                <td className="py-2 text-slate-500 text-xs">{d.type || '—'}</td>
                                <td className="py-2 text-slate-300">{formatValue(d.value)}</td>
                                <td className="py-2">
                                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                                    d.status === 'Terminated' ? 'bg-red-500/10 text-red-400' :
                                    d.status === 'Active' ? 'bg-green-500/10 text-green-400' :
                                    'bg-slate-700 text-slate-400'
                                  }`}>{d.status || '—'}</span>
                                </td>
                                <td className="py-2 text-slate-500 text-xs">{d.date || '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : section.type === 'drug_portfolio' && Array.isArray(section.content) ? (
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mt-3">
                          {section.content.map((d: any) => (
                            <div key={d.id} className="flex items-center justify-between px-3 py-2 bg-slate-800 rounded-lg">
                              <span className="text-sm text-slate-300 truncate">{d.name}</span>
                              <span className="text-xs px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-400">{d.phase}</span>
                            </div>
                          ))}
                        </div>
                      ) : section.type === 'partnerships' && Array.isArray(section.content) ? (
                        <div className="space-y-1 mt-3">
                          {section.content.map((p: any) => (
                            <div key={p.id} className="flex items-center justify-between text-sm">
                              <span className="text-slate-300">{p.name}</span>
                              <span className="text-slate-500">{p.deal_count} deals</span>
                            </div>
                          ))}
                        </div>
                      ) : section.type === 'financials' && section.content ? (
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
                          {[
                            { label: 'Total Deal Value', value: formatValue(section.content.total_deal_value) },
                            { label: 'Avg Deal Value', value: formatValue(section.content.avg_deal_value) },
                            { label: 'Largest Deal', value: formatValue(section.content.largest_deal) },
                            { label: 'Deals w/ Financials', value: section.content.deal_count_with_financials?.toString() || '0' },
                          ].map(kpi => (
                            <div key={kpi.label} className="bg-slate-800 rounded-lg p-3">
                              <div className="text-xs text-slate-500">{kpi.label}</div>
                              <div className="text-lg font-bold text-slate-200 mt-1">{kpi.value}</div>
                            </div>
                          ))}
                        </div>
                      ) : section.type === 'company_overview' && section.content ? (
                        <div className="grid grid-cols-2 gap-3 mt-3 text-sm">
                          {Object.entries(section.content).filter(([k]) => k !== 'id').map(([key, val]) => (
                            <div key={key}>
                              <span className="text-slate-500">{key.replace(/_/g, ' ')}:</span>
                              <span className="text-slate-300 ml-2">{String(val || '—')}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="mt-3 text-sm text-slate-500">
                          {Array.isArray(section.content) && section.content.length === 0 ? 'No data available' :
                           section.content ? <pre className="text-xs">{JSON.stringify(section.content, null, 2)}</pre> : 'No data available'}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}

      {!ddPackage && !loading && (
        <div className="text-center py-16">
          <Shield className="w-16 h-16 text-slate-700 mx-auto mb-4" />
          <p className="text-slate-500">Search for a company to generate a DD package</p>
          <p className="text-sm text-slate-600 mt-1">Combines deal history, drug portfolio, partnerships, financials, and risk assessment</p>
        </div>
      )}
    </div>
  );
}

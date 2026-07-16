import { useState, useEffect, useRef } from 'react';
import { Search, AlertTriangle, CheckCircle, Info, Building2, Pill, Users, DollarSign, Shield, FileDown, FileText, FileCheck2, MapPinned, Scale } from 'lucide-react';
import api from '../lib/api';
import { Link } from 'react-router-dom';

function formatValue(v: number | null): string {
  if (v === null || v === undefined) return 'N/A';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
}

function formatReportedAmount(v: number | null, currency?: string | null, unit?: string | null): string {
  if (v === null || v === undefined) return '—';
  const symbol = currency === 'USD' ? '$' : currency ? `${currency} ` : '';
  const suffix = unit === 'Million' ? 'M' : unit === 'B' ? 'B' : unit ? ` ${unit}` : '';
  return `${symbol}${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}${suffix}`;
}

function shortDate(value?: string | null): string {
  return value ? value.slice(0, 10) : '—';
}

const SECTION_ICONS: Record<string, any> = {
  company_overview: Building2,
  deal_history: Info,
  drug_portfolio: Pill,
  partnerships: Users,
  financials: DollarSign,
  sec_filings: FileText,
  contracts: FileCheck2,
  territory_rights: MapPinned,
  comparable_transactions: Scale,
  risk_assessment: Shield,
};

export default function DDPage() {
  const [searchQuery, setSearchQuery] = useState('');
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [ddPackage, setDdPackage] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['company_overview', 'risk_assessment']));
  const selectedAutocompleteValue = useRef<string | null>(null);

  // Autocomplete
  useEffect(() => {
    if (selectedAutocompleteValue.current === searchQuery) {
      selectedAutocompleteValue.current = null;
      setSuggestions([]);
      return;
    }
    selectedAutocompleteValue.current = null;
    if (searchQuery.length < 2) { setSuggestions([]); return; }
    let active = true;
    const timer = setTimeout(() => {
      api.get(`/search/autocomplete/companies?q=${encodeURIComponent(searchQuery)}&limit=8`)
        .then(r => { if (active) setSuggestions(r.data.suggestions || []); })
        .catch(() => {});
    }, 300);
    return () => { active = false; clearTimeout(timer); };
  }, [searchQuery]);

  const generateDD = async (companyId: number, companyName: string) => {
    selectedAutocompleteValue.current = companyName;
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

  const exportPdf = async () => {
    if (!ddPackage) return;
    try {
      const res = await api.post('/export/dd/pdf', {
        company_name: ddPackage.company?.name || 'Unknown',
        dd_package: ddPackage,
      }, { responseType: 'blob' });
      
      const blob = new Blob([res.data]);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `dd-${(ddPackage.company?.name || 'report').toLowerCase().replace(/\s+/g, '-')}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (e) {
      console.error('PDF export failed:', e);
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
                <button onClick={exportPdf} disabled={!ddPackage}
                  className="px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 hover:bg-slate-700 flex items-center gap-1 disabled:opacity-50"
                >
                  <FileDown className="w-3 h-3" /> Export PDF
                </button>
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
                      {(section.source || section.methodology) && (
                        <div className="mt-3 rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-xs text-slate-500">
                          {section.source && <div><span className="font-medium text-slate-400">Source:</span> {section.source}</div>}
                          {section.methodology && <div className="mt-1">{section.methodology}</div>}
                        </div>
                      )}
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
                                <td className="py-2 text-slate-300">{formatReportedAmount(d.value, d.currency, d.unit)}</td>
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
                            { label: 'Total Known Value (USD)', value: formatValue(section.content.total_deal_value) },
                            { label: 'Avg Known Value (USD)', value: formatValue(section.content.avg_deal_value) },
                            { label: 'Largest Known Value (USD)', value: formatValue(section.content.largest_deal) },
                            { label: 'Deals w/ Financials', value: section.content.deal_count_with_financials?.toString() || '0' },
                          ].map(kpi => (
                            <div key={kpi.label} className="bg-slate-800 rounded-lg p-3">
                              <div className="text-xs text-slate-500">{kpi.label}</div>
                              <div className="text-lg font-bold text-slate-200 mt-1">{kpi.value}</div>
                            </div>
                          ))}
                        </div>
                      ) : section.type === 'sec_filings' && Array.isArray(section.content) ? (
                        section.content.length > 0 ? (
                          <table className="w-full text-sm mt-3">
                            <thead><tr className="text-left text-slate-500"><th className="pb-2">Form</th><th className="pb-2">Filed</th><th className="pb-2">Filing</th><th className="pb-2">Parsed</th></tr></thead>
                            <tbody>{section.content.map((filing: any) => (
                              <tr key={filing.id} className="border-t border-slate-800/50">
                                <td className="py-2 text-blue-400">{filing.doc_type || '—'}</td>
                                <td className="py-2 text-xs text-slate-500 whitespace-nowrap">{shortDate(filing.filing_date)}</td>
                                <td className="py-2 pr-3"><a href={filing.source_url} target="_blank" rel="noreferrer" className="text-slate-300 hover:text-blue-400">{filing.title || filing.accession_no || `Filing ${filing.id}`}</a></td>
                                <td className="py-2 text-xs text-slate-500">{filing.parse_ok ? `${filing.chunk_count} chunks` : 'No parsed text'}</td>
                              </tr>
                            ))}</tbody>
                          </table>
                        ) : <div className="mt-3 text-sm text-slate-500">{section.status === 'unmapped' ? 'No source-confirmed EDGAR company identity is available.' : 'No SEC filings are available.'}</div>
                      ) : section.type === 'contracts' && Array.isArray(section.content) ? (
                        section.content.length > 0 ? (
                          <div className="space-y-2 mt-3">{section.content.map((contract: any) => (
                            <div key={contract.contract_id} className="rounded-lg bg-slate-800/70 p-3">
                              <div className="flex items-start justify-between gap-3">
                                <div><Link to={`/deals/${contract.deal_id}`} className="text-sm text-slate-200 hover:text-blue-400">{contract.deal_title}</Link><div className="mt-1 text-xs text-slate-500">{contract.contract_types || 'Contract'} · {shortDate(contract.date_contract || contract.date_filing)} · {contract.word_count.toLocaleString()} words</div></div>
                                <div className="flex gap-1 text-[11px]"><span className={`rounded px-1.5 py-0.5 ${contract.has_text ? 'bg-green-500/10 text-green-400' : 'bg-slate-700 text-slate-500'}`}>{contract.has_text ? 'Text' : 'Metadata only'}</span>{contract.is_redacted && <span className="rounded bg-yellow-500/10 px-1.5 py-0.5 text-yellow-400">Redacted</span>}</div>
                              </div>
                              {contract.key_financial_clauses?.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{contract.key_financial_clauses.map((clause: any) => <span key={clause.id} title={clause.source_excerpt} className={`rounded px-2 py-1 text-[11px] ${clause.review_status === 'accepted' ? 'bg-green-500/10 text-green-300' : 'bg-blue-500/10 text-blue-300'}`}>{clause.clause_type.replace(/_/g, ' ')} · {clause.review_status}</span>)}</div>}
                            </div>
                          ))}</div>
                        ) : <div className="mt-3 text-sm text-slate-500">No contract records are available.</div>
                      ) : section.type === 'territory_rights' && Array.isArray(section.content) ? (
                        section.content.length > 0 ? (
                          <table className="w-full text-sm mt-3"><thead><tr className="text-left text-slate-500"><th className="pb-2">Territory</th><th className="pb-2">Scope</th><th className="pb-2">Company role</th><th className="pb-2">Deal / assets</th><th className="pb-2">Date</th></tr></thead><tbody>{section.content.map((right: any, index: number) => (
                            <tr key={`${right.deal_id}-${right.territory_id}-${right.scope_type}-${index}`} className="border-t border-slate-800/50"><td className="py-2 text-slate-300">{right.territory}</td><td className="py-2"><span className={`rounded px-2 py-0.5 text-xs ${String(right.scope_type).toLowerCase().includes('exclu') ? 'bg-red-500/10 text-red-400' : 'bg-green-500/10 text-green-400'}`}>{right.scope_type}</span></td><td className="py-2 text-slate-400">{right.company_role}</td><td className="py-2 pr-3"><Link to={`/deals/${right.deal_id}`} className="text-slate-300 hover:text-blue-400">{right.deal_title}</Link>{right.assets?.length > 0 && <div className="text-xs text-slate-500">{right.assets.join(', ')}</div>}</td><td className="py-2 text-xs text-slate-500 whitespace-nowrap">{shortDate(right.date_start)}</td></tr>
                          ))}</tbody></table>
                        ) : <div className="mt-3 text-sm text-slate-500">No deal territory scope is available.</div>
                      ) : section.type === 'comparable_transactions' && Array.isArray(section.content) ? (
                        section.content.length > 0 ? (
                          <table className="w-full text-sm mt-3"><thead><tr className="text-left text-slate-500"><th className="pb-2">Comparable deal</th><th className="pb-2">Match</th><th className="pb-2">Phase</th><th className="pb-2">Value</th><th className="pb-2">Date</th></tr></thead><tbody>{section.content.map((comp: any) => (
                            <tr key={comp.id} className="border-t border-slate-800/50"><td className="py-2 pr-3"><Link to={`/deals/${comp.id}`} className="text-slate-300 hover:text-blue-400">{comp.title}</Link><div className="text-xs text-slate-500">{[comp.principal, comp.partner].filter(Boolean).join(' → ')}</div></td><td className="py-2"><div className="text-xs font-medium text-blue-400">{comp.similarity_score}/9</div><div className="text-[11px] text-slate-500">{comp.match_reasons.join(', ')}</div></td><td className="py-2 text-slate-400">{comp.phase_at_signing || '—'}</td><td className="py-2 text-slate-300">{formatReportedAmount(comp.total_value, comp.currency, comp.unit)}</td><td className="py-2 text-xs text-slate-500 whitespace-nowrap">{shortDate(comp.date_start)}</td></tr>
                          ))}</tbody></table>
                        ) : <div className="mt-3 text-sm text-slate-500">No comparable transactions were found.</div>
                      ) : section.type === 'risk_assessment' && Array.isArray(section.content) ? (
                        section.content.length > 0 ? (
                          <div className="space-y-2 mt-3">
                            {section.content.map((flag: any, index: number) => (
                              <div key={`${flag.category || 'risk'}-${index}`} className={`rounded-lg border px-3 py-2 ${
                                flag.severity === 'high' ? 'border-red-500/30 bg-red-500/10 text-red-300' :
                                flag.severity === 'medium' ? 'border-yellow-500/30 bg-yellow-500/10 text-yellow-300' :
                                'border-slate-700 bg-slate-800 text-slate-300'
                              }`}>
                                <div className="text-sm">{flag.flag}</div>
                                {flag.category && <div className="text-[11px] opacity-70 mt-1">{String(flag.category).replace(/_/g, ' ')}</div>}
                              </div>
                            ))}
                          </div>
                        ) : <div className="mt-3 text-sm text-slate-500">No risk flags were identified from the available records. This is not evidence that no risks exist.</div>
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
          <p className="text-sm text-slate-600 mt-1">Combines deals, assets, filings, contracts, territories, comparables, financials, and risks</p>
        </div>
      )}
    </div>
  );
}

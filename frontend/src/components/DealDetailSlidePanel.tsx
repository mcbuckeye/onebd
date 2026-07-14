import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { X, Building2, DollarSign, Calendar, FileText, MapPin, Tag, TrendingUp } from 'lucide-react';
import api from '../lib/api';
import { DealDetail } from '../types';
import EvidenceTimelineList from './EvidenceTimelineList';

interface DealDetailSlidePanelProps {
  dealId: number | null;
  onClose: () => void;
}

function stripXml(text: string): string {
  if (!text) return '';
  return text
    .replace(/<para>\s*/g, '')
    .replace(/<\/para>/g, '\n')
    .replace(/<ulink[^>]*>/g, '')
    .replace(/<\/ulink>/g, '')
    .replace(/\[\s*\d+\s*\]/g, '') // remove [4343749] reference numbers
    .replace(/\n{3,}/g, '\n\n')    // collapse multiple newlines
    .trim();
}

function formatValue(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
}

function PhaseBadge({ phase }: { phase?: string }) {
  if (!phase) return <span className="text-slate-500 text-xs">—</span>;
  
  const colors: Record<string, string> = {
    'Preclinical': 'bg-slate-500/10 text-slate-400 border-slate-500/30',
    'Phase I': 'bg-blue-500/10 text-blue-400 border-blue-500/30',
    'Phase II': 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30',
    'Phase III': 'bg-purple-500/10 text-purple-400 border-purple-500/30',
    'Approved': 'bg-green-500/10 text-green-400 border-green-500/30',
  };

  const colorClass = colors[phase] || 'bg-slate-500/10 text-slate-400 border-slate-500/30';

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs border ${colorClass}`}>
      {phase}
    </span>
  );
}

function StatusBadge({ status }: { status?: string }) {
  if (!status) return null;

  const colors: Record<string, string> = {
    'Active': 'bg-green-500/10 text-green-400 border-green-500/30',
    'Completed': 'bg-blue-500/10 text-blue-400 border-blue-500/30',
    'Terminated': 'bg-red-500/10 text-red-400 border-red-500/30',
    'Unknown': 'bg-slate-500/10 text-slate-400 border-slate-500/30',
  };

  const colorClass = colors[status] || 'bg-slate-500/10 text-slate-400 border-slate-500/30';

  return (
    <span className={`inline-flex items-center px-2 py-1 rounded text-xs font-medium border ${colorClass}`}>
      {status}
    </span>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="h-8 bg-slate-800 rounded w-3/4" />
      <div className="space-y-2">
        <div className="h-4 bg-slate-800 rounded w-full" />
        <div className="h-4 bg-slate-800 rounded w-5/6" />
      </div>
      <div className="space-y-2">
        <div className="h-4 bg-slate-800 rounded w-full" />
        <div className="h-4 bg-slate-800 rounded w-4/6" />
      </div>
    </div>
  );
}

export default function DealDetailSlidePanel({ dealId, onClose }: DealDetailSlidePanelProps) {
  const [deal, setDeal] = useState<DealDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!dealId) {
      setDeal(null);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);

    api
      .get(`/deal/${dealId}`)
      .then((res) => {
        setDeal(res.data);
      })
      .catch((err) => {
        console.error(err);
        setError('Failed to load deal details');
      })
      .finally(() => setLoading(false));
  }, [dealId]);

  if (!dealId) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm z-40 transition-opacity"
        onClick={onClose}
      />

      {/* Slide-in panel */}
      <div
        className={`fixed top-0 right-0 h-full w-[500px] max-w-[90vw] bg-slate-900 border-l border-slate-800 shadow-2xl z-50 overflow-y-auto transform transition-transform duration-300 ${
          dealId ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        {/* Header with close button */}
        <div className="sticky top-0 z-10 bg-slate-900 border-b border-slate-800 p-4 flex items-start justify-between">
          <div className="flex-1 pr-4">
            {loading ? (
              <div className="h-6 bg-slate-800 rounded w-3/4 animate-pulse" />
            ) : (
              <h2 className="text-lg font-semibold text-slate-100 leading-tight">
                {deal?.title || 'Loading...'}
              </h2>
            )}
          </div>
          <button
            onClick={onClose}
            className="flex-shrink-0 p-1 hover:bg-slate-800 rounded transition-colors"
            aria-label="Close"
          >
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-6">
          {loading ? (
            <LoadingSkeleton />
          ) : error ? (
            <div className="text-red-400 text-sm bg-red-500/10 border border-red-500/30 rounded p-3">
              {error}
            </div>
          ) : deal ? (
            <>
              {/* Status & Date Range */}
              <div className="flex items-center gap-3 flex-wrap">
                <StatusBadge status={deal.status} />
                {deal.date_start && (
                  <div className="flex items-center gap-1 text-xs text-slate-400">
                    <Calendar className="w-3.5 h-3.5" />
                    {deal.date_start}
                    {deal.date_end && ` – ${deal.date_end}`}
                  </div>
                )}
              </div>

              {/* Deal Type & Therapy Area */}
              {(deal.deal_type || deal.therapy_area) && (
                <div className="flex flex-wrap gap-2">
                  {deal.deal_type && (
                    <span className="px-2 py-1 bg-slate-800 text-slate-300 rounded text-xs">
                      {deal.deal_type}
                    </span>
                  )}
                  {deal.therapy_area && (
                    <span className="px-2 py-1 bg-blue-500/10 text-blue-400 border border-blue-500/30 rounded text-xs">
                      {deal.therapy_area}
                    </span>
                  )}
                </div>
              )}

              {/* Companies */}
              {deal.companies.length > 0 && (
                <section>
                  <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2 mb-3">
                    <Building2 className="w-4 h-4" />
                    Companies
                  </h3>
                  <div className="space-y-2">
                    {deal.companies.map((company, idx) => (
                      <Link
                        key={idx}
                        to={`/company/${company.id}`}
                        className="block p-3 bg-slate-800/50 hover:bg-slate-800 border border-slate-700 rounded-lg transition-colors"
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-slate-200 font-medium hover:text-blue-400">
                            {company.name}
                          </span>
                          <span className="text-xs text-slate-500 uppercase">{company.role}</span>
                        </div>
                        {(company.company_type || company.hq_location) && (
                          <div className="text-xs text-slate-500 mt-1">
                            {[company.company_type, company.hq_location].filter(Boolean).join(' • ')}
                          </div>
                        )}
                      </Link>
                    ))}
                  </div>
                </section>
              )}

              {/* Financials */}
              {deal.finance && (
                <section>
                  <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2 mb-3">
                    <DollarSign className="w-4 h-4" />
                    Financials
                  </h3>
                  <div className="grid grid-cols-2 gap-3">
                    {deal.finance.total_paid_amount !== undefined && (
                      <div className="p-3 bg-slate-800/50 border border-slate-700 rounded-lg">
                        <div className="text-xs text-slate-500 mb-1">Paid Amount</div>
                        <div className="text-base font-semibold text-slate-200">
                          {formatValue(deal.finance.total_paid_amount)}
                        </div>
                        {deal.finance.total_paid_disclosure_status && (
                          <div className="text-xs text-slate-500 mt-0.5">
                            {deal.finance.total_paid_disclosure_status}
                          </div>
                        )}
                      </div>
                    )}
                    {deal.finance.total_projected_current_amount !== undefined && (
                      <div className="p-3 bg-slate-800/50 border border-slate-700 rounded-lg">
                        <div className="text-xs text-slate-500 mb-1">Projected (Current)</div>
                        <div className="text-base font-semibold text-slate-200">
                          {formatValue(deal.finance.total_projected_current_amount)}
                        </div>
                      </div>
                    )}
                    {deal.finance.total_projected_signing_amount !== undefined && (
                      <div className="p-3 bg-slate-800/50 border border-slate-700 rounded-lg">
                        <div className="text-xs text-slate-500 mb-1">Projected (Signing)</div>
                        <div className="text-base font-semibold text-slate-200">
                          {formatValue(deal.finance.total_projected_signing_amount)}
                        </div>
                      </div>
                    )}
                  </div>
                </section>
              )}

              {/* Drugs */}
              {deal.drugs.length > 0 && (
                <section>
                  <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2 mb-3">
                    <TrendingUp className="w-4 h-4" />
                    Drugs
                  </h3>
                  <div className="space-y-2">
                    {deal.drugs.map((drug) => (
                      <Link
                        key={drug.id}
                        to={`/drug/${drug.id}`}
                        className="flex items-center justify-between p-3 bg-slate-800/50 hover:bg-slate-800 border border-slate-700 rounded-lg transition-colors"
                      >
                        <span className="text-sm text-slate-200 hover:text-blue-400 font-medium">
                          {drug.name}
                        </span>
                        <PhaseBadge phase={drug.phase_highest_now} />
                      </Link>
                    ))}
                  </div>
                </section>
              )}

              {/* Indications */}
              {deal.indications.length > 0 && (
                <section>
                  <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2 mb-3">
                    <Tag className="w-4 h-4" />
                    Indications
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {deal.indications.map((indication) => (
                      <span
                        key={indication.id}
                        className="px-2 py-1 bg-purple-500/10 text-purple-400 border border-purple-500/30 rounded text-xs"
                      >
                        {indication.name}
                      </span>
                    ))}
                  </div>
                </section>
              )}

              {/* Technologies */}
              {deal.technologies.length > 0 && (
                <section>
                  <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2 mb-3">
                    <Tag className="w-4 h-4" />
                    Technologies
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {deal.technologies.map((tech) => (
                      <span
                        key={tech.id}
                        className="px-2 py-1 bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 rounded text-xs"
                      >
                        {tech.name}
                      </span>
                    ))}
                  </div>
                </section>
              )}

              {/* Territories */}
              {(deal.territories_included.length > 0 || deal.territories_excluded.length > 0) && (
                <section>
                  <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2 mb-3">
                    <MapPin className="w-4 h-4" />
                    Territories
                  </h3>
                  {deal.territories_included.length > 0 && (
                    <div className="mb-3">
                      <div className="text-xs text-slate-500 mb-2">Included</div>
                      <div className="flex flex-wrap gap-1.5">
                        {deal.territories_included.map((territory, idx) => (
                          <span
                            key={idx}
                            className="px-2 py-0.5 bg-green-500/10 text-green-400 border border-green-500/30 rounded text-xs"
                          >
                            {territory}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {deal.territories_excluded.length > 0 && (
                    <div>
                      <div className="text-xs text-slate-500 mb-2">Excluded</div>
                      <div className="flex flex-wrap gap-1.5">
                        {deal.territories_excluded.map((territory, idx) => (
                          <span
                            key={idx}
                            className="px-2 py-0.5 bg-red-500/10 text-red-400 border border-red-500/30 rounded text-xs"
                          >
                            {territory}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </section>
              )}

              {/* Source-labeled timeline */}
              {(deal.evidence_timeline?.length ?? 0) > 0 ? (
                <section>
                  <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2 mb-1">
                    <Calendar className="w-4 h-4" />
                    Evidence timeline
                  </h3>
                  <p className="mb-3 text-xs text-slate-500">
                    {deal.evidence_timeline_summary?.exact_cited_trial_count ?? 0} exact cited trials ·{' '}
                    {deal.evidence_timeline_summary?.explicit_regulatory_event_count ?? 0} explicit regulatory events
                  </p>
                  <EvidenceTimelineList events={deal.evidence_timeline ?? []} />
                </section>
              ) : deal.timeline.length > 0 ? (
                <section>
                  <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2 mb-3">
                    <Calendar className="w-4 h-4" />
                    Timeline
                  </h3>
                  <div className="space-y-2">
                    {deal.timeline.map((event, idx) => (
                      <div
                        key={idx}
                        className="p-3 bg-slate-800/50 border border-slate-700 rounded-lg"
                      >
                        <div className="flex items-center justify-between mb-1">
                          {event.event_type && (
                            <span className="text-xs font-medium text-blue-400">
                              {event.event_type}
                            </span>
                          )}
                          {event.event_date && (
                            <span className="text-xs text-slate-500">{event.event_date}</span>
                          )}
                        </div>
                        {event.summary && (
                          <div className="text-xs text-slate-400 mt-1">{stripXml(event.summary || '')}</div>
                        )}
                        {event.stage && (
                          <span className="inline-block mt-2 px-2 py-0.5 bg-slate-700 text-slate-300 rounded text-xs">
                            {event.stage}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              ) : null}

              {/* Contracts */}
              {deal.contracts.length > 0 && (
                <section>
                  <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2 mb-3">
                    <FileText className="w-4 h-4" />
                    Contracts
                  </h3>
                  <div className="space-y-2">
                    {deal.contracts.map((contract) => (
                      <div
                        key={contract.id}
                        className="p-3 bg-slate-800/50 border border-slate-700 rounded-lg"
                      >
                        <div className="flex items-start justify-between">
                          <div className="flex-1">
                            {contract.contract_types && (
                              <div className="text-xs font-medium text-slate-200 mb-1">
                                {contract.contract_types}
                              </div>
                            )}
                            <div className="text-xs text-slate-500">
                              {contract.date_contract || contract.date_filing || 'No date'}
                            </div>
                          </div>
                          <div className="flex gap-1">
                            {contract.has_pdf && (
                              <span className="px-1.5 py-0.5 bg-blue-500/10 text-blue-400 text-xs rounded">
                                PDF
                              </span>
                            )}
                            {contract.has_text && (
                              <span className="px-1.5 py-0.5 bg-green-500/10 text-green-400 text-xs rounded">
                                Text
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Cortellis source citations */}
              {(deal.sources?.length ?? 0) > 0 && (
                <section>
                  <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2 mb-3">
                    <FileText className="w-4 h-4" />
                    Cortellis Citations
                  </h3>
                  <div className="space-y-2">
                    {deal.sources?.map((source) => (
                      <div
                        key={`${source.source_type}:${source.source_id}`}
                        className="p-3 bg-slate-800/50 border border-slate-700 rounded-lg"
                      >
                        <div className="text-xs font-medium text-slate-200">
                          {source.source_type || 'Cortellis source'}
                        </div>
                        <div className="text-xs text-slate-500 mt-1">
                          Source ID {source.source_id}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Summary */}
              {deal.summary && (
                <section>
                  <h3 className="text-sm font-medium text-slate-400 mb-3">Summary</h3>
                  <div className="p-3 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-300 leading-relaxed whitespace-pre-line">
                    {stripXml(deal.summary)}
                  </div>
                </section>
              )}
            </>
          ) : null}
        </div>
      </div>
    </>
  );
}

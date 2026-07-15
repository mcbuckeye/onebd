import { useEffect, useState } from 'react';
import {
  X, Building2, DollarSign, FileText, Clock,
  MapPin, Pill, FlaskConical, Activity, ChevronDown, ChevronUp,
  Download
} from 'lucide-react';
import { DealDetail, SelectedEntity } from '../types';
import EvidenceTimelineList from './EvidenceTimelineList';

interface DealDetailPanelProps {
  dealId: number | null;
  apiBase: string;
  onClose: () => void;
  onEntityClick?: (entity: SelectedEntity) => void;
}

export default function DealDetailPanel({ dealId, apiBase, onClose, onEntityClick }: DealDetailPanelProps) {
  const [deal, setDeal] = useState<DealDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(['overview', 'parties', 'financials'])
  );

  useEffect(() => {
    if (!dealId) return;

    const fetchDeal = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(`${apiBase}/deal/${dealId}`);
        if (!response.ok) {
          throw new Error(`Failed to load deal: ${response.status}`);
        }
        const data = await response.json();
        setDeal(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load deal');
      } finally {
        setLoading(false);
      }
    };

    fetchDeal();
  }, [dealId, apiBase]);

  const toggleSection = (section: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev);
      if (next.has(section)) {
        next.delete(section);
      } else {
        next.add(section);
      }
      return next;
    });
  };

  if (!dealId) return null;

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return 'N/A';
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  };

  const formatCurrency = (amount?: number, currency?: string, unit?: string) => {
    if (amount == null) return 'Undisclosed';
    const symbols: Record<string, string> = { USD: '$', EUR: '€', GBP: '£', JPY: '¥' };
    const prefix = symbols[currency || ''] || (currency ? `${currency} ` : '');
    const suffix = unit === 'Million' ? 'M' : unit === 'Billion' ? 'B' : unit ? ` ${unit}` : '';
    return `${prefix}${amount.toLocaleString()}${suffix}`;
  };

  return (
    <div data-testid="deal-panel" className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop - hidden on mobile since panel is full screen */}
      <div
        className="hidden lg:block absolute inset-0 bg-black/50"
        onClick={onClose}
      />

      {/* Panel - full screen on mobile, slide-over on desktop */}
      <div className="relative w-full lg:max-w-2xl bg-slate-900 lg:border-l border-slate-700 overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-slate-900 border-b border-slate-700 px-4 lg:px-6 py-3 lg:py-4 flex items-start justify-between z-10">
          <div className="flex-1 pr-4">
            {loading ? (
              <div className="h-6 w-48 bg-slate-700 rounded animate-pulse" />
            ) : deal ? (
              <>
                <h2 className="text-lg font-semibold text-white leading-tight">
                  {deal.title}
                </h2>
                <div className="flex items-center gap-3 mt-2">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                    deal.status === 'Active' ? 'bg-green-500/20 text-green-400' :
                    deal.status === 'Completed' ? 'bg-blue-500/20 text-blue-400' :
                    deal.status === 'Terminated' ? 'bg-red-500/20 text-red-400' :
                    'bg-slate-500/20 text-slate-400'
                  }`}>
                    {deal.status || 'Unknown'}
                  </span>
                  <span className="text-sm text-slate-400">
                    Deal #{deal.id}
                  </span>
                </div>
              </>
            ) : null}
          </div>
          <button
            data-testid="deal-panel-close"
            onClick={onClose}
            className="p-2 hover:bg-slate-700 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 lg:p-6">
          {loading && (
            <div className="space-y-4">
              {[1, 2, 3].map(i => (
                <div key={i} className="h-24 bg-slate-800 rounded-lg animate-pulse" />
              ))}
            </div>
          )}

          {error && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-400">
              {error}
            </div>
          )}

          {deal && (
            <div className="space-y-4">
              {/* Overview Section */}
              <Section
                title="Overview"
                icon={<Activity className="w-4 h-4" />}
                expanded={expandedSections.has('overview')}
                onToggle={() => toggleSection('overview')}
              >
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 lg:gap-4">
                  <InfoItem label="Deal Type" value={deal.deal_type} />
                  <InfoItem label="Therapy Area" value={deal.therapy_area} />
                  <InfoItem label="Agreement Type" value={deal.agreement_type} />
                  <InfoItem label="Asset Type" value={deal.asset_type} />
                  <InfoItem label="Transaction Type" value={deal.transaction_type} />
                  <InfoItem label="Start Date" value={formatDate(deal.date_start)} />
                  {deal.phase_highest_now && (
                    <InfoItem label="Current Phase" value={deal.phase_highest_now} />
                  )}
                  {deal.is_merger_acquisition && (
                    <InfoItem label="M&A Deal" value="Yes" />
                  )}
                </div>
                {deal.summary && (
                  <div className="mt-4">
                    <div className="text-xs text-slate-500 mb-1">Summary</div>
                    <p className="text-sm text-slate-300 leading-relaxed">
                      {deal.summary}
                    </p>
                  </div>
                )}
              </Section>

              {/* Parties Section */}
              <Section
                title="Parties"
                icon={<Building2 className="w-4 h-4" />}
                expanded={expandedSections.has('parties')}
                onToggle={() => toggleSection('parties')}
                badge={deal.companies.length}
              >
                <div className="space-y-3">
                  {deal.companies.map((company, idx) => (
                    <div key={idx} className="flex items-start justify-between bg-slate-800/50 rounded-lg p-3">
                      <div>
                        <button
                          onClick={() => onEntityClick?.({ type: 'company', id: company.id })}
                          className="text-sm font-medium text-blue-400 hover:text-blue-300 hover:underline flex items-center gap-1 text-left"
                        >
                          {company.name}
                        </button>
                        <div className="text-xs text-slate-400 mt-0.5">
                          {company.company_type}{company.hq_location && ` • ${company.hq_location}`}
                        </div>
                      </div>
                      <span className={`px-2 py-0.5 rounded text-xs ${
                        company.role === 'Principal'
                          ? 'bg-purple-500/20 text-purple-400'
                          : 'bg-cyan-500/20 text-cyan-400'
                      }`}>
                        {company.role}
                      </span>
                    </div>
                  ))}
                </div>
              </Section>

              {/* Financials Section */}
              {deal.finance && (
                <Section
                  title="Financials"
                  icon={<DollarSign className="w-4 h-4" />}
                  expanded={expandedSections.has('financials')}
                  onToggle={() => toggleSection('financials')}
                >
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 lg:gap-4">
                    <div className="bg-slate-800/50 rounded-lg p-3">
                      <div className="text-xs text-slate-500">Total Paid</div>
                      <div className="text-base lg:text-lg font-semibold text-white">
                        {formatCurrency(
                          deal.finance.total_paid_amount,
                          deal.finance.total_paid_currency,
                          deal.finance.total_paid_unit,
                        )}
                      </div>
                      {deal.finance.total_paid_disclosure_status && (
                        <div className="text-xs text-slate-400">
                          {deal.finance.total_paid_disclosure_status}
                        </div>
                      )}
                    </div>
                    <div className="bg-slate-800/50 rounded-lg p-3">
                      <div className="text-xs text-slate-500">Total Projected (Current)</div>
                      <div className="text-lg font-semibold text-green-400">
                        {formatCurrency(
                          deal.finance.total_projected_current_amount,
                          deal.finance.total_projected_current_currency,
                          deal.finance.total_projected_current_unit,
                        )}
                      </div>
                    </div>
                    {deal.finance.total_projected_signing_amount != null && (
                      <div className="bg-slate-800/50 rounded-lg p-3">
                        <div className="text-xs text-slate-500">Total at Signing</div>
                        <div className="text-lg font-semibold text-white">
                          {formatCurrency(
                            deal.finance.total_projected_signing_amount,
                            deal.finance.total_projected_signing_currency,
                            deal.finance.total_projected_signing_unit,
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </Section>
              )}

              {/* Drugs Section */}
              {deal.drugs.length > 0 && (
                <Section
                  title="Drugs"
                  icon={<Pill className="w-4 h-4" />}
                  expanded={expandedSections.has('drugs')}
                  onToggle={() => toggleSection('drugs')}
                  badge={deal.drugs.length}
                >
                  <div className="flex flex-wrap gap-2">
                    {deal.drugs.map((drug) => (
                      <button
                        key={drug.id}
                        onClick={() => onEntityClick?.({ type: 'drug', id: drug.id })}
                        className="px-2 py-1 bg-slate-800 hover:bg-slate-700 rounded text-sm text-blue-400 hover:text-blue-300 transition-colors flex items-center gap-1"
                      >
                        {drug.name}
                        {drug.phase_highest_now && (
                          <span className="text-xs text-slate-500">({drug.phase_highest_now})</span>
                        )}
                      </button>
                    ))}
                  </div>
                </Section>
              )}

              {/* Indications Section */}
              {deal.indications.length > 0 && (
                <Section
                  title="Indications"
                  icon={<FlaskConical className="w-4 h-4" />}
                  expanded={expandedSections.has('indications')}
                  onToggle={() => toggleSection('indications')}
                  badge={deal.indications.length}
                >
                  <div className="flex flex-wrap gap-2">
                    {deal.indications.map((indication) => (
                      <button
                        key={indication.id}
                        onClick={() => onEntityClick?.({ type: 'indication', id: indication.id })}
                        className="px-2 py-1 bg-slate-800 hover:bg-slate-700 rounded text-sm text-blue-400 hover:text-blue-300 transition-colors"
                      >
                        {indication.name}
                      </button>
                    ))}
                  </div>
                </Section>
              )}

              {/* Technologies Section */}
              {deal.technologies.length > 0 && (
                <Section
                  title="Technologies"
                  icon={<FlaskConical className="w-4 h-4" />}
                  expanded={expandedSections.has('technologies')}
                  onToggle={() => toggleSection('technologies')}
                  badge={deal.technologies.length}
                >
                  <div className="flex flex-wrap gap-2">
                    {deal.technologies.map((tech) => (
                      <button
                        key={tech.id}
                        onClick={() => onEntityClick?.({ type: 'technology', id: tech.id })}
                        className="px-2 py-1 bg-slate-800 hover:bg-slate-700 rounded text-sm text-blue-400 hover:text-blue-300 transition-colors"
                      >
                        {tech.name}
                      </button>
                    ))}
                  </div>
                </Section>
              )}

              {/* Territories Section */}
              {(deal.territories_included.length > 0 || deal.territories_excluded.length > 0) && (
                <Section
                  title="Territories"
                  icon={<MapPin className="w-4 h-4" />}
                  expanded={expandedSections.has('territories')}
                  onToggle={() => toggleSection('territories')}
                >
                  {deal.territories_included.length > 0 && (
                    <div className="mb-3">
                      <div className="text-xs text-slate-500 mb-1">Included</div>
                      <div className="flex flex-wrap gap-1">
                        {deal.territories_included.map((t, idx) => (
                          <span key={idx} className="px-2 py-0.5 bg-green-500/20 text-green-400 rounded text-xs">
                            {t}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {deal.territories_excluded.length > 0 && (
                    <div>
                      <div className="text-xs text-slate-500 mb-1">Excluded</div>
                      <div className="flex flex-wrap gap-1">
                        {deal.territories_excluded.map((t, idx) => (
                          <span key={idx} className="px-2 py-0.5 bg-red-500/20 text-red-400 rounded text-xs">
                            {t}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </Section>
              )}

              {/* Source-labeled timeline */}
              {(deal.evidence_timeline?.length ?? 0) > 0 ? (
                <Section
                  title="Evidence Timeline"
                  icon={<Clock className="w-4 h-4" />}
                  expanded={expandedSections.has('timeline')}
                  onToggle={() => toggleSection('timeline')}
                  badge={deal.evidence_timeline?.length}
                >
                  <p className="mb-3 text-xs text-slate-500">
                    {deal.evidence_timeline_summary?.exact_cited_trial_count ?? 0} exact cited trials ·{' '}
                    {deal.evidence_timeline_summary?.explicit_regulatory_event_count ?? 0} explicit regulatory events
                  </p>
                  <EvidenceTimelineList events={deal.evidence_timeline ?? []} />
                </Section>
              ) : deal.timeline.length > 0 ? (
                <Section
                  title="Timeline"
                  icon={<Clock className="w-4 h-4" />}
                  expanded={expandedSections.has('timeline')}
                  onToggle={() => toggleSection('timeline')}
                  badge={deal.timeline.length}
                >
                  <div className="space-y-3">
                    {deal.timeline.map((event, idx) => (
                      <div key={idx} className="flex gap-3 border-l-2 border-slate-700 pl-3">
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-white">
                              {event.event_type || event.stage || 'Event'}
                            </span>
                            {event.event_date && (
                              <span className="text-xs text-slate-500">
                                {formatDate(event.event_date)}
                              </span>
                            )}
                          </div>
                          {event.summary && (
                            <p className="text-xs text-slate-400 mt-1 line-clamp-2">
                              {event.summary}
                            </p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </Section>
              ) : null}

              {/* Contracts Section */}
              {deal.contracts.length > 0 && (
                <Section
                  title="Source Documents"
                  icon={<FileText className="w-4 h-4" />}
                  expanded={expandedSections.has('contracts')}
                  onToggle={() => toggleSection('contracts')}
                  badge={deal.contracts.length}
                >
                  <div className="space-y-2">
                    {deal.contracts.map((contract) => (
                      <div key={contract.id} className="flex items-center justify-between bg-slate-800/50 rounded-lg p-3">
                        <div className="flex-1">
                          <div className="text-sm font-medium text-white">
                            {contract.contract_types || 'Contract'}
                          </div>
                          <div className="text-xs text-slate-400 mt-0.5">
                            {contract.date_filing && `Filed: ${formatDate(contract.date_filing)}`}
                            {contract.date_contract && ` • Dated: ${formatDate(contract.date_contract)}`}
                          </div>
                        </div>
                        <div className="flex gap-2">
                          {contract.has_pdf && (
                            <a
                              href={`${apiBase}/contract/${contract.id}/pdf`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="flex items-center gap-1 px-2 py-1 bg-red-500/20 text-red-400 hover:bg-red-500/30 rounded text-xs transition-colors"
                              title="Download PDF"
                            >
                              <Download className="w-3 h-3" />
                              PDF
                            </a>
                          )}
                          {contract.has_text && (
                            <a
                              href={`${apiBase}/contract/${contract.id}/text`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="flex items-center gap-1 px-2 py-1 bg-blue-500/20 text-blue-400 hover:bg-blue-500/30 rounded text-xs transition-colors"
                              title="View Text"
                            >
                              <FileText className="w-3 h-3" />
                              TXT
                            </a>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              {/* Cortellis source citations */}
              {(deal.sources?.length ?? 0) > 0 && (
                <Section
                  title="Cortellis Citations"
                  icon={<FileText className="w-4 h-4" />}
                  expanded={expandedSections.has('citations')}
                  onToggle={() => toggleSection('citations')}
                  badge={deal.sources?.length}
                >
                  <div className="space-y-2">
                    {deal.sources?.map((source) => (
                      <div
                        key={`${source.source_type}:${source.source_id}`}
                        className="bg-slate-800/50 rounded-lg p-3"
                      >
                        <div className="text-sm font-medium text-white">
                          {source.source_type || 'Cortellis source'}
                        </div>
                        <div className="text-xs text-slate-400 mt-0.5">
                          Source ID {source.source_id}
                        </div>
                      </div>
                    ))}
                  </div>
                </Section>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({
  title,
  icon,
  expanded,
  onToggle,
  badge,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  expanded: boolean;
  onToggle: () => void;
  badge?: number;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-slate-800/30 rounded-lg border border-slate-700">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-slate-700/30 transition-colors"
      >
        <div className="flex items-center gap-2 text-slate-300">
          {icon}
          <span className="font-medium">{title}</span>
          {badge !== undefined && (
            <span className="px-1.5 py-0.5 bg-slate-700 rounded text-xs text-slate-400">
              {badge}
            </span>
          )}
        </div>
        {expanded ? (
          <ChevronUp className="w-4 h-4 text-slate-500" />
        ) : (
          <ChevronDown className="w-4 h-4 text-slate-500" />
        )}
      </button>
      {expanded && (
        <div className="px-4 pb-4">
          {children}
        </div>
      )}
    </div>
  );
}

function InfoItem({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-sm text-slate-300">{value || 'N/A'}</div>
    </div>
  );
}

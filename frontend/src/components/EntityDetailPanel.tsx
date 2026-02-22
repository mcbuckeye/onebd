import { useEffect, useState } from 'react';
import {
  X, Building2, Pill, FlaskConical, Activity,
  ExternalLink, DollarSign, Calendar
} from 'lucide-react';
import { EntityDetail, DrugDetail, CompanyDetail, SelectedEntity, DealSummary } from '../types';

interface EntityDetailPanelProps {
  entity: SelectedEntity | null;
  apiBase: string;
  onClose: () => void;
  onDealClick: (dealId: number) => void;
}

type EntityData = EntityDetail | DrugDetail | CompanyDetail | null;

export default function EntityDetailPanel({
  entity,
  apiBase,
  onClose,
  onDealClick
}: EntityDetailPanelProps) {
  const [data, setData] = useState<EntityData>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!entity) return;

    const fetchEntity = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(`${apiBase}/entity/${entity.type}/${entity.id}`);
        if (!response.ok) {
          throw new Error(`Failed to load ${entity.type}: ${response.status}`);
        }
        const result = await response.json();
        setData(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load entity');
      } finally {
        setLoading(false);
      }
    };

    fetchEntity();
  }, [entity, apiBase]);

  if (!entity) return null;

  const getIcon = () => {
    switch (entity.type) {
      case 'drug': return <Pill className="w-5 h-5 text-pink-400" />;
      case 'indication': return <Activity className="w-5 h-5 text-orange-400" />;
      case 'technology': return <FlaskConical className="w-5 h-5 text-cyan-400" />;
      case 'company': return <Building2 className="w-5 h-5 text-purple-400" />;
    }
  };

  const getTypeLabel = () => {
    switch (entity.type) {
      case 'drug': return 'Drug';
      case 'indication': return 'Indication';
      case 'technology': return 'Technology';
      case 'company': return 'Company';
    }
  };

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return null;
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
    });
  };

  const formatCurrency = (amount?: number) => {
    if (amount == null) return null;
    return `$${amount.toLocaleString()}M`;
  };

  const isCompanyDetail = (d: EntityData): d is CompanyDetail => {
    return d !== null && 'deals_as_principal' in d;
  };

  const isDrugDetail = (d: EntityData): d is DrugDetail => {
    return d !== null && 'phase_highest_now' in d && !('deals_as_principal' in d);
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop - hidden on mobile since panel is full screen */}
      <div className="hidden lg:block absolute inset-0 bg-black/50" onClick={onClose} />

      {/* Panel - full screen on mobile, slide-over on desktop */}
      <div className="relative w-full lg:max-w-xl bg-slate-900 lg:border-l border-slate-700 overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-slate-900 border-b border-slate-700 px-4 lg:px-6 py-3 lg:py-4 flex items-start justify-between z-10">
          <div className="flex-1 pr-4">
            {loading ? (
              <div className="h-6 w-48 bg-slate-700 rounded animate-pulse" />
            ) : data ? (
              <>
                <div className="flex items-center gap-2 mb-1">
                  {getIcon()}
                  <span className="text-xs text-slate-400 uppercase tracking-wider">
                    {getTypeLabel()}
                  </span>
                </div>
                <h2 className="text-lg font-semibold text-white leading-tight">
                  {data.name}
                </h2>
                <div className="text-sm text-slate-400 mt-1">
                  {data.deal_count.toLocaleString()} deals
                </div>
              </>
            ) : null}
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-slate-700 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 lg:p-6">
          {loading && (
            <div className="space-y-3">
              {[1, 2, 3, 4, 5].map(i => (
                <div key={i} className="h-16 bg-slate-800 rounded-lg animate-pulse" />
              ))}
            </div>
          )}

          {error && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-400">
              {error}
            </div>
          )}

          {data && (
            <div className="space-y-6">
              {/* Extra info for drugs */}
              {isDrugDetail(data) && (data.phase_highest_start || data.phase_highest_now) && (
                <div className="bg-slate-800/50 rounded-lg p-3 lg:p-4">
                  <div className="grid grid-cols-2 gap-3 lg:gap-4">
                    {data.phase_highest_start && (
                      <div>
                        <div className="text-xs text-slate-500">Phase at Start</div>
                        <div className="text-sm text-slate-300">{data.phase_highest_start}</div>
                      </div>
                    )}
                    {data.phase_highest_now && (
                      <div>
                        <div className="text-xs text-slate-500">Current Phase</div>
                        <div className="text-sm text-slate-300">{data.phase_highest_now}</div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Extra info for companies */}
              {isCompanyDetail(data) && (data.company_type || data.hq_location) && (
                <div className="bg-slate-800/50 rounded-lg p-3 lg:p-4">
                  <div className="grid grid-cols-2 gap-3 lg:gap-4">
                    {data.company_type && (
                      <div>
                        <div className="text-xs text-slate-500">Type</div>
                        <div className="text-sm text-slate-300">{data.company_type}</div>
                      </div>
                    )}
                    {data.hq_location && (
                      <div>
                        <div className="text-xs text-slate-500">Headquarters</div>
                        <div className="text-sm text-slate-300">{data.hq_location}</div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Deals list */}
              {isCompanyDetail(data) ? (
                <>
                  {data.deals_as_principal.length > 0 && (
                    <DealSection
                      title="Deals as Principal (Seller/Licensor)"
                      deals={data.deals_as_principal}
                      onDealClick={onDealClick}
                      formatDate={formatDate}
                      formatCurrency={formatCurrency}
                    />
                  )}
                  {data.deals_as_partner.length > 0 && (
                    <DealSection
                      title="Deals as Partner (Buyer/Licensee)"
                      deals={data.deals_as_partner}
                      onDealClick={onDealClick}
                      formatDate={formatDate}
                      formatCurrency={formatCurrency}
                    />
                  )}
                </>
              ) : (
                <DealSection
                  title="Related Deals"
                  deals={data.deals}
                  onDealClick={onDealClick}
                  formatDate={formatDate}
                  formatCurrency={formatCurrency}
                />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function DealSection({
  title,
  deals,
  onDealClick,
  formatDate,
  formatCurrency
}: {
  title: string;
  deals: DealSummary[];
  onDealClick: (id: number) => void;
  formatDate: (d?: string) => string | null;
  formatCurrency: (a?: number) => string | null;
}) {
  return (
    <div>
      <h3 className="text-sm font-medium text-slate-400 mb-3">{title}</h3>
      <div className="space-y-2">
        {deals.map(deal => (
          <button
            key={deal.id}
            onClick={() => onDealClick(deal.id)}
            className="w-full text-left bg-slate-800/50 hover:bg-slate-700/50 rounded-lg p-3 transition-colors group"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <div className="text-sm text-blue-400 group-hover:text-blue-300 flex items-center gap-1">
                  <span className="truncate">{deal.title}</span>
                  <ExternalLink className="w-3 h-3 opacity-50 flex-shrink-0" />
                </div>
                <div className="flex items-center gap-3 mt-1 text-xs text-slate-500">
                  {deal.status && (
                    <span className={`px-1.5 py-0.5 rounded ${
                      deal.status === 'Active' ? 'bg-green-500/20 text-green-400' :
                      deal.status === 'Completed' ? 'bg-blue-500/20 text-blue-400' :
                      deal.status === 'Terminated' ? 'bg-red-500/20 text-red-400' :
                      'bg-slate-500/20 text-slate-400'
                    }`}>
                      {deal.status}
                    </span>
                  )}
                  {formatDate(deal.date_start) && (
                    <span className="flex items-center gap-1">
                      <Calendar className="w-3 h-3" />
                      {formatDate(deal.date_start)}
                    </span>
                  )}
                  {formatCurrency(deal.total_value) && (
                    <span className="flex items-center gap-1 text-green-400">
                      <DollarSign className="w-3 h-3" />
                      {formatCurrency(deal.total_value)}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

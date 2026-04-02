import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { TrendingUp, TrendingDown, Minus, ArrowRight, DollarSign, Activity, Layers, CheckCircle, AlertTriangle, XCircle } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import api, { DealSummary } from '../lib/api';
import DealDetailSlidePanel from '../components/DealDetailSlidePanel';

interface DashboardData {
  market_pulse: {
    deal_count_30d: number;
    deal_count_prev_30d: number;
    avg_value_30d: number | null;
    disclosed_count_30d: number;
    top_therapy_areas: Array<{ name: string; count: number }>;
    monthly_trend: Array<{ month: string; count: number }>;
  };
  notable_deals: Array<DealSummary & { agreement_type?: string }>;
}

interface Recommendation {
  deal_id: number;
  title: string;
  agreement_type: string;
  date: string;
  value: number | null;
  principal: string;
  partner: string;
  indication: string | null;
  modality: string | null;
  reasons: string[];
}

interface DataHealth {
  overall_score: number;
  checks: Array<{
    name: string;
    status: 'ok' | 'warning' | 'critical';
    detail: string;
  }>;
  sources: {
    cortellis_deals?: { total: number; with_financials: number };
    companies?: { total: number; cross_referenced: number };
    neo4j?: { companies: number; deals: number; relationships: number };
  };
}

function StatCard({ label, value, subtext, trend, icon: Icon }: {
  label: string; value: string; subtext?: string;
  trend?: 'up' | 'down' | 'flat';
  icon: any;
}) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-slate-500">{label}</span>
        <Icon className="w-5 h-5 text-slate-600" />
      </div>
      <div className="text-2xl font-bold text-slate-100">{value}</div>
      {subtext && (
        <div className="flex items-center gap-1 mt-1.5">
          {trend === 'up' && <TrendingUp className="w-3.5 h-3.5 text-green-400" />}
          {trend === 'down' && <TrendingDown className="w-3.5 h-3.5 text-red-400" />}
          {trend === 'flat' && <Minus className="w-3.5 h-3.5 text-slate-500" />}
          <span className={`text-xs ${
            trend === 'up' ? 'text-green-400' : trend === 'down' ? 'text-red-400' : 'text-slate-500'
          }`}>{subtext}</span>
        </div>
      )}
    </div>
  );
}

function formatValue(v: number | null): string {
  if (v === null) return 'N/A';
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
  return `$${v.toFixed(0)}M`;
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [dataHealth, setDataHealth] = useState<DataHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedDealId, setSelectedDealId] = useState<number | null>(null);

  useEffect(() => {
    Promise.allSettled([
      api.get('/dashboard/executive'),
      api.get('/recommendations?limit=5'),
      api.get('/health/data')
    ])
      .then(([dashRes, recRes, healthRes]) => {
        if (dashRes.status === 'fulfilled') setData(dashRes.value.data);
        if (recRes.status === 'fulfilled') setRecommendations(recRes.value.data.recommendations || []);
        if (healthRes.status === 'fulfilled') setDataHealth(healthRes.value.data);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="p-6 animate-pulse">
        <div className="h-8 w-48 bg-slate-800 rounded mb-6" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          {[1, 2, 3].map(i => <div key={i} className="h-28 bg-slate-800 rounded-xl" />)}
        </div>
      </div>
    );
  }

  if (!data) return <div className="p-6 text-slate-400">Failed to load dashboard</div>;

  const { market_pulse: pulse, notable_deals } = data;
  const dealChange = pulse.deal_count_prev_30d > 0
    ? ((pulse.deal_count_30d - pulse.deal_count_prev_30d) / pulse.deal_count_prev_30d * 100)
    : 0;
  const dealTrend = dealChange > 5 ? 'up' : dealChange < -5 ? 'down' : 'flat';

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-100">Market Pulse</h1>
        <p className="text-sm text-slate-500 mt-1">Pharmaceutical deal activity overview</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <StatCard
          label="Deals (30d)"
          value={pulse.deal_count_30d.toLocaleString()}
          subtext={`${dealChange >= 0 ? '+' : ''}${dealChange.toFixed(0)}% vs prior 30d`}
          trend={dealTrend}
          icon={Activity}
        />
        <StatCard
          label="Avg Deal Value (30d)"
          value={formatValue(pulse.avg_value_30d)}
          subtext={`${pulse.disclosed_count_30d} disclosed deals`}
          icon={DollarSign}
        />
        <StatCard
          label="Top Therapy Area"
          value={pulse.top_therapy_areas[0]?.name || 'N/A'}
          subtext={`${pulse.top_therapy_areas[0]?.count || 0} deals (90d)`}
          icon={Layers}
        />
      </div>

      {/* Deal Volume Trend */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 mb-6">
        <h2 className="text-sm font-medium text-slate-400 mb-4">Deal Volume (12 months)</h2>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={pulse.monthly_trend}>
            <XAxis
              dataKey="month"
              tickFormatter={(v) => new Date(v).toLocaleDateString('en', { month: 'short' })}
              stroke="#475569"
              fontSize={12}
            />
            <YAxis stroke="#475569" fontSize={12} />
            <Tooltip
              contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
              labelFormatter={(v) => new Date(v).toLocaleDateString('en', { month: 'long', year: 'numeric' })}
            />
            <Line type="monotone" dataKey="count" stroke="#3b82f6" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Notable Deals */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-medium text-slate-400">Notable Deals (60d)</h2>
            <Link to="/search" className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1">
              View all <ArrowRight className="w-3 h-3" />
            </Link>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-800">
                  <th className="pb-2 pr-4">Deal</th>
                  <th className="pb-2 pr-4">Type</th>
                  <th className="pb-2 pr-4">Value</th>
                  <th className="pb-2">Date</th>
                </tr>
              </thead>
              <tbody>
                {notable_deals.map(deal => (
                  <tr 
                    key={deal.id} 
                    onClick={() => setSelectedDealId(deal.id)}
                    className="border-b border-slate-800/50 hover:bg-slate-800/30 cursor-pointer"
                  >
                    <td className="py-2.5 pr-4">
                      <div className="text-slate-200 font-medium truncate max-w-xs">{deal.title}</div>
                      <div className="text-xs text-slate-500">
                        {deal.principal_company} → {deal.partner_company}
                      </div>
                    </td>
                    <td className="py-2.5 pr-4 text-slate-400 text-xs">{deal.agreement_type || deal.deal_type || '—'}</td>
                    <td className="py-2.5 pr-4 text-slate-300">
                      {deal.total_value ? formatValue(deal.total_value) : '—'}
                    </td>
                    <td className="py-2.5 text-slate-500 text-xs">{deal.date_start || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Top Therapy Areas */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-slate-400 mb-4">Active Therapy Areas (90d)</h2>
          <div className="space-y-3">
            {pulse.top_therapy_areas.map((ta) => (
              <div key={ta.name}>
                <div className="flex items-center justify-between text-sm mb-1">
                  <span className="text-slate-300">{ta.name}</span>
                  <span className="text-slate-500">{ta.count}</span>
                </div>
                <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 rounded-full"
                    style={{ width: `${(ta.count / (pulse.top_therapy_areas[0]?.count || 1)) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Recommendations */}
      {recommendations.length > 0 && (
        <div className="mt-6 bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-medium text-slate-400 mb-4">Deals You Should Know About</h2>
          <div className="space-y-3">
            {recommendations.map((rec) => (
              <div key={rec.deal_id} className="flex items-start justify-between py-3 border-b border-slate-800/50 last:border-0">
                <div className="flex-1">
                  <div className="text-sm text-slate-200 font-medium">{rec.title}</div>
                  <div className="text-xs text-slate-500 mt-0.5">
                    {rec.principal} → {rec.partner} • {rec.agreement_type}
                  </div>
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {rec.reasons.map((reason, i) => (
                      <span key={i} className="px-2 py-0.5 bg-blue-500/10 border border-blue-500/30 rounded text-xs text-blue-400">
                        {reason}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="text-right flex-shrink-0 ml-4">
                  <div className="text-sm text-slate-300 font-medium">{formatValue(rec.value)}</div>
                  <div className="text-xs text-slate-500">{rec.date}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Data Health Status */}
      {dataHealth && (
        <div className="mt-6 bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-medium text-slate-400">Data Health Status</h2>
            <div className={`px-3 py-1 rounded-full text-xs font-semibold ${
              dataHealth.overall_score >= 80 ? 'bg-green-500/10 text-green-400 border border-green-500/30' :
              dataHealth.overall_score >= 60 ? 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/30' :
              'bg-red-500/10 text-red-400 border border-red-500/30'
            }`}>
              Score: {dataHealth.overall_score}/100
            </div>
          </div>

          {/* Health Checks */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
            {dataHealth.checks.map((check, i) => {
              const Icon = check.status === 'ok' ? CheckCircle : check.status === 'warning' ? AlertTriangle : XCircle;
              const colorClass = check.status === 'ok' ? 'text-green-400' : check.status === 'warning' ? 'text-yellow-400' : 'text-red-400';
              
              return (
                <div key={i} className="flex items-start gap-2 p-2 rounded border border-slate-800/50">
                  <Icon className={`w-4 h-4 flex-shrink-0 mt-0.5 ${colorClass}`} />
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium text-slate-300">{check.name}</div>
                    <div className="text-xs text-slate-500 mt-0.5 truncate">{check.detail}</div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Source Summary */}
          <div className="grid grid-cols-3 gap-3 pt-3 border-t border-slate-800">
            <div className="text-center">
              <div className="text-xs text-slate-500">Deals</div>
              <div className="text-lg font-bold text-slate-200 mt-1">
                {dataHealth.sources.cortellis_deals?.total.toLocaleString() || '—'}
              </div>
            </div>
            <div className="text-center">
              <div className="text-xs text-slate-500">Companies</div>
              <div className="text-lg font-bold text-slate-200 mt-1">
                {dataHealth.sources.companies?.total.toLocaleString() || '—'}
              </div>
            </div>
            <div className="text-center">
              <div className="text-xs text-slate-500">Graph Nodes</div>
              <div className="text-lg font-bold text-slate-200 mt-1">
                {((dataHealth.sources.neo4j?.companies || 0) + (dataHealth.sources.neo4j?.deals || 0)).toLocaleString()}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Deal Detail Slide Panel */}
      <DealDetailSlidePanel 
        dealId={selectedDealId} 
        onClose={() => setSelectedDealId(null)} 
      />
    </div>
  );
}

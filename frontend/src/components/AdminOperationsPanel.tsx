import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  Database,
  Gauge,
  HardDrive,
  Loader2,
  PlayCircle,
  RefreshCw,
  Save,
  Search,
  Settings2,
  Trash2,
  X,
} from 'lucide-react';
import api from '../lib/api';

type OperationsTab = 'overview' | 'requests' | 'sql' | 'jobs' | 'databases' | 'settings';

interface RequestSummary {
  requests: number;
  errors: number;
  slow_requests: number;
  average_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
  sql_calls: number;
  sql_time_ms: number | null;
  dropped_sql_spans: number;
  principals: number;
  error_rate: number;
  server_errors: number;
  server_error_rate: number;
  client_rejections: number;
  client_rejection_rate: number;
  non_sql_time_ms: number | null;
}

interface OperationsSummary {
  slow_request_ms: number;
  slow_sql_ms: number;
  requests: RequestSummary;
  jobs: Record<string, number | null>;
  by_channel: any[];
  slow_routes: any[];
  hourly: any[];
  recent_errors: any[];
}

interface TelemetrySettings {
  enabled: boolean;
  capture_request_payloads: boolean;
  retain_normalized_sql: boolean;
  sql_min_duration_ms: number;
  slow_request_ms: number;
  slow_sql_ms: number;
  max_sql_spans_per_operation: number;
  payload_max_bytes: number;
  retention_days: number;
}

const TABS: { id: OperationsTab; label: string; icon: any }[] = [
  { id: 'overview', label: 'Overview', icon: Gauge },
  { id: 'requests', label: 'Requests & MCP', icon: Activity },
  { id: 'sql', label: 'SQL', icon: Database },
  { id: 'jobs', label: 'Jobs', icon: PlayCircle },
  { id: 'databases', label: 'DB & Schema', icon: HardDrive },
  { id: 'settings', label: 'Settings', icon: Settings2 },
];
const PAGE_SIZE = 100;

function number(value: any, digits = 0) {
  if (value === null || value === undefined) return '—';
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function duration(value: any) {
  const ms = Number(value || 0);
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`;
  if (ms >= 1_000) return `${(ms / 1_000).toFixed(2)}s`;
  return `${ms.toFixed(ms < 10 ? 2 : 0)}ms`;
}

function bytes(value: any) {
  let size = Number(value || 0);
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function date(value: any) {
  return value ? new Date(value).toLocaleString() : '—';
}

function statusTone(status: number) {
  if (status >= 500) return 'bg-red-500/15 text-red-300';
  if (status >= 400) return 'bg-amber-500/15 text-amber-300';
  return 'bg-emerald-500/15 text-emerald-300';
}

function MetricCard({ label, value, detail, warning = false }: {
  label: string;
  value: string;
  detail?: string;
  warning?: boolean;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-2 text-2xl font-semibold ${warning ? 'text-amber-300' : 'text-slate-100'}`}>{value}</div>
      {detail && <div className="mt-1 text-xs text-slate-600">{detail}</div>}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="py-10 text-center text-sm text-slate-500">{children}</div>;
}

export default function AdminOperationsPanel() {
  const [tab, setTab] = useState<OperationsTab>('overview');
  const [hours, setHours] = useState(24);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [summary, setSummary] = useState<OperationsSummary | null>(null);
  const [requests, setRequests] = useState<any[]>([]);
  const [requestTotal, setRequestTotal] = useState(0);
  const [requestOffset, setRequestOffset] = useState(0);
  const [requestFilters, setRequestFilters] = useState({ path: '', principal: '', channel: '', status: '', minDuration: '' });
  const [requestDetail, setRequestDetail] = useState<any | null>(null);
  const [sql, setSql] = useState<any[]>([]);
  const [sqlTotal, setSqlTotal] = useState(0);
  const [sqlOffset, setSqlOffset] = useState(0);
  const [sqlFilters, setSqlFilters] = useState({ database: '', search: '', sort: 'total', minDuration: '', errorsOnly: false });
  const [expandedSql, setExpandedSql] = useState<string | null>(null);
  const [jobs, setJobs] = useState<any[]>([]);
  const [jobTotal, setJobTotal] = useState(0);
  const [jobOffset, setJobOffset] = useState(0);
  const [jobFilter, setJobFilter] = useState('');
  const [jobStatus, setJobStatus] = useState('');
  const [jobDetail, setJobDetail] = useState<any | null>(null);
  const [databases, setDatabases] = useState<any | null>(null);
  const [selectedDatabase, setSelectedDatabase] = useState('cortellis');
  const [settings, setSettings] = useState<TelemetrySettings | null>(null);

  const load = async (selectedTab = tab) => {
    setLoading(true);
    setError('');
    try {
      if (selectedTab === 'overview') {
        const response = await api.get(`/admin/operations/summary?hours=${hours}`);
        setSummary(response.data);
      } else if (selectedTab === 'requests') {
        const params = new URLSearchParams({ hours: String(hours), limit: String(PAGE_SIZE), offset: String(requestOffset) });
        if (requestFilters.path) params.set('path', requestFilters.path);
        if (requestFilters.principal) params.set('principal', requestFilters.principal);
        if (requestFilters.channel) params.set('channel', requestFilters.channel);
        if (requestFilters.status) params.set('status', requestFilters.status);
        if (requestFilters.minDuration) params.set('min_duration_ms', requestFilters.minDuration);
        const response = await api.get(`/admin/operations/requests?${params}`);
        setRequests(response.data.items);
        setRequestTotal(response.data.total);
      } else if (selectedTab === 'sql') {
        const params = new URLSearchParams({ hours: String(hours), limit: String(PAGE_SIZE), offset: String(sqlOffset), sort: sqlFilters.sort });
        if (sqlFilters.database) params.set('database_name', sqlFilters.database);
        if (sqlFilters.search) params.set('search', sqlFilters.search);
        if (sqlFilters.minDuration) params.set('min_duration_ms', sqlFilters.minDuration);
        if (sqlFilters.errorsOnly) params.set('errors_only', 'true');
        const response = await api.get(`/admin/operations/sql?${params}`);
        setSql(response.data.items);
        setSqlTotal(response.data.total);
      } else if (selectedTab === 'jobs') {
        const params = new URLSearchParams({ hours: String(Math.max(hours, 168)), limit: String(PAGE_SIZE), offset: String(jobOffset) });
        if (jobFilter) params.set('task_name', jobFilter);
        if (jobStatus) params.set('status', jobStatus);
        const response = await api.get(`/admin/operations/jobs?${params}`);
        setJobs(response.data.items);
        setJobTotal(response.data.total);
      } else if (selectedTab === 'databases') {
        const response = await api.get('/admin/operations/databases');
        setDatabases(response.data);
      } else if (selectedTab === 'settings') {
        const response = await api.get('/admin/operations/settings');
        setSettings(response.data);
      }
    } catch (requestError: any) {
      setError(requestError.response?.data?.detail || 'Failed to load operations telemetry');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(tab);
  }, [tab, hours, requestOffset, sqlOffset, jobOffset]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(() => load(tab), 15_000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, tab, hours, requestFilters, sqlFilters, jobFilter, jobStatus, requestOffset, sqlOffset, jobOffset]);

  const openRequest = async (requestId: string) => {
    setLoading(true);
    try {
      const response = await api.get(`/admin/operations/requests/${requestId}`);
      setRequestDetail(response.data);
    } catch (requestError: any) {
      setError(requestError.response?.data?.detail || 'Failed to load request detail');
    } finally {
      setLoading(false);
    }
  };

  const openJob = async (taskId: string) => {
    setLoading(true);
    try {
      const response = await api.get(`/admin/operations/jobs/${taskId}`);
      setJobDetail(response.data);
    } catch (requestError: any) {
      setError(requestError.response?.data?.detail || 'Failed to load job detail');
    } finally {
      setLoading(false);
    }
  };

  const saveSettings = async () => {
    if (!settings) return;
    setLoading(true);
    setError('');
    setMessage('');
    try {
      const response = await api.put('/admin/operations/settings', settings);
      setSettings(response.data);
      setMessage('Telemetry policy saved and effective for new operations.');
    } catch (requestError: any) {
      setError(requestError.response?.data?.detail || 'Failed to save telemetry settings');
    } finally {
      setLoading(false);
    }
  };

  const purge = async () => {
    if (!settings || !confirm(`Delete telemetry older than ${settings.retention_days} days now?`)) return;
    setLoading(true);
    try {
      const response = await api.post('/admin/operations/purge', { older_than_days: settings.retention_days });
      const deleted = Object.values(response.data.deleted || {}).reduce((sum: number, value: any) => sum + Number(value || 0), 0);
      setMessage(`Purged ${deleted.toLocaleString()} expired telemetry records.`);
    } catch (requestError: any) {
      setError(requestError.response?.data?.detail || 'Failed to purge telemetry');
    } finally {
      setLoading(false);
    }
  };

  const snapshot = async () => {
    setLoading(true);
    setMessage('');
    try {
      const response = await api.post('/admin/operations/databases/snapshot');
      setMessage(`Captured ${response.data.captured} database schema snapshots.`);
      await load('databases');
    } catch (requestError: any) {
      setError(requestError.response?.data?.detail || 'Failed to capture schema snapshot');
    } finally {
      setLoading(false);
    }
  };

  const activeDatabase = useMemo(
    () => databases?.databases?.find((item: any) => item.name === selectedDatabase),
    [databases, selectedDatabase],
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-100">
            <Activity className="h-5 w-5 text-cyan-400" /> Operations & performance
          </h2>
          <p className="mt-1 text-sm text-slate-500">Correlated API, MCP, SQL, job, database, and schema telemetry. Values and secrets are redacted.</p>
        </div>
        <div className="flex items-center gap-2">
          <select value={hours} onChange={(event) => { setRequestOffset(0); setSqlOffset(0); setJobOffset(0); setHours(Number(event.target.value)); }} className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-300">
            <option value={1}>Last hour</option>
            <option value={6}>Last 6 hours</option>
            <option value={24}>Last 24 hours</option>
            <option value={168}>Last 7 days</option>
            <option value={720}>Last 30 days</option>
          </select>
          <label className="flex items-center gap-2 text-xs text-slate-500">
            <input type="checkbox" checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} /> Auto
          </label>
          <button onClick={() => load(tab)} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-50">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </button>
        </div>
      </div>

      {error && <div className="flex gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300"><AlertTriangle className="h-4 w-4 shrink-0" />{error}</div>}
      {message && <div className="flex gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-300"><CheckCircle2 className="h-4 w-4 shrink-0" />{message}</div>}

      <div className="flex gap-1 overflow-x-auto border-b border-slate-800">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => setTab(id)} className={`flex items-center gap-2 whitespace-nowrap border-b-2 px-3 py-2 text-xs font-medium ${tab === id ? 'border-cyan-400 text-cyan-300' : 'border-transparent text-slate-500 hover:text-slate-300'}`}>
            <Icon className="h-4 w-4" /> {label}
          </button>
        ))}
      </div>

      {loading && !summary && <div className="flex justify-center py-12 text-slate-500"><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading telemetry…</div>}

      {tab === 'overview' && summary && (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard label="Requests" value={number(summary.requests.requests)} detail={`${number(summary.requests.principals)} active principals`} />
            <MetricCard label="p95 latency" value={duration(summary.requests.p95_ms)} detail={`p50 ${duration(summary.requests.p50_ms)} · p99 ${duration(summary.requests.p99_ms)}`} warning={Number(summary.requests.p95_ms) >= summary.slow_request_ms} />
            <MetricCard label="Server errors" value={`${(summary.requests.server_error_rate * 100).toFixed(2)}%`} detail={`${number(summary.requests.server_errors)} 5xx/exceptions · ${number(summary.requests.client_rejections)} expected 4xx`} warning={summary.requests.server_errors > 0} />
            <MetricCard label="Execution time" value={duration(summary.requests.non_sql_time_ms)} detail={`${duration(summary.requests.sql_time_ms)} SQL · ${number(summary.requests.sql_calls)} statements`} warning={summary.requests.dropped_sql_spans > 0} />
          </div>
          <div className="grid gap-5 xl:grid-cols-2">
            <section className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
              <h3 className="text-sm font-semibold text-slate-200">Channels</h3>
              <div className="mt-3 space-y-2">
                {summary.by_channel.map((item) => (
                  <div key={item.channel} className="grid grid-cols-[1fr_auto_auto_auto] gap-4 rounded-lg bg-slate-900/70 px-3 py-2 text-xs">
                    <span className="font-medium text-slate-300">{item.channel}</span><span className="text-slate-500">{number(item.requests)} calls</span><span className="text-slate-500">p95 {duration(item.p95_ms)}</span><span className={item.server_errors ? 'text-red-300' : 'text-slate-600'}>{number(item.server_errors)} server / {number(item.client_rejections)} client</span>
                  </div>
                ))}
                {!summary.by_channel.length && <Empty>No request telemetry yet.</Empty>}
              </div>
            </section>
            <section className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
              <h3 className="text-sm font-semibold text-slate-200">Slowest routes by p95</h3>
              <div className="mt-3 space-y-2">
                {summary.slow_routes.slice(0, 8).map((item) => (
                  <div key={`${item.method}-${item.route}`} className="rounded-lg bg-slate-900/70 px-3 py-2 text-xs">
                    <div className="flex justify-between gap-3"><code className="truncate text-cyan-300">{item.method} {item.route}</code><span className="whitespace-nowrap text-amber-300">{duration(item.p95_ms)}</span></div>
                    <div className="mt-1 text-slate-600">{number(item.calls)} calls · {duration(item.sql_time_ms)} SQL · {duration(item.non_sql_time_ms)} non-SQL · {number(item.errors)} HTTP errors</div>
                  </div>
                ))}
              </div>
            </section>
          </div>
          {summary.recent_errors.length > 0 && (
            <section className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
              <h3 className="text-sm font-semibold text-amber-200">Recent non-success responses</h3>
              <div className="mt-3 overflow-x-auto"><table className="w-full text-xs"><thead className="text-left text-slate-600"><tr><th className="py-2">Time</th><th>Channel</th><th>Request</th><th>Status</th><th>Duration</th></tr></thead><tbody className="divide-y divide-slate-800">{summary.recent_errors.map((item) => <tr key={item.request_id}><td className="py-2 text-slate-500">{date(item.started_at)}</td><td>{item.channel}</td><td><button className="font-mono text-cyan-300" onClick={() => openRequest(item.request_id)}>{item.method} {item.path}</button></td><td className="text-red-300">{item.status_code}</td><td>{duration(item.duration_ms)}</td></tr>)}</tbody></table></div>
            </section>
          )}
        </div>
      )}

      {tab === 'requests' && (
        <div className="space-y-4">
          <div className="grid gap-2 rounded-xl border border-slate-800 bg-slate-950/40 p-3 md:grid-cols-6">
            <input value={requestFilters.path} onChange={(e) => setRequestFilters({ ...requestFilters, path: e.target.value })} placeholder="Path contains…" className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs" />
            <input value={requestFilters.principal} onChange={(e) => setRequestFilters({ ...requestFilters, principal: e.target.value })} placeholder="User or API key…" className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs" />
            <select value={requestFilters.channel} onChange={(e) => setRequestFilters({ ...requestFilters, channel: e.target.value })} className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs"><option value="">All channels</option><option value="api">API/UI</option><option value="mcp">MCP</option><option value="http">HTTP</option></select>
            <select value={requestFilters.status} onChange={(e) => setRequestFilters({ ...requestFilters, status: e.target.value })} className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs"><option value="">All statuses</option><option value="success">Success</option><option value="server_errors">Server errors (5xx/exceptions)</option><option value="client_rejections">Client rejections (4xx)</option><option value="errors">All non-success</option></select>
            <input type="number" value={requestFilters.minDuration} onChange={(e) => setRequestFilters({ ...requestFilters, minDuration: e.target.value })} placeholder="Minimum ms" className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs" />
            <button onClick={() => requestOffset ? setRequestOffset(0) : load('requests')} className="inline-flex items-center justify-center gap-2 rounded-lg bg-cyan-600 px-3 py-2 text-xs font-medium hover:bg-cyan-500"><Search className="h-4 w-4" /> Apply ({number(requestTotal)})</button>
          </div>
          <div className="overflow-x-auto rounded-xl border border-slate-800"><table className="w-full min-w-[1150px] text-xs"><thead className="bg-slate-800/50 text-left uppercase text-slate-600"><tr><th className="px-3 py-3">Time</th><th>Channel / principal</th><th>Request / tool</th><th>Status</th><th>Duration</th><th>SQL</th><th>Bytes</th></tr></thead><tbody className="divide-y divide-slate-800">{requests.map((item) => <tr key={item.request_id} className="cursor-pointer hover:bg-slate-800/30" onClick={() => openRequest(item.request_id)}><td className="px-3 py-3 text-slate-500">{date(item.started_at)}</td><td><div className="text-slate-300">{item.channel}</div><div className="max-w-[180px] truncate text-slate-600">{item.principal_name || item.principal_type || 'unattributed'}</div></td><td><code className="text-cyan-300">{item.method} {item.path}</code>{item.operation_names?.length > 0 && <div className="mt-1 text-purple-300">{item.operation_names.join(', ')}</div>}</td><td><span className={`rounded px-2 py-1 ${statusTone(item.status_code)}`}>{item.status_code}</span></td><td className={item.duration_ms >= (summary?.slow_request_ms || 1000) ? 'text-amber-300' : 'text-slate-400'}>{duration(item.duration_ms)}</td><td><div>{number(item.sql_count)} calls</div><div className="text-slate-600">{duration(item.sql_duration_ms)}</div></td><td className="text-slate-500">{bytes(item.request_bytes)} → {bytes(item.response_bytes)}</td></tr>)}</tbody></table>{!requests.length && <Empty>No matching requests.</Empty>}</div>
          <Pager offset={requestOffset} total={requestTotal} onChange={setRequestOffset} />
        </div>
      )}

      {tab === 'sql' && (
        <div className="space-y-4">
          <div className="grid gap-2 rounded-xl border border-slate-800 bg-slate-950/40 p-3 md:grid-cols-6">
            <select value={sqlFilters.database} onChange={(e) => setSqlFilters({ ...sqlFilters, database: e.target.value })} className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs"><option value="">Both databases</option><option value="cortellis">Cortellis</option><option value="edgar">EDGAR</option></select>
            <input value={sqlFilters.search} onChange={(e) => setSqlFilters({ ...sqlFilters, search: e.target.value })} placeholder="Table, SQL, or hash…" className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs" />
            <select value={sqlFilters.sort} onChange={(e) => setSqlFilters({ ...sqlFilters, sort: e.target.value })} className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs"><option value="total">Total time</option><option value="average">Average time</option><option value="maximum">Maximum time</option><option value="calls">Call count</option><option value="errors">Errors</option></select>
            <input type="number" value={sqlFilters.minDuration} onChange={(e) => setSqlFilters({ ...sqlFilters, minDuration: e.target.value })} placeholder="Minimum ms" className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs" />
            <label className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-400"><input type="checkbox" checked={sqlFilters.errorsOnly} onChange={(e) => setSqlFilters({ ...sqlFilters, errorsOnly: e.target.checked })} /> Errors only</label>
            <button onClick={() => sqlOffset ? setSqlOffset(0) : load('sql')} className="inline-flex items-center justify-center gap-2 rounded-lg bg-cyan-600 px-3 py-2 text-xs font-medium hover:bg-cyan-500"><Search className="h-4 w-4" /> Apply ({number(sqlTotal)})</button>
          </div>
          <div className="overflow-x-auto rounded-xl border border-slate-800"><table className="w-full min-w-[1200px] text-xs"><thead className="bg-slate-800/50 text-left uppercase text-slate-600"><tr><th className="px-3 py-3">Query shape</th><th>DB / tables</th><th>Calls</th><th>Total</th><th>Average / p95</th><th>Max</th><th>Rows / errors</th></tr></thead><tbody className="divide-y divide-slate-800">{sql.map((item) => <tr key={`${item.database_name}-${item.fingerprint}`} className="align-top"><td className="max-w-[480px] px-3 py-3"><button className="flex w-full items-start gap-2 text-left" onClick={() => setExpandedSql(expandedSql === item.fingerprint ? null : item.fingerprint)}>{expandedSql === item.fingerprint ? <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0" />}<span><code className={`${item.errors ? 'text-red-300' : 'text-cyan-300'} ${expandedSql === item.fingerprint ? 'whitespace-pre-wrap break-all' : 'line-clamp-2'}`}>{item.normalized_sql || `SQL text disabled · ${item.fingerprint.slice(0, 16)}`}</code><span className="mt-1 block font-mono text-[10px] text-slate-700">{item.fingerprint}</span></span></button></td><td><div className="text-slate-300">{item.database_name} · {item.statement_type}</div><div className="max-w-[220px] truncate text-slate-600">{item.table_names?.filter(Boolean).join(', ') || '—'}</div></td><td>{number(item.calls)}</td><td className="text-amber-300">{duration(item.total_ms)}</td><td>{duration(item.average_ms)} / {duration(item.p95_ms)}</td><td>{duration(item.maximum_ms)}</td><td><div>{number(item.rows)} rows</div><div className={item.errors ? 'text-red-300' : 'text-slate-600'}>{number(item.errors)} errors</div></td></tr>)}</tbody></table>{!sql.length && <Empty>No matching SQL spans.</Empty>}</div>
          <Pager offset={sqlOffset} total={sqlTotal} onChange={setSqlOffset} />
        </div>
      )}

      {tab === 'jobs' && (
        <div className="space-y-4">
          <div className="grid gap-2 rounded-xl border border-slate-800 bg-slate-950/40 p-3 md:grid-cols-[1fr_180px_auto]"><input value={jobFilter} onChange={(e) => setJobFilter(e.target.value)} placeholder="Task name contains…" className="min-w-0 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs" /><select value={jobStatus} onChange={(e) => setJobStatus(e.target.value)} className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs"><option value="">All statuses</option><option value="SUCCESS">Success</option><option value="FAILURE">Failure</option><option value="PARTIAL">Partial</option></select><button onClick={() => jobOffset ? setJobOffset(0) : load('jobs')} className="rounded-lg bg-cyan-600 px-4 py-2 text-xs">Apply ({number(jobTotal)})</button></div>
          <div className="overflow-x-auto rounded-xl border border-slate-800"><table className="w-full min-w-[1000px] text-xs"><thead className="bg-slate-800/50 text-left uppercase text-slate-600"><tr><th className="px-3 py-3">Started</th><th>Task</th><th>Status</th><th>Runtime</th><th>SQL</th><th>Queue / worker</th><th>Retries</th></tr></thead><tbody className="divide-y divide-slate-800">{jobs.map((item) => <tr key={item.task_id} className="cursor-pointer hover:bg-slate-800/30" onClick={() => openJob(item.task_id)}><td className="px-3 py-3 text-slate-500">{date(item.started_at)}</td><td><div className="max-w-[340px] truncate text-cyan-300">{item.task_name}</div><code className="text-[10px] text-slate-700">{item.task_id}</code></td><td className={String(item.status).toUpperCase() === 'SUCCESS' ? 'text-emerald-300' : 'text-red-300'}>{item.status}</td><td>{duration(item.duration_ms)}</td><td>{number(item.sql_count)} · {duration(item.sql_duration_ms)}</td><td><div>{item.queue || '—'}</div><div className="text-slate-600">{item.worker || '—'}</div></td><td>{number(item.retries)}</td></tr>)}</tbody></table>{!jobs.length && <Empty>No job telemetry yet. New worker tasks appear after deployment.</Empty>}</div>
          <Pager offset={jobOffset} total={jobTotal} onChange={setJobOffset} />
        </div>
      )}

      {tab === 'databases' && databases && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex gap-2">{databases.databases.map((database: any) => <button key={database.name} onClick={() => setSelectedDatabase(database.name)} className={`rounded-lg border px-4 py-2 text-xs ${selectedDatabase === database.name ? 'border-cyan-500 bg-cyan-500/10 text-cyan-300' : 'border-slate-700 text-slate-500'}`}>{database.name}</button>)}</div><button onClick={snapshot} className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300"><Clock3 className="h-4 w-4" /> Capture schema snapshot</button></div>
          {activeDatabase?.error ? <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-300">{activeDatabase.name}: {activeDatabase.error}</div> : activeDatabase && <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5"><MetricCard label="Database size" value={bytes(activeDatabase.overview.database_bytes)} /><MetricCard label="Connections" value={number(activeDatabase.connections.total)} detail={`${number(activeDatabase.connections.active)} active · ${number(activeDatabase.connections.waiting)} waiting`} warning={activeDatabase.connections.waiting > 0} /><MetricCard label="Cache hit since reset" value={`${(Number(activeDatabase.overview.cache_hit_ratio || 0) * 100).toFixed(2)}%`} detail={`Stats reset ${date(activeDatabase.overview.stats_reset)}`} /><MetricCard label="Deadlocks since reset" value={number(activeDatabase.overview.deadlocks)} detail={`Stats reset ${date(activeDatabase.overview.stats_reset)}`} warning={activeDatabase.overview.deadlocks > 0} /><MetricCard label="pg_stat_statements" value={activeDatabase.pg_stat_statements.available ? 'Active' : 'Unavailable'} detail={activeDatabase.settings.track_io_timing === 'on' ? 'I/O timing active' : 'I/O timing disabled'} warning={!activeDatabase.pg_stat_statements.available} /></div>
            {activeDatabase.recommendations?.length > 0 && <section className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4"><h3 className="text-sm font-semibold text-amber-200">Review opportunities</h3><div className="mt-3 grid gap-2 md:grid-cols-2">{activeDatabase.recommendations.slice(0, 12).map((item: any, index: number) => <div key={`${item.object}-${index}`} className="rounded-lg bg-slate-950/60 p-3 text-xs"><div className="font-mono text-amber-300">{item.object}</div><div className="mt-1 text-slate-500">{item.detail}</div></div>)}</div></section>}
            <section className="rounded-xl border border-slate-800"><div className="border-b border-slate-800 px-4 py-3 text-sm font-semibold text-slate-200">Largest tables and scan behavior</div><div className="max-h-[520px] overflow-auto"><table className="w-full min-w-[1000px] text-xs"><thead className="sticky top-0 bg-slate-900 text-left text-slate-600"><tr><th className="px-3 py-2">Table</th><th>Size</th><th>Live / dead rows</th><th>Sequential scans</th><th>Index scans</th><th>Last analyze</th></tr></thead><tbody className="divide-y divide-slate-800">{activeDatabase.tables.map((item: any) => <tr key={`${item.schema_name}.${item.table_name}`}><td className="px-3 py-2 font-mono text-cyan-300">{item.schema_name}.{item.table_name}</td><td>{bytes(item.total_bytes)} <span className="text-slate-700">({bytes(item.index_bytes)} idx)</span></td><td>{number(item.n_live_tup)} / <span className={item.n_dead_tup > item.n_live_tup * .2 ? 'text-amber-300' : 'text-slate-600'}>{number(item.n_dead_tup)}</span></td><td>{number(item.seq_scan)} · {number(item.seq_tup_read)} rows</td><td>{number(item.idx_scan)}</td><td className="text-slate-600">{date(item.last_autoanalyze || item.last_analyze)}</td></tr>)}</tbody></table></div></section>
            {activeDatabase.active_queries?.length > 0 && <section className="rounded-xl border border-slate-800"><div className="border-b border-slate-800 px-4 py-3 text-sm font-semibold text-slate-200">Active database work</div><div className="max-h-[320px] overflow-auto"><table className="w-full min-w-[1000px] text-xs"><thead className="sticky top-0 bg-slate-900 text-left text-slate-600"><tr><th className="px-3 py-2">Runtime</th><th>User / application</th><th>State / wait</th><th>Query shape</th></tr></thead><tbody className="divide-y divide-slate-800">{activeDatabase.active_queries.map((item: any) => <tr key={item.pid}><td className="px-3 py-2 text-amber-300">{duration(item.duration_ms)}</td><td><div>{item.usename}</div><div className="text-slate-600">{item.application_name || '—'}</div></td><td><div>{item.state}</div><div className="text-slate-600">{item.wait_event_type || '—'} {item.wait_event || ''}</div></td><td className="max-w-[620px]"><code className="line-clamp-3 text-cyan-300">{item.normalized_sql}</code></td></tr>)}</tbody></table></div></section>}
            <section className="rounded-xl border border-slate-800"><div className="border-b border-slate-800 px-4 py-3 text-sm font-semibold text-slate-200">Largest indexes</div><div className="max-h-[360px] overflow-auto"><table className="w-full min-w-[1000px] text-xs"><thead className="sticky top-0 bg-slate-900 text-left text-slate-600"><tr><th className="px-3 py-2">Index</th><th>Table</th><th>Size</th><th>Scans</th><th>Definition</th></tr></thead><tbody className="divide-y divide-slate-800">{activeDatabase.indexes.slice(0, 100).map((item: any) => <tr key={`${item.schema_name}.${item.index_name}`}><td className="px-3 py-2 font-mono text-cyan-300">{item.index_name}</td><td>{item.schema_name}.{item.table_name}</td><td>{bytes(item.index_bytes)}</td><td className={item.idx_scan === 0 && !item.indisunique ? 'text-amber-300' : ''}>{number(item.idx_scan)}</td><td className="max-w-[520px]"><code className="line-clamp-2 text-slate-500">{item.definition}</code></td></tr>)}</tbody></table></div></section>
            <section className="rounded-xl border border-slate-800"><div className="border-b border-slate-800 px-4 py-3 text-sm font-semibold text-slate-200">PostgreSQL aggregate query statistics</div><div className="max-h-[420px] overflow-auto"><table className="w-full min-w-[1050px] text-xs"><thead className="sticky top-0 bg-slate-900 text-left text-slate-600"><tr><th className="px-3 py-2">Query shape</th><th>Calls</th><th>Total</th><th>Mean</th><th>Rows</th><th>Blocks hit/read</th></tr></thead><tbody className="divide-y divide-slate-800">{activeDatabase.pg_stat_statements.items.map((item: any) => <tr key={item.fingerprint}><td className="max-w-[600px] px-3 py-2"><code className="line-clamp-2 text-cyan-300">{item.normalized_sql}</code></td><td>{number(item.calls)}</td><td>{duration(item.total_exec_time)}</td><td>{duration(item.mean_exec_time)}</td><td>{number(item.rows)}</td><td>{number(item.shared_blks_hit)} / {number(item.shared_blks_read)}</td></tr>)}</tbody></table>{!activeDatabase.pg_stat_statements.available && <Empty>pg_stat_statements is not active for this database.</Empty>}</div></section>
            <section className="rounded-xl border border-slate-800"><div className="border-b border-slate-800 px-4 py-3 text-sm font-semibold text-slate-200">Schema growth history</div><div className="max-h-[300px] overflow-auto"><table className="w-full text-xs"><thead className="sticky top-0 bg-slate-900 text-left text-slate-600"><tr><th className="px-3 py-2">Captured</th><th>Database</th><th>Size</th><th>Tables</th><th>Indexes</th></tr></thead><tbody className="divide-y divide-slate-800">{(databases.schema_history || []).filter((item: any) => item.database_name === selectedDatabase).slice().reverse().map((item: any) => <tr key={item.id}><td className="px-3 py-2 text-slate-500">{date(item.captured_at)}</td><td>{item.database_name}</td><td>{bytes(item.database_bytes)}</td><td>{number(item.table_count)}</td><td>{number(item.index_count)}</td></tr>)}</tbody></table>{!(databases.schema_history || []).some((item: any) => item.database_name === selectedDatabase) && <Empty>No snapshots captured yet.</Empty>}</div></section>
          </>}
        </div>
      )}

      {tab === 'settings' && settings && (
        <div className="space-y-4">
          <section className="rounded-xl border border-slate-800 bg-slate-950/40 p-5"><h3 className="text-sm font-semibold text-slate-200">Capture and privacy</h3><p className="mt-1 text-xs text-slate-600">Headers containing credentials and SQL parameter values are never stored. Payload capture is bounded and recursively redacts secret-like fields.</p><div className="mt-4 grid gap-3 md:grid-cols-3">{[
            ['enabled', 'Enable durable telemetry', 'Capture new requests, jobs, and SQL spans.'],
            ['capture_request_payloads', 'Retain sanitized JSON', 'Keep bounded request filters/prompts after redaction.'],
            ['retain_normalized_sql', 'Retain normalized SQL', 'Store value-free SQL shapes, not parameters.'],
          ].map(([key, label, detail]) => <label key={key} className="flex cursor-pointer items-start gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-3"><input type="checkbox" checked={Boolean((settings as any)[key])} onChange={(event) => setSettings({ ...settings, [key]: event.target.checked })} className="mt-1" /><span><span className="block text-sm text-slate-300">{label}</span><span className="mt-1 block text-xs text-slate-600">{detail}</span></span></label>)}</div></section>
          <section className="rounded-xl border border-slate-800 bg-slate-950/40 p-5"><h3 className="text-sm font-semibold text-slate-200">Thresholds and retention</h3><div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[
            ['sql_min_duration_ms', 'Minimum SQL duration (ms)', 0, 60000], ['slow_sql_ms', 'Slow SQL threshold (ms)', 1, 600000], ['slow_request_ms', 'Slow request threshold (ms)', 1, 600000], ['max_sql_spans_per_operation', 'SQL spans per operation', 1, 5000], ['payload_max_bytes', 'Maximum payload bytes', 0, 1000000], ['retention_days', 'Retention days', 1, 3650],
          ].map(([key, label, min, max]) => <label key={String(key)} className="text-xs text-slate-500">{label}<input type="number" min={Number(min)} max={Number(max)} value={Number((settings as any)[key])} onChange={(event) => setSettings({ ...settings, [key]: Number(event.target.value) })} className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200" /></label>)}</div><div className="mt-5 flex flex-wrap justify-between gap-3 border-t border-slate-800 pt-4"><button onClick={purge} className="inline-flex items-center gap-2 rounded-lg border border-red-500/30 px-3 py-2 text-xs text-red-300 hover:bg-red-500/10"><Trash2 className="h-4 w-4" /> Purge expired now</button><button onClick={saveSettings} disabled={loading} className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-4 py-2 text-xs font-medium hover:bg-cyan-500 disabled:opacity-50"><Save className="h-4 w-4" /> Save telemetry policy</button></div></section>
        </div>
      )}

      {(requestDetail || jobDetail) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={() => { setRequestDetail(null); setJobDetail(null); }}>
          <div className="max-h-[92vh] w-full max-w-6xl overflow-auto rounded-xl border border-slate-700 bg-slate-950 p-5" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-center justify-between"><h3 className="text-lg font-semibold text-slate-100">{requestDetail ? 'Request trace' : 'Job trace'}</h3><button onClick={() => { setRequestDetail(null); setJobDetail(null); }}><X className="h-5 w-5 text-slate-500" /></button></div>
            {requestDetail && <div className="mt-4 space-y-5"><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><MetricCard label="Request" value={`${requestDetail.request.method} ${requestDetail.request.status_code}`} detail={requestDetail.request.path} /><MetricCard label="Duration" value={duration(requestDetail.request.duration_ms)} detail={date(requestDetail.request.started_at)} /><MetricCard label="Principal" value={requestDetail.request.principal_name || 'Unattributed'} detail={`${requestDetail.request.channel} · ${requestDetail.request.principal_type || 'unknown'}`} /><MetricCard label="SQL" value={`${number(requestDetail.request.sql_count)} calls`} detail={duration(requestDetail.request.sql_duration_ms)} /></div><section><h4 className="mb-2 text-sm font-semibold text-slate-300">Sanitized request metadata</h4><pre className="max-h-72 overflow-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-400">{JSON.stringify(requestDetail.request.request_metadata, null, 2)}</pre></section><SQLSpanTable items={requestDetail.sql} slowMs={summary?.slow_sql_ms || 250} />{requestDetail.child_requests?.length > 0 && <section><h4 className="mb-2 text-sm font-semibold text-slate-300">Child requests (MCP → governed REST)</h4><div className="space-y-2">{requestDetail.child_requests.map((child: any) => <button key={child.request_id} onClick={() => openRequest(child.request_id)} className="flex w-full justify-between rounded-lg bg-slate-900 p-3 text-left text-xs"><code className="text-cyan-300">{child.method} {child.path}</code><span>{duration(child.duration_ms)} · {child.sql_count} SQL</span></button>)}</div></section>}</div>}
            {jobDetail && <div className="mt-4 space-y-5"><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><MetricCard label="Task" value={jobDetail.job.status} detail={jobDetail.job.task_name} /><MetricCard label="Runtime" value={duration(jobDetail.job.duration_ms)} detail={date(jobDetail.job.started_at)} /><MetricCard label="Queue" value={jobDetail.job.queue || '—'} detail={jobDetail.job.worker} /><MetricCard label="SQL" value={`${number(jobDetail.job.sql_count)} calls`} detail={duration(jobDetail.job.sql_duration_ms)} /></div><div className="grid gap-4 lg:grid-cols-2"><section><h4 className="mb-2 text-sm font-semibold text-slate-300">Sanitized arguments</h4><pre className="max-h-64 overflow-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-400">{JSON.stringify(jobDetail.job.arguments, null, 2)}</pre></section><section><h4 className="mb-2 text-sm font-semibold text-slate-300">Result/error</h4><pre className="max-h-64 overflow-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-400">{JSON.stringify(jobDetail.job.result_summary || { error_type: jobDetail.job.error_type, error_message: jobDetail.job.error_message }, null, 2)}</pre></section></div><SQLSpanTable items={jobDetail.sql} slowMs={summary?.slow_sql_ms || 250} /></div>}
          </div>
        </div>
      )}
    </div>
  );
}

function SQLSpanTable({ items, slowMs = 250 }: { items: any[]; slowMs?: number }) {
  return <section><h4 className="mb-2 text-sm font-semibold text-slate-300">SQL spans ({number(items.length)})</h4><div className="overflow-x-auto rounded-lg border border-slate-800"><table className="w-full min-w-[900px] text-xs"><thead className="bg-slate-900 text-left text-slate-600"><tr><th className="px-3 py-2">DB</th><th>Duration</th><th>Rows</th><th>Query shape</th></tr></thead><tbody className="divide-y divide-slate-800">{items.map((item) => <tr key={item.id}><td className="px-3 py-2">{item.database_name}</td><td className={item.duration_ms >= slowMs ? 'text-amber-300' : ''}>{duration(item.duration_ms)}</td><td>{number(item.row_count)}</td><td className="max-w-[680px]"><code className={item.success ? 'text-cyan-300' : 'text-red-300'}>{item.normalized_sql || item.fingerprint}</code></td></tr>)}</tbody></table>{!items.length && <Empty>No SQL spans retained for this operation.</Empty>}</div></section>;
}

function Pager({ offset, total, onChange }: {
  offset: number;
  total: number;
  onChange: (offset: number) => void;
}) {
  if (total <= PAGE_SIZE) return null;
  const first = Math.min(offset + 1, total);
  const last = Math.min(offset + PAGE_SIZE, total);
  return <div className="flex items-center justify-between text-xs text-slate-500"><span>Showing {number(first)}–{number(last)} of {number(total)}</span><div className="flex gap-2"><button disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - PAGE_SIZE))} className="rounded-lg border border-slate-700 px-3 py-2 disabled:opacity-40">Previous</button><button disabled={offset + PAGE_SIZE >= total} onClick={() => onChange(offset + PAGE_SIZE)} className="rounded-lg border border-slate-700 px-3 py-2 disabled:opacity-40">Next</button></div></div>;
}

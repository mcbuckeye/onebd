import { useEffect, useState } from 'react';
import {
  Activity,
  Building2,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Database,
  Download,
  ExternalLink,
  FlaskConical,
  Loader2,
  Search,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import api from '../lib/api';
import { useToast } from '../contexts/ToastContext';

interface EntityLink {
  id: number;
  name: string;
  match_method: string;
  confidence: number;
}

interface CatalystEvent {
  nct_id: string;
  brief_title: string;
  overall_status: string;
  phases: string[];
  enrollment: number | null;
  catalyst_date: string;
  catalyst_date_raw: string;
  catalyst_date_type: string | null;
  lead_sponsor_name: string | null;
  conditions: string[];
  last_update_posted: string | null;
  source_url: string;
  linked_companies: EntityLink[];
  linked_drugs: EntityLink[];
  linked_indications: EntityLink[];
}

interface CalendarResponse {
  total: number;
  limit: number;
  offset: number;
  summary: {
    estimated_dates: number;
    phase_3: number;
    linked_to_company: number;
    linked_to_drug: number;
  };
  events: CatalystEvent[];
  date_from: string;
  date_to: string;
  methodology: string;
}

const PAGE_SIZE = 50;
const ACTIVE_STATUSES = [
  'RECRUITING',
  'NOT_YET_RECRUITING',
  'ACTIVE_NOT_RECRUITING',
  'ENROLLING_BY_INVITATION',
];
const PHASES = ['EARLY_PHASE1', 'PHASE1', 'PHASE2', 'PHASE3', 'PHASE4'];

function isoDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function offsetDate(days: number): string {
  const value = new Date();
  value.setDate(value.getDate() + days);
  return isoDate(value);
}

function displayLabel(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (char: string) => char.toUpperCase());
}

function formatDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function displayCatalystDate(event: CatalystEvent): string {
  if (/^\d{4}$/.test(event.catalyst_date_raw)) {
    return `${event.catalyst_date_raw} (year only)`;
  }
  if (/^\d{4}-\d{2}$/.test(event.catalyst_date_raw)) {
    return new Date(`${event.catalyst_date_raw}-01T00:00:00`).toLocaleDateString(undefined, {
      month: 'long',
      year: 'numeric',
    });
  }
  return formatDate(event.catalyst_date);
}

function EntityLinks({ items, type }: { items: EntityLink[]; type: 'company' | 'drug' | 'indication' }) {
  if (!items.length) return <span className="text-slate-600">No exact link</span>;
  const route = type === 'company' ? 'company' : type === 'drug' ? 'drug' : null;
  return (
    <div className="flex flex-wrap gap-1">
      {items.slice(0, 3).map(item => route ? (
        <Link
          key={`${type}-${item.id}`}
          to={`/${route}/${item.id}`}
          className="rounded bg-blue-500/10 px-1.5 py-0.5 text-xs text-blue-300 hover:bg-blue-500/20"
          title={`Exact normalized link (${Math.round(item.confidence * 100)}% confidence)`}
        >
          {item.name}
        </Link>
      ) : (
        <span key={`${type}-${item.id}`} className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-300">
          {item.name}
        </span>
      ))}
      {items.length > 3 && <span className="text-xs text-slate-500">+{items.length - 3}</span>}
    </div>
  );
}

export default function CatalystCalendarPage() {
  const toast = useToast();
  const [dateFrom, setDateFrom] = useState(offsetDate(0));
  const [dateTo, setDateTo] = useState(offsetDate(365));
  const [status, setStatus] = useState('');
  const [phase, setPhase] = useState('');
  const [query, setQuery] = useState('');
  const [includeInactive, setIncludeInactive] = useState(false);
  const [offset, setOffset] = useState(0);
  const [calendar, setCalendar] = useState<CalendarResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState<'csv' | 'ics' | null>(null);
  const [error, setError] = useState('');

  const params = (includePagination = true) => ({
    date_from: dateFrom,
    date_to: dateTo,
    ...(status ? { status } : {}),
    ...(phase ? { phase } : {}),
    ...(query.trim().length >= 2 ? { q: query.trim() } : {}),
    ...(includeInactive ? { include_inactive: true } : {}),
    ...(includePagination ? { limit: PAGE_SIZE, offset } : {}),
  });

  useEffect(() => {
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setError('');
      try {
        const response = await api.get<CalendarResponse>('/clinical-trials/calendar', {
          params: params(),
        });
        setCalendar(response.data);
      } catch (requestError) {
        console.error('Catalyst calendar load failed:', requestError);
        setError('The catalyst calendar could not be loaded.');
      } finally {
        setLoading(false);
      }
    }, query ? 300 : 0);
    return () => window.clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateFrom, dateTo, status, phase, query, includeInactive, offset]);

  const updateFilter = (setter: (value: string) => void, value: string) => {
    setter(value);
    setOffset(0);
  };

  const setRange = (days: number) => {
    setDateFrom(offsetDate(0));
    setDateTo(offsetDate(days));
    setOffset(0);
  };

  const exportCalendar = async (format: 'csv' | 'ics') => {
    setExporting(format);
    try {
      const response = await api.get(`/clinical-trials/calendar.${format}`, {
        params: params(false),
        responseType: 'blob',
      });
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `clinical-trial-catalysts-${dateFrom}-${dateTo}.${format}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      toast.success(format === 'csv' ? 'CSV export created' : 'Calendar export created');
    } catch (requestError) {
      console.error('Catalyst calendar export failed:', requestError);
      toast.error('Export failed. Narrow the date range or filters and try again.');
    } finally {
      setExporting(null);
    }
  };

  const pageStart = calendar?.total ? offset + 1 : 0;
  const pageEnd = calendar ? Math.min(offset + PAGE_SIZE, calendar.total) : 0;

  return (
    <div className="mx-auto max-w-[1600px] p-4 sm:p-6">
      <div className="mb-6 flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <div className="flex items-center gap-3">
            <CalendarDays className="h-7 w-7 text-blue-400" />
            <h1 className="text-2xl font-bold text-slate-100">Catalyst Calendar</h1>
          </div>
          <p className="mt-2 max-w-3xl text-sm text-slate-400">
            Clinical trial primary-completion dates with retained source precision and exact normalized links to OneBD companies, drugs, and indications.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => exportCalendar('csv')}
            disabled={exporting !== null || loading}
            className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-50"
          >
            {exporting === 'csv' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            CSV
          </button>
          <button
            onClick={() => exportCalendar('ics')}
            disabled={exporting !== null || loading}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {exporting === 'ics' ? <Loader2 className="h-4 w-4 animate-spin" /> : <CalendarDays className="h-4 w-4" />}
            Add to calendar
          </button>
        </div>
      </div>

      <div className="mb-5 rounded-xl border border-slate-800 bg-slate-900 p-4">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
          <label className="text-xs font-medium text-slate-400">
            From
            <input
              type="date"
              value={dateFrom}
              onChange={event => updateFilter(setDateFrom, event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
            />
          </label>
          <label className="text-xs font-medium text-slate-400">
            To
            <input
              type="date"
              value={dateTo}
              onChange={event => updateFilter(setDateTo, event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
            />
          </label>
          <label className="text-xs font-medium text-slate-400">
            Status
            <select
              value={status}
              onChange={event => updateFilter(setStatus, event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
            >
              <option value="">All active statuses</option>
              {ACTIVE_STATUSES.map(value => <option key={value} value={value}>{displayLabel(value)}</option>)}
              {includeInactive && <option value="COMPLETED">Completed</option>}
              {includeInactive && <option value="TERMINATED">Terminated</option>}
              {includeInactive && <option value="WITHDRAWN">Withdrawn</option>}
            </select>
          </label>
          <label className="text-xs font-medium text-slate-400">
            Phase
            <select
              value={phase}
              onChange={event => updateFilter(setPhase, event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
            >
              <option value="">All phases</option>
              {PHASES.map(value => <option key={value} value={value}>{displayLabel(value)}</option>)}
            </select>
          </label>
          <label className="text-xs font-medium text-slate-400 xl:col-span-2">
            Search trial, sponsor, drug, or condition
            <div className="relative mt-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
              <input
                value={query}
                onChange={event => updateFilter(setQuery, event.target.value)}
                placeholder="e.g. KRAS or NCT number"
                className="w-full rounded-lg border border-slate-700 bg-slate-800 py-2 pl-9 pr-3 text-sm text-slate-200 placeholder-slate-500"
              />
            </div>
          </label>
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-slate-800 pt-3">
          <div className="flex gap-2">
            {[90, 365, 730].map(days => (
              <button key={days} onClick={() => setRange(days)} className="rounded-md bg-slate-800 px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-700">
                {days === 90 ? '90 days' : `${days / 365} year${days > 365 ? 's' : ''}`}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-xs text-slate-400">
            <input
              type="checkbox"
              checked={includeInactive}
              onChange={event => { setIncludeInactive(event.target.checked); setStatus(''); setOffset(0); }}
              className="rounded border-slate-600 bg-slate-800 text-blue-600"
            />
            Include completed and stopped trials
          </label>
        </div>
      </div>

      {calendar && (
        <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[
            { label: 'Calendar events', value: calendar.total, icon: CalendarDays, color: 'text-blue-400' },
            { label: 'Phase 3', value: calendar.summary.phase_3, icon: Activity, color: 'text-purple-400' },
            { label: 'Exact company links', value: calendar.summary.linked_to_company, icon: Building2, color: 'text-emerald-400' },
            { label: 'Estimated dates', value: calendar.summary.estimated_dates, icon: Database, color: 'text-amber-400' },
          ].map(({ label, value, icon: Icon, color }) => (
            <div key={label} className="rounded-xl border border-slate-800 bg-slate-900 p-4">
              <div className="flex items-center justify-between">
                <span className="text-xs uppercase tracking-wide text-slate-500">{label}</span>
                <Icon className={`h-4 w-4 ${color}`} />
              </div>
              <div className="mt-2 text-2xl font-semibold text-slate-100">{value.toLocaleString()}</div>
            </div>
          ))}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900">
        {loading ? (
          <div className="flex min-h-80 items-center justify-center"><Loader2 className="h-7 w-7 animate-spin text-blue-400" /></div>
        ) : error ? (
          <div className="flex min-h-80 items-center justify-center text-sm text-red-400">{error}</div>
        ) : !calendar?.events.length ? (
          <div className="flex min-h-80 flex-col items-center justify-center gap-2 text-slate-500">
            <FlaskConical className="h-8 w-8" />
            <span className="text-sm">No primary-completion events match these filters.</span>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1200px] text-left text-sm">
              <thead className="border-b border-slate-800 bg-slate-900/90 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Trial</th>
                  <th className="px-4 py-3">Phase / status</th>
                  <th className="px-4 py-3">Exact-linked companies</th>
                  <th className="px-4 py-3">Exact-linked drugs</th>
                  <th className="px-4 py-3">Conditions</th>
                  <th className="px-4 py-3">Source</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {calendar.events.map(event => (
                  <tr key={event.nct_id} className="align-top hover:bg-slate-800/30">
                    <td className="whitespace-nowrap px-4 py-3">
                      <div className="font-medium text-slate-200">{displayCatalystDate(event)}</div>
                      <div className="mt-1 flex items-center gap-1 text-xs text-slate-500">
                        {event.catalyst_date_raw}
                        {event.catalyst_date_type && (
                          <span className={`rounded px-1 py-0.5 ${event.catalyst_date_type === 'ACTUAL' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-amber-500/10 text-amber-400'}`}>
                            {event.catalyst_date_type.toLowerCase()}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="max-w-sm px-4 py-3">
                      <div className="font-medium text-slate-200">{event.brief_title}</div>
                      <div className="mt-1 text-xs text-slate-500">{event.nct_id} · {event.lead_sponsor_name || 'Sponsor not reported'}</div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="text-slate-300">{event.phases.map(displayLabel).join(', ') || 'Not reported'}</div>
                      <div className="mt-1 text-xs text-slate-500">{displayLabel(event.overall_status)}</div>
                    </td>
                    <td className="px-4 py-3"><EntityLinks items={event.linked_companies} type="company" /></td>
                    <td className="px-4 py-3"><EntityLinks items={event.linked_drugs} type="drug" /></td>
                    <td className="max-w-xs px-4 py-3 text-xs text-slate-400">{event.conditions.slice(0, 3).join('; ') || 'Not reported'}</td>
                    <td className="px-4 py-3">
                      <a href={event.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300">
                        ClinicalTrials.gov <ExternalLink className="h-3 w-3" />
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {calendar && calendar.total > 0 && (
          <div className="flex items-center justify-between border-t border-slate-800 px-4 py-3 text-sm text-slate-400">
            <span>Showing {pageStart.toLocaleString()}–{pageEnd.toLocaleString()} of {calendar.total.toLocaleString()}</span>
            <div className="flex gap-2">
              <button
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                disabled={offset === 0 || loading}
                className="rounded-lg border border-slate-700 p-2 hover:bg-slate-800 disabled:opacity-40"
                aria-label="Previous page"
              ><ChevronLeft className="h-4 w-4" /></button>
              <button
                onClick={() => setOffset(offset + PAGE_SIZE)}
                disabled={offset + PAGE_SIZE >= calendar.total || loading}
                className="rounded-lg border border-slate-700 p-2 hover:bg-slate-800 disabled:opacity-40"
                aria-label="Next page"
              ><ChevronRight className="h-4 w-4" /></button>
            </div>
          </div>
        )}
      </div>

      {calendar && <p className="mt-3 text-xs leading-relaxed text-slate-500">Methodology: {calendar.methodology}</p>}
    </div>
  );
}

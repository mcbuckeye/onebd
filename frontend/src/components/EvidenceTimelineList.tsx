import {
  Activity,
  CalendarDays,
  ExternalLink,
  Link2,
  ShieldCheck,
} from 'lucide-react';
import { EvidenceTimelineEvent } from '../types';

const categoryStyle: Record<EvidenceTimelineEvent['category'], string> = {
  deal: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
  development: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30',
  regulatory: 'bg-purple-500/15 text-purple-300 border-purple-500/30',
  clinical_trial: 'bg-green-500/15 text-green-300 border-green-500/30',
  clinical_status: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
};

function CategoryIcon({ category }: { category: EvidenceTimelineEvent['category'] }) {
  if (category === 'regulatory') return <ShieldCheck className="h-4 w-4" />;
  if (category === 'clinical_trial' || category === 'clinical_status') {
    return <Activity className="h-4 w-4" />;
  }
  if (category === 'deal') return <Link2 className="h-4 w-4" />;
  return <CalendarDays className="h-4 w-4" />;
}

function formatDate(value?: string | null) {
  if (!value) return 'Date not reported';
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

function sourceLabel(source: string) {
  if (source === 'clinicaltrials.gov_api_v2') return 'ClinicalTrials.gov';
  if (source === 'cortellis_deals_api') return 'Cortellis Deals';
  return source;
}

export default function EvidenceTimelineList({
  events,
}: {
  events: EvidenceTimelineEvent[];
}) {
  return (
    <div className="space-y-3">
      {events.map((event, index) => (
        <article
          key={`${event.source}:${event.source_record_id}:${event.event_type}:${event.event_date}:${index}`}
          className="relative border-l-2 border-slate-700 pb-1 pl-4"
        >
          <span className="absolute -left-[7px] top-1.5 h-3 w-3 rounded-full border-2 border-slate-900 bg-slate-500" />
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-medium ${categoryStyle[event.category]}`}>
              <CategoryIcon category={event.category} />
              {event.event_type}
            </span>
            <time className="text-xs text-slate-500">{formatDate(event.event_date)}</time>
            {event.stage && (
              <span className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-400">
                {event.stage}
              </span>
            )}
          </div>
          {event.summary && (
            <p className="mt-2 text-sm leading-5 text-slate-300">{event.summary}</p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-slate-500">
            <span>{sourceLabel(event.source)}</span>
            {event.nct_id && event.source_url ? (
              <a
                href={event.source_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-blue-400 hover:text-blue-300"
              >
                {event.nct_id}
                <ExternalLink className="h-3 w-3" />
              </a>
            ) : event.nct_id ? (
              <span>{event.nct_id}</span>
            ) : null}
            {event.link_method === 'exact_nct_citation' && (
              <span className="text-green-400">Exact NCT citation</span>
            )}
          </div>
          {event.citation_evidence.length > 0 && (
            <details className="mt-2 rounded-lg bg-slate-950/60 px-3 py-2 text-xs">
              <summary className="cursor-pointer text-slate-400 hover:text-slate-300">
                Citation provenance ({event.citation_evidence.length})
              </summary>
              <div className="mt-2 space-y-2">
                {event.citation_evidence.map((evidence, evidenceIndex) => (
                  <div key={`${evidence.source_record_id}:${evidence.source_char_start}:${evidenceIndex}`}>
                    <p className="leading-5 text-slate-400">{evidence.source_excerpt}</p>
                    <p className="mt-1 font-mono text-[10px] text-slate-600">
                      Cortellis raw record {evidence.source_record_id} · chars {evidence.source_char_start}–{evidence.source_char_end} · SHA {evidence.source_sha256.slice(0, 12)}…
                    </p>
                  </div>
                ))}
              </div>
            </details>
          )}
        </article>
      ))}
    </div>
  );
}

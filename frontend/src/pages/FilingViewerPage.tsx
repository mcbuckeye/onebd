import { Fragment, useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowRight,
  Building2,
  CalendarDays,
  ExternalLink,
  FileSearch,
  FileText,
  Hash,
  ListTree,
} from 'lucide-react';
import api from '../lib/api';

interface FilingChunk {
  id: number;
  section: string | null;
  chunk_index: number;
  text: string;
  token_count: number | null;
}

interface FilingContent {
  id: number;
  doc_type: string | null;
  title: string | null;
  accession_no: string | null;
  published_at: string | null;
  filing_date: string | null;
  company_name: string;
  company_ticker: string | null;
  company_cik: string | null;
  source_url: string | null;
  chunks: FilingChunk[];
  focus_chunk_id: number | null;
  pagination: {
    page: number;
    page_size: number;
    total_chunks: number;
    total_pages: number;
  };
}

interface FilingSection {
  section: string | null;
  start_index: number;
  end_index: number;
  chunk_count: number;
  total_tokens: number | null;
}

interface RelatedDeals {
  total_related: number;
  edgar_extracted_deals: Array<{
    id: number;
    deal_type: string;
    announced_at: string | null;
    description: string | null;
    status: string;
  }>;
  cortellis_deals: Array<{
    id: number;
    title: string;
    agreement_type: string | null;
    status: string | null;
    date_start: string | null;
    total_value: number | null;
  }>;
}

const PAGE_SIZE = 12;

function formatDate(value: string | null) {
  if (!value) return 'Date unavailable';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value.slice(0, 10)
    : parsed.toLocaleDateString();
}

function HighlightedText({ text, query }: { text: string; query: string }) {
  const parts = useMemo(() => {
    const normalized = query.trim();
    if (normalized.length < 2) return [text];
    const escaped = normalized.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return text.split(new RegExp(`(${escaped})`, 'gi'));
  }, [query, text]);

  if (query.trim().length < 2) return <>{text}</>;
  return (
    <>
      {parts.map((part, index) => (
        part.toLowerCase() === query.trim().toLowerCase()
          ? <mark key={index} className="rounded bg-amber-300/30 px-0.5 text-amber-100">{part}</mark>
          : <Fragment key={index}>{part}</Fragment>
      ))}
    </>
  );
}

export default function FilingViewerPage() {
  const { filingId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialChunk = Number(searchParams.get('chunk')) || null;
  const [page, setPage] = useState(1);
  const [focusChunkId, setFocusChunkId] = useState<number | null>(initialChunk);
  const [highlight, setHighlight] = useState(searchParams.get('q') || '');
  const [content, setContent] = useState<FilingContent | null>(null);
  const [sections, setSections] = useState<FilingSection[]>([]);
  const [related, setRelated] = useState<RelatedDeals | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!filingId) return;
    Promise.allSettled([
      api.get(`/edgar/filings/${filingId}/sections`),
      api.get(`/edgar/filings/${filingId}/related-deals`),
    ]).then(([sectionResult, relatedResult]) => {
      if (sectionResult.status === 'fulfilled') {
        setSections(sectionResult.value.data.sections || []);
      }
      if (relatedResult.status === 'fulfilled') {
        setRelated(relatedResult.value.data);
      }
    });
  }, [filingId]);

  useEffect(() => {
    if (!filingId) return;
    setLoading(true);
    setError('');
    api.get(`/edgar/filings/${filingId}/content`, {
      params: {
        mode: 'chunks',
        page,
        page_size: PAGE_SIZE,
        ...(focusChunkId ? { chunk_id: focusChunkId } : {}),
      },
    }).then((response) => {
      const next = response.data as FilingContent;
      setContent(next);
      if (next.pagination.page !== page) setPage(next.pagination.page);
    }).catch((err) => {
      setError(err.response?.data?.detail || 'Failed to load this SEC filing');
    }).finally(() => setLoading(false));
  }, [filingId, focusChunkId, page]);

  const goToPage = (nextPage: number) => {
    setFocusChunkId(null);
    setPage(nextPage);
    setSearchParams((current) => {
      const updated = new URLSearchParams(current);
      updated.delete('chunk');
      return updated;
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const goToSection = (section: FilingSection) => {
    goToPage(Math.floor(section.start_index / PAGE_SIZE) + 1);
  };

  const updateHighlight = (value: string) => {
    setHighlight(value);
    setSearchParams((current) => {
      const updated = new URLSearchParams(current);
      if (value.trim()) updated.set('q', value);
      else updated.delete('q');
      return updated;
    });
  };

  if (error) {
    return (
      <div className="mx-auto max-w-4xl p-6">
        <Link to="/filings" className="mb-5 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-300">
          <ArrowLeft className="h-4 w-4" /> Back to filings
        </Link>
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-6 text-red-300">{error}</div>
      </div>
    );
  }

  if (!content && loading) {
    return <div className="p-6"><div className="h-40 animate-pulse rounded-xl bg-slate-900" /></div>;
  }
  if (!content) return null;

  const { pagination } = content;
  const startChunk = (pagination.page - 1) * pagination.page_size + 1;
  const endChunk = Math.min(
    pagination.total_chunks,
    startChunk + content.chunks.length - 1,
  );

  return (
    <div className="mx-auto max-w-[1600px] p-4 sm:p-6">
      <Link to="/filings" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-300">
        <ArrowLeft className="h-4 w-4" /> Back to filing search
      </Link>

      <header className="mb-5 rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="rounded bg-blue-500/15 px-2 py-1 text-xs font-semibold text-blue-300">
                {content.doc_type || 'SEC filing'}
              </span>
              {content.company_ticker && <span className="text-xs text-slate-500">{content.company_ticker}</span>}
            </div>
            <h1 className="truncate text-2xl font-bold text-slate-100">
              {content.title || `${content.doc_type || 'SEC'} filing`}
            </h1>
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-sm text-slate-400">
              <span className="inline-flex items-center gap-1.5"><Building2 className="h-4 w-4" />{content.company_name}</span>
              <span className="inline-flex items-center gap-1.5"><CalendarDays className="h-4 w-4" />{formatDate(content.filing_date || content.published_at)}</span>
              {content.accession_no && <span className="inline-flex items-center gap-1.5 font-mono text-xs"><Hash className="h-4 w-4" />{content.accession_no}</span>}
            </div>
          </div>
          {content.source_url && (
            <a href={content.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:border-blue-500 hover:text-blue-300">
              Open at SEC.gov <ExternalLink className="h-4 w-4" />
            </a>
          )}
        </div>
      </header>

      <div className="grid gap-5 xl:grid-cols-[240px_minmax(0,1fr)_280px]">
        <aside className="space-y-4">
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 xl:sticky xl:top-4">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-300">
              <ListTree className="h-4 w-4" /> Sections
            </h2>
            <div className="max-h-[65vh] space-y-1 overflow-y-auto pr-1">
              {sections.length ? sections.map((section, index) => (
                <button key={`${section.section}-${index}`} type="button" onClick={() => goToSection(section)} className="block w-full rounded px-2 py-2 text-left text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-200">
                  <span className="block truncate">{section.section || 'Unlabeled section'}</span>
                  <span className="text-[10px] text-slate-600">{section.chunk_count} chunks</span>
                </button>
              )) : <p className="text-xs text-slate-600">No section labels were detected.</p>}
            </div>
          </div>
        </aside>

        <main className="min-w-0">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900 p-3">
            <label className="relative min-w-[220px] flex-1">
              <FileSearch className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
              <input value={highlight} onChange={(event) => updateHighlight(event.target.value)} placeholder="Highlight text on this page" className="w-full rounded-lg border border-slate-700 bg-slate-800 py-2 pl-9 pr-3 text-sm text-slate-200 outline-none focus:border-blue-500" />
            </label>
            <span className="text-xs text-slate-500">Chunks {startChunk}–{endChunk} of {pagination.total_chunks}</span>
          </div>

          <div className={`space-y-3 transition-opacity ${loading ? 'opacity-50' : ''}`}>
            {content.chunks.map((chunk) => (
              <article key={chunk.id} className={`rounded-xl border bg-slate-950/70 p-5 ${chunk.id === content.focus_chunk_id ? 'border-amber-400/70 ring-1 ring-amber-400/30' : 'border-slate-800'}`}>
                <div className="mb-3 flex items-center justify-between gap-3 text-xs text-slate-500">
                  <span className="truncate">{chunk.section || 'Filing text'}</span>
                  <span className="shrink-0 font-mono">#{chunk.chunk_index + 1}</span>
                </div>
                <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-7 text-slate-300"><HighlightedText text={chunk.text} query={highlight} /></pre>
              </article>
            ))}
          </div>

          <Pagination page={pagination.page} totalPages={pagination.total_pages} onPage={goToPage} />
        </main>

        <aside>
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 xl:sticky xl:top-4">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-300">
              <FileText className="h-4 w-4" /> Related deal evidence
            </h2>
            {!related || related.total_related === 0 ? (
              <p className="text-xs leading-5 text-slate-500">No exact extracted deal or company/date-proximate Cortellis record is linked to this filing.</p>
            ) : (
              <div className="space-y-3">
                {related.cortellis_deals.map((deal) => (
                  <div key={`c-${deal.id}`} className="rounded-lg bg-slate-800/70 p-3">
                    <p className="text-xs font-medium text-slate-300">{deal.title}</p>
                    <p className="mt-1 text-[11px] text-slate-500">Cortellis #{deal.id} · {deal.date_start?.slice(0, 10) || 'No date'}</p>
                  </div>
                ))}
                {related.edgar_extracted_deals.map((deal) => (
                  <div key={`e-${deal.id}`} className="rounded-lg bg-slate-800/70 p-3">
                    <p className="text-xs font-medium text-slate-300">{deal.deal_type || 'Extracted deal'}</p>
                    {deal.description && <p className="mt-1 line-clamp-4 text-[11px] leading-4 text-slate-500">{deal.description}</p>}
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

function Pagination({ page, totalPages, onPage }: { page: number; totalPages: number; onPage: (page: number) => void }) {
  if (totalPages <= 1) return null;
  return (
    <div className="mt-5 flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900 p-3">
      <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)} className="inline-flex items-center gap-1 rounded px-3 py-2 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-30">
        <ArrowLeft className="h-4 w-4" /> Previous
      </button>
      <span className="text-xs text-slate-500">Page {page} of {totalPages}</span>
      <button type="button" disabled={page >= totalPages} onClick={() => onPage(page + 1)} className="inline-flex items-center gap-1 rounded px-3 py-2 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-30">
        Next <ArrowRight className="h-4 w-4" />
      </button>
    </div>
  );
}

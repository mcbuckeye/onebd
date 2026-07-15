import { useEffect, useState } from 'react';
import {
  CheckCircle2,
  ClipboardCheck,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import api from '../lib/api';
import { useAuth } from '../contexts/AuthContext';

interface ClauseCandidate {
  id: number;
  contract_id: number;
  deal_id: number;
  clause_type: 'royalty_rate' | 'milestone_payment' | 'upfront_payment';
  rate_min_pct: number | null;
  rate_max_pct: number | null;
  amount_min_millions: number | null;
  amount_max_millions: number | null;
  currency: string | null;
  is_tiered: boolean;
  confidence: number;
  source_text: string;
  source_line_start: number;
  source_line_end: number;
  source_hash: string;
}

interface ValidationStatus {
  parser_version: string;
  parse_coverage_pct: number;
  clauses_total: number;
  sample_replay_accuracy_pct: number;
  fresh_reviewed_accepted: number;
  fresh_reviewed_rejected: number;
  fresh_reviewed_clauses: number;
  fresh_review_precision_pct: number | null;
  technical_release_ready: boolean;
  governed_release_ready: boolean;
}

function clauseLabel(type: ClauseCandidate['clause_type']) {
  return {
    royalty_rate: 'Royalty rate',
    milestone_payment: 'Milestone payment',
    upfront_payment: 'Upfront payment',
  }[type];
}

function rangeLabel(minimum: number | null, maximum: number | null, suffix = '') {
  if (minimum === null && maximum === null) return 'Not captured';
  if (minimum === maximum || maximum === null) return `${minimum}${suffix}`;
  if (minimum === null) return `${maximum}${suffix}`;
  return `${minimum}–${maximum}${suffix}`;
}

function valueLabel(candidate: ClauseCandidate) {
  if (candidate.clause_type === 'royalty_rate') {
    return rangeLabel(candidate.rate_min_pct, candidate.rate_max_pct, '%');
  }
  const amount = rangeLabel(
    candidate.amount_min_millions,
    candidate.amount_max_millions,
    'M',
  );
  return `${candidate.currency ?? 'Currency unknown'} ${amount}`;
}

export default function ContractClauseReviewPanel() {
  const { user } = useAuth();
  const [candidates, setCandidates] = useState<ClauseCandidate[]>([]);
  const [validation, setValidation] = useState<ValidationStatus | null>(null);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [savingId, setSavingId] = useState<number | null>(null);
  const [error, setError] = useState('');

  const loadQueue = async () => {
    setIsLoading(true);
    setError('');
    try {
      const [validationResponse, queueResponse] = await Promise.all([
        api.get('/enrichment/contract-financial-clauses/validation?sample_per_type=5'),
        api.get('/enrichment/contract-financial-clauses/review-sample?limit=20'),
      ]);
      setValidation(
        validationResponse.data.contract_financial_clause_validation,
      );
      setCandidates(queueResponse.data.candidates);
      setNotes({});
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load the review queue');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadQueue();
  }, []);

  const review = async (
    candidate: ClauseCandidate,
    reviewStatus: 'accepted' | 'rejected',
  ) => {
    setSavingId(candidate.id);
    setError('');
    try {
      await api.patch(
        `/enrichment/contract-financial-clauses/${candidate.id}/review`,
        {
          review_status: reviewStatus,
          note: notes[candidate.id]?.trim() || null,
        },
      );
      setCandidates((current) =>
        current.filter((item) => item.id !== candidate.id),
      );
      setValidation((current) => {
        if (!current) return current;
        const accepted = current.fresh_reviewed_accepted
          + (reviewStatus === 'accepted' ? 1 : 0);
        const rejected = current.fresh_reviewed_rejected
          + (reviewStatus === 'rejected' ? 1 : 0);
        const total = accepted + rejected;
        const precision = total ? Math.round((10000 * accepted) / total) / 100 : null;
        return {
          ...current,
          fresh_reviewed_accepted: accepted,
          fresh_reviewed_rejected: rejected,
          fresh_reviewed_clauses: total,
          fresh_review_precision_pct: precision,
          governed_release_ready: Boolean(
            current.technical_release_ready
              && total >= 100
              && precision !== null
              && precision >= 95,
          ),
        };
      });
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save the review');
    } finally {
      setSavingId(null);
    }
  };

  const reviewed = validation?.fresh_reviewed_clauses ?? 0;
  const reviewProgress = Math.min(100, reviewed);

  return (
    <div className="space-y-5">
      {isLoading && !validation ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 text-sm text-slate-500">
          Loading validation status and a 20-item review page…
        </div>
      ) : <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatusCard
          label="Technical gate"
          value={validation?.technical_release_ready ? 'Passed' : 'Not ready'}
          good={validation?.technical_release_ready === true}
        />
        <StatusCard
          label="Human reviews"
          value={`${reviewed} / 100`}
          good={reviewed >= 100}
        />
        <StatusCard
          label="Accepted precision"
          value={validation?.fresh_review_precision_pct === null || !validation
            ? '—'
            : `${validation.fresh_review_precision_pct}%`}
          good={(validation?.fresh_review_precision_pct ?? 0) >= 95}
        />
        <StatusCard
          label="Governed release"
          value={validation?.governed_release_ready ? 'Ready' : 'Blocked'}
          good={validation?.governed_release_ready === true}
        />
      </div>}

      <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="flex items-center gap-2 font-semibold text-slate-100">
              <ShieldCheck className="h-5 w-5 text-purple-400" />
              Contract financial-clause review
            </h2>
            <p className="mt-1 max-w-3xl text-sm text-slate-400">
              Compare the extracted type and value with the exact source excerpt.
              Accept only when the excerpt states the captured deal economics;
              reject false positives, wrong values, or misleading context.
            </p>
            <p className="mt-2 text-xs text-slate-500">
              Decisions are attributed to {user?.email} and retained in the audit log.
            </p>
          </div>
          <button
            type="button"
            onClick={loadQueue}
            disabled={isLoading || savingId !== null}
            className="inline-flex items-center gap-2 rounded-lg bg-slate-800 px-3 py-2 text-sm text-slate-200 transition-colors hover:bg-slate-700 disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
        <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-800">
          <div
            className="h-full bg-purple-500 transition-all"
            style={{ width: `${reviewProgress}%` }}
          />
        </div>
        {validation && (
          <p className="mt-2 text-xs text-slate-500">
            Parser {validation.parser_version} · {validation.parse_coverage_pct}% corpus
            coverage · {validation.sample_replay_accuracy_pct}% replay accuracy
          </p>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {isLoading ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-10 text-center text-slate-500">
          Loading the deterministic review sample…
        </div>
      ) : candidates.length === 0 ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-10 text-center">
          <ClipboardCheck className="mx-auto mb-3 h-10 w-10 text-green-400" />
          <p className="font-medium text-slate-200">No unreviewed candidates in this sample.</p>
          <p className="mt-1 text-sm text-slate-500">Refresh to verify the current queue.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {candidates.map((candidate) => (
            <article
              key={candidate.id}
              className="rounded-xl border border-slate-800 bg-slate-900 p-5"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-blue-500/15 px-2 py-1 text-xs font-semibold text-blue-300">
                      {clauseLabel(candidate.clause_type)}
                    </span>
                    {candidate.is_tiered && (
                      <span className="rounded bg-amber-500/15 px-2 py-1 text-xs text-amber-300">
                        Tiered
                      </span>
                    )}
                  </div>
                  <p className="mt-2 text-2xl font-semibold text-slate-100">
                    {valueLabel(candidate)}
                  </p>
                </div>
                <div className="text-right text-xs text-slate-500">
                  <p>Deal {candidate.deal_id} · Contract {candidate.contract_id}</p>
                  <p>Lines {candidate.source_line_start}–{candidate.source_line_end}</p>
                  <p>Confidence {Math.round(candidate.confidence * 100)}%</p>
                </div>
              </div>

              <blockquote className="mt-4 whitespace-pre-wrap rounded-lg border-l-4 border-blue-500 bg-slate-950/70 p-4 text-sm leading-6 text-slate-300">
                {candidate.source_text}
              </blockquote>

              <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_auto]">
                <label className="text-xs text-slate-400">
                  Optional review note
                  <textarea
                    value={notes[candidate.id] ?? ''}
                    onChange={(event) => setNotes((current) => ({
                      ...current,
                      [candidate.id]: event.target.value,
                    }))}
                    maxLength={2000}
                    rows={2}
                    placeholder="Explain a rejection or record an edge case…"
                    className="mt-1 block w-full resize-y rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 outline-none focus:border-blue-500"
                  />
                </label>
                <div className="flex items-end gap-2">
                  <button
                    type="button"
                    onClick={() => review(candidate, 'rejected')}
                    disabled={savingId !== null}
                    className="inline-flex items-center gap-2 rounded-lg bg-red-500/15 px-4 py-2 text-sm font-medium text-red-300 transition-colors hover:bg-red-500/25 disabled:opacity-50"
                  >
                    <XCircle className="h-4 w-4" />
                    Reject
                  </button>
                  <button
                    type="button"
                    onClick={() => review(candidate, 'accepted')}
                    disabled={savingId !== null}
                    className="inline-flex items-center gap-2 rounded-lg bg-green-500/15 px-4 py-2 text-sm font-medium text-green-300 transition-colors hover:bg-green-500/25 disabled:opacity-50"
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    Accept
                  </button>
                </div>
              </div>
              <p className="mt-3 truncate font-mono text-[10px] text-slate-600">
                Evidence SHA-256: {candidate.source_hash}
              </p>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusCard({ label, value, good }: { label: string; value: string; good: boolean }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-1 text-lg font-semibold ${good ? 'text-green-400' : 'text-amber-300'}`}>
        {value}
      </p>
    </div>
  );
}

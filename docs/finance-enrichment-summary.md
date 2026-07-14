# Cortellis Financial-Term Analytics — Production Report

**Verified:** 2026-07-14 18:38 UTC

**Environment:** `onebd.pchomelab.com`

**Source:** Cortellis `FinanceDetail` JSON retained in PostgreSQL

## Production status

The financial enrichment pipeline is deployed, complete for the current source
snapshot, scheduled for incremental maintenance, and available through governed
Chat queries. It is no longer awaiting deployment or database enrichment.

| Measure | Verified value |
|---|---:|
| Cortellis deals | 172,643 |
| Deals with `FinanceDetail` payloads | 150,898 |
| Normalized financial terms | 503,525 |
| Parser version | 4 |
| Parse coverage | 100% |
| Failed source replays | 0 |
| Deterministic source replays checked | 475 |
| Source replay field accuracy | 100% |

The normalized table preserves deal ID, recipient side, paid/projected basis,
term type, reported amount/currency/unit, Cortellis USD value, royalty range,
disclosure and accuracy metadata, source JSON/path/hash, confidence, and parser
version. The raw vendor node remains available for audit.

## Governed semantic contract

The first production query family uses deliberately narrow rules:

- `basis = projected_current`
- `disclosure_status = Known`
- parser v4 only
- explicit Cortellis USD values for monetary comparisons
- non-breakdown headline terms only
- one maximum headline amount per deal to avoid double-counting reciprocal or
  repeated recipient nodes
- `milestone_total` for aggregate milestone potential; component milestones are
  not summed into a second total
- one disclosed low/high royalty range per deal
- licensing agreement scope for generic “upfront over” deal lists

The platform does not substitute total projected deal value for an upfront or
milestone term. Financial questions outside a governed pattern return a scoped
limitation instead of unconstrained generated SQL. Acquisition-premium analytics
remain unavailable because unaffected equity value and market-price history are
not yet present.

## Production benchmark proofs

These answers passed the user-facing Chat v2 route and an independent read-only
PostgreSQL truth query on 2026-07-14:

| Question | Production result | Disclosure |
|---|---|---:|
| Typical upfront for Phase 2 ADC license assets | median $92.5M; interquartile range $38.875M–$182.5M; average $190.07M | 14 of 22 eligible deals (63.6%) |
| Median milestone for Phase 3 license deals | median $110M; interquartile range $20M–$325M; average $338.57M | 653 of 1,694 eligible deals (38.5%) |
| Typical royalties for oncology bispecific licenses | median per-deal low/high 20%/20%; midpoint interquartile range 10%–22% | 7 of 153 eligible deals (4.6%) |
| License deals with disclosed upfront over $100M | 428 qualifying deals; Chat returns the top 20 with deal citations | all returned rows disclosed |

The royalty benchmark has a particularly small disclosed sample and must be
presented with that caveat. These are descriptive Cortellis-source benchmarks,
not valuation recommendations.

## Phase-at-deal repair

The expanded API carries phase fields inside each deal's drug records, but the
legacy transformer never populated `deals.phase_highest_start` or
`deals.phase_highest_now`. A lossless-archive backfill repaired all 172,638
currently accessible deals in 42 seconds:

| Backfill result | Count |
|---|---:|
| Archived deals checkpointed | 172,638 |
| Deals with phase at start | 63,772 |
| Deals with current phase | 64,312 |
| XML/parser failures | 0 |

Future full/incremental syncs and expanded-response coverage scans populate the
same fields as records arrive. Deal phase is the highest per-drug phase in that
deal's expanded response, using Cortellis phase IDs and a deterministic stage
ordering. It should not be confused with a separate, global current asset phase.

## Operations and verification

- Incremental extraction task:
  `unified_api.workers.tasks.enrichment.extract_financial_terms`
- One-time/versioned rebuild task:
  `unified_api.workers.tasks.enrichment.rebuild_financial_terms`
- Phase archive repair task:
  `unified_api.workers.tasks.enrichment.backfill_deal_phases`
- Status endpoint: `/api/enrichment/status`
- Validation endpoint: `/api/enrichment/financial-terms/validation`
- Governed pageable terms: `/api/v1/financial-terms`
- MCP tool: `search_financial_terms`
- Metric definitions: `/api/analytics/metric-definitions`
- Executable truth suite: `unified_api/evals/question_cases.yaml`

The production proof passed all five blocking regressions and financial cases
#11, #14, #16, and #17 with direct database truth. The local backend suite passed
593 tests with 67 database-dependent tests deferred to the deployed environment.

## Access and licensing control

Source-license annotations document provenance and contractual considerations;
they do not hard-code access restrictions. The system owner controls whether
dataset, API-key scope, authentication, and MCP restrictions are enforced through
Admin → API Access. Current policy can therefore be tightened, relaxed, or left
advisory by the owner without changing the financial parser.

## Remaining financial priorities

1. Add governed question shapes for deal-specific terms, company comparisons,
   and milestone structures in comp sets.
2. Add acquisition-premium inputs from licensed market-price/fundamental data.
3. Add review UI that opens a normalized term beside its exact archived source
   node and vendor citation.
4. Expand truth cases before promoting any additional free-form financial query.

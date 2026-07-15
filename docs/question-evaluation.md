# BD Intelligence Platform — Question & Analysis Evaluation

**Reviewed:** 2026-07-15

**Assessment baseline:** `onebd.pchomelab.com`, production database snapshot
2026-07-14

**Verified remediation:** through the current change set, checked against the
2026-07-15 production database

**Status:** All 65 questions are versioned, executable, and have deterministic
pass/fail oracles. Eight are blocking production regressions. Eighteen cases
compare the deployed response with direct, read-only database truth; 54 use
scored grounding/provenance rubrics (six cases use both).

## Purpose

This document measures whether a user can obtain a correct, grounded answer from
the product—not merely whether the database contains the necessary columns or a
developer could write a suitable query by hand.

The previous score treated route existence and theoretical SQL feasibility as
successful question answering. Production checks showed that this overstated
readiness. For example, the assessed baseline answered that Pfizer had zero 2024
deals because it queried the exact name `Pfizer`; the canonical `Pfizer Inc`
record now has 26 after exhaustive historical recovery. The remediated
deployment returns that grounded count.

## Rating Standard

- ✅ **Strong** — Demonstrated end-to-end answer with correct entity resolution,
  correct metric semantics, supporting records/source references, useful caveats,
  and acceptable latency.
- 🟡 **Partial** — Useful capability exists, but the user must supply IDs/use a
  direct feature, coverage is incomplete, or answer reliability is not yet proven.
- 🔧 **Needs Work** — Relevant data or infrastructure exists, but the requested
  workflow or governed metric is not implemented.
- ❌ **Cannot / Unreliable** — Required data is absent or the current answer can
  be materially misleading.

A generated SQL statement, an LLM narrative, or an endpoint alone is not proof of
a Strong result. Numerical questions require deterministic ground truth; narrative
questions require source-backed claims and a refusal when evidence is insufficient.

## Current Production Baseline

The counts below were re-verified at 2026-07-14 18:38 UTC and will continue to
move as scheduled enrichment and linking jobs run.

- 172,643 Cortellis rows and 67,177 companies. Exhaustive retrieval proved
  172,638 currently accessible deals plus five preserved retired records; the
  API search endpoint advertises only 149,028.
- 41,503 deals with at least one disclosed financial total (24.0%).
- 150,898 deals with typed `FinanceDetail` payloads and 503,525 normalized
  financial terms; parser v4 has 100% source-payload coverage and no failures.
- 25,977 indexed contracts and 897,041 embedded contract chunks.
- 330,818 EDGAR filings and 3,580,771 filing chunks.
- 692 company mappings with CIKs (1,648 cross-references of all types).
- 76,448 candidate deal–filing links generated from company and date proximity.
- 2,157 patent records and 2,863 deal–patent associations; this is not a
  comprehensive patent landscape.
- Archive-backed phase repair populated phase-at-start for 63,772 deals and
  current phase for 64,312 deals; all 172,638 accessible archived records were
  inspected with zero parse failures.
- Cortellis incremental sync is current. Both EDGAR recent and historical lanes
  reached 2026-07-13; the historical backlog is complete for that snapshot.

## Historical Baseline Reliability Findings

These were observed in the reviewed baseline and drove the remediation below;
they are not descriptions of the current deployment.

1. **Entity aliases invalidated otherwise simple questions.** Chat v2 returned
   zero Pfizer deals for 2024; `Pfizer Inc` now has 26.
2. **Financial concepts were not governed.** A milestone question generated SQL
   against total projected deal value rather than milestone payments.
3. **Empty-result synthesis was not grounded.** A Roche strategy question returned
   zero rows but still introduced unsupported historical assertions.
4. **Chat confidence was not factual confidence.** It reported record
   count and financial disclosure rate, without source citations or validation.
5. **EDGAR form filtering was incorrect.** Actual forms are stored in
   `documents.subtype`, while list/search routes filter `documents.doc_type`
   (`filing`). A live `doc_type=8-K` search returned no results.
6. **DD output was incomplete.** SEC filings, contracts, territory rights, and
   comparable-transaction sections were empty placeholders in the reviewed
   baseline.
7. **Comp modality was scored but not used to select candidates.** High-value
   nonmatching candidates can crowd out the relevant modality before ranking.
8. **The agentic-RAG suite was not green.** Eight tests failed around async
   mocks/tool execution in the reviewed production baseline.

## Verified Remediation

The deployed implementation addresses the most consequential baseline failures:

- Canonical company resolution is passed into SQL generation, and generated SQL
  is not executed if it drops an unambiguous company ID.
- Company/year deal counts use a deterministic, index-friendly truth query rather
  than an LLM-generated name match.
- Upfront, milestone, and royalty benchmark questions use governed parser-v4 SQL
  with explicit source basis, disclosure denominator, unit, and database truth.
  Acquisition-premium questions still return an explicit limitation.
- Empty or all-null evidence produces a deterministic insufficient-evidence
  response and bypasses narrative synthesis.
- EDGAR form filtering and output use `COALESCE(subtype, doc_type)`.
- Comp-set candidate retrieval now applies modality as well as indication, phase,
  deal type, and date filters before ranking.
- Agentic-RAG tool availability and streaming state handling were corrected; its
  15 focused tests now pass.
- Five production regressions (#1, #14, #23, #35, and #61) are versioned in
  `unified_api/evals/question_cases.yaml` and executable through
  `python -m unified_api.scripts.evaluate_questions`.
- Chat v2 now returns record-level or aggregate-query citations and marks evidence
  as grounded only when retrieved data has source provenance.
- Aggregate financial confidence reports underlying disclosed/eligible deal
  coverage rather than treating one aggregate response row as the sample.
- `/api/analytics/metric-definitions` publishes the semantic contract for deal
  count, projected totals, reported paid totals, upfronts, milestones, royalties,
  and acquisition premiums.
- Every non-truth case now has a weighted evidence rubric checking answer
  integrity, retrieved-data/citation alignment, record traceability, sample-size
  consistency, and generated-SQL safety. Direct endpoints use exact filter/result
  rubrics instead.
- The stricter rubric exposed that Roche's oncology-strategy question was routed
  to an unconstrained graph leaderboard. The current remediation routes it to a
  canonical-company, Cancer-taxonomy, agreement-pattern query and verifies the
  returned rows against database truth.
- Full/incremental Cortellis syncs and raw-response scans now populate
  phase-at-deal fields; the production archive repair inspected 172,638 records
  with zero failures.
- Due-diligence generation now resolves source-backed SEC filings, contract text
  and parser-v11 clause candidates, agreement territory scope, and deterministically
  scored comparable transactions. Direct DD and Chat DD routes expose section
  provenance, coverage totals, and methodology caveats and are checked against
  independent Cortellis and EDGAR truth queries.

The original five seeded cases passed against deployed commit `314efda` on
2026-07-11:

1. Pfizer 2024 count returned the then-current 23 using canonical company ID
   18767.
2. Median milestone analytics then refused safely without generating substitute SQL.
3. Bispecific comp candidates return the matching bispecific modality.
4. Empty Roche strategy evidence does not introduce an unsupported history claim.
5. Full-text EDGAR filtering returns non-empty 8-K results.

The exhaustive Cortellis repair on 2026-07-14 recovered three additional
Pfizer-linked 2024 records (deal IDs 385757, 408502, and 425099), changing the
governed count from 23 to 26. Both the deployed answer and direct PostgreSQL
truth return 26; the blocking regression was updated accordingly.

On 2026-07-14, deployed commit `1fd6366` passed all five blocking regressions
with direct database truth. The milestone regression now returns the governed
parser-v4 result instead of a refusal. Financial catalog cases #11, #16, and
#17 also passed independently executed PostgreSQL truth queries.

The scorecard incorporates the directly justified rating changes below. A passing
refusal improves safety but does not make an unavailable analytical capability
Strong. Narrative rubrics establish a repeatable evidence floor; they do not
replace question-specific database truth where an exact numerical answer exists.

## 2026-07-11 Priority Sprint Verification

- The versioned evaluation file contains exactly 65 executable cases: five
  deterministic regression cases and 60 catalog probes.
- The GitHub quality gate passed backend, frontend, and Compose jobs; all three
  checks are now required on `main` before normal merges.
- The final database-attached production-image suite passed all 329 tests.
- Frontend production build and `npm audit` pass with zero vulnerabilities.
- Entity enrichment created 2,890 aliases across all 1,648 xrefs and raised the
  high-confidence share from 19.5% to 48.9% without merging fuzzy affiliates.
- The 3.35M-row EDGAR vector index is valid, occupies 26 GB, and is selected by
  PostgreSQL for cosine-nearest-neighbor queries.
- A bounded EDGAR catch-up advanced the cursor seven days to 2025-11-30, adding
  139 filings, 275 documents, and 3,653 chunks without error.
- The five blocking production regressions pass on the final deployment, including
  canonical Pfizer count provenance and evidence-status assertions.

## Deterministic Truth Expansion

Production probing after the initial sprint found that several endpoint-based
ratings were too optimistic: top acquirers returned no rows, the oncology average
used a taxonomy term that does not exist, geography grouped on an almost entirely
empty company-location field, and “top 20” exposed only ten records. These are now
governed SQL patterns using the actual Cortellis taxonomy and fields:

- `Cancer` is the source taxonomy value for oncology.
- M&A and licensing are classified from `agreement_type`; `deal_type` is empty in
  the current Cortellis database.
- Financial comparisons are restricted to USD/Million records.
- Geography uses deal territory rights, not sparsely populated company HQ text.
- Chat v2 exposes up to 20 rows so a top-20 request is not silently truncated.

The evaluation schema now rejects any Strong-rated case without a versioned,
read-only database truth query, and rejects any other case lacking either truth
or a scored rubric. Cases #1, #3, #10, #12, #13, #18, #32, #35, #52, #53,
and #54, plus financial cases #11, #14, #16, and #17, have database truth.
Cases #7, #19, #37, #42, #49, and #50 were
downgraded until graph identity, YoY period semantics, or conversational context
is made deterministic.

The Cortellis financial source was also re-audited. `finance_detail_raw` is JSONB,
not unstructured text: 150,898 deals contain typed paid/projected payments,
recipient side, dates, currencies, USD conversions, disclosure status, milestone
breakdowns, royalty percentages, notes, and accuracy metadata. The old regex-only
enrichment route treated this payload as a string and could not populate governed
terms. The structured parser flattens it into `deal_financial_terms`, preserves
the source JSON/path and parser version, and records resumable per-deal extraction status.
Parser v4 corrects Cortellis `B`/`T` unit scaling, captures bounded percentage
terms beyond royalties, and normalizes one impossible vendor `%`/money unit
conflict while preserving the raw source node. The production gate now covers
all 150,898 payloads and 503,525 terms with zero structural failures and 100%
accuracy across 475 deterministic source replays. The job remains resumable and
scheduled. Governed SQL and question-specific truth are now live for Phase 2 ADC
upfronts, Phase 3 license milestone totals, oncology bispecific royalties, and
license deals with upfronts over a requested threshold. Other financial question
shapes continue to refuse unconstrained SQL.

The deployed benchmark values are intentionally disclosure-aware: Phase 2 ADC
upfronts use 14 disclosed of 22 eligible deals (median $92.5M), Phase 3 license
milestones use 653 of 1,694 (median $110M), and oncology bispecific royalties use
only 7 of 153 (median midpoint 20%). The small royalty sample is a material
limitation, not a confidence score to hide.

---

## Category 1: Quick Factual Lookups

*JVO in a meeting, needs a correct answer in 10 seconds.*

| # | Question | Rating | Current assessment |
|---|---|---:|---|
| 1 | How many deals did Pfizer do in 2024? | ✅ | Production returns 26 through deterministic company/year SQL using canonical Pfizer ID 18767. |
| 2 | What was the biggest pharma deal ever? | 🟡 | Deterministic over disclosed totals, but “pharma,” currency/amount semantics, and disclosure scope need explicit handling. |
| 3 | Who are the top 5 most active acquirers this year? | ✅ | Governed SQL counts `Partner` companies only on M&A agreements started in the current year, with a bounded reproducible ranking. |
| 4 | What are the largest ADC deals in oncology? | ✅ | Governed SQL maps oncology to the `Cancer` therapy area, normalizes ADC technology synonyms, ranks unique deals by disclosed USD/Million total value, and reports disclosure coverage. |
| 5 | What is BeiGene's total deal count? | 🟡 | Queryable after resolving BeiGene/BeOne and duplicate company entities. |
| 6 | When was the last oncology M&A deal over $1B? | 🟡 | Queryable, but generated multi-table SQL and financial units need golden-answer validation. |
| 7 | Is there a deal between Pfizer and Seagen? | 🔧 | The graph chat path does not yet bind both canonical IDs deterministically. |
| 8 | What phase is drug X in? | 🟡 | Phase exists, but drug aliases, multiple assets, phase provenance, and “current” semantics need resolution. |
| 9 | How many deals closed last week? | 🟡 | Relative dates, timezone, and closed-vs-announced field selection are not deterministic. |
| 10 | What is the average deal size in oncology? | ✅ | Analytics can calculate it with a disclosure caveat; null and unit handling must remain explicit. |

**Catalog rating: 4 Strong, 5 Partial, 1 Needs Work**

---

## Category 2: Analytical / Benchmarking

| # | Question | Rating | Current assessment |
|---|---|---:|---|
| 11 | Typical upfront payments for Phase 2 ADC assets? | ✅ | Governed Phase 2 + ADC + license + parser-v4 query returns a $92.5M median from 14 disclosed of 22 eligible deals and matches direct database truth. |
| 12 | Valuation range for oncology M&A deals, 2020–2025? | ✅ | Supported by deterministic analytics filters with disclosure caveats. |
| 13 | How have deal values trended over five years? | ✅ | Market-trends endpoint supports reproducible trend output. |
| 14 | Median milestone payment for Phase 3 license deals? | ✅ | Governed milestone-total query returns a $110M median from 653 disclosed of 1,694 eligible deals and matches direct database truth. |
| 15 | Compare Pfizer vs Merck vs Novartis deal activity. | 🟡 | Endpoint exists; frontend uses hardcoded IDs and entity selection is not robust. |
| 16 | Typical royalty rates for oncology bispecifics? | ✅ | Governed per-deal royalty ranges return a 20% median midpoint, but only 7 of 153 eligible deals disclose a usable rate; the answer exposes that limitation. |
| 17 | Deals with disclosed upfront over $100M. | ✅ | Governed parser-v4 query finds 428 qualifying license deals, returns the top 20 with record citations, and matches direct database truth. |
| 18 | Percentage of 2024 deals that were M&A vs licensing. | ✅ | Agreement-type distribution endpoint supports the calculation. |
| 19 | YoY deal-volume growth by therapy area. | 🟡 | Endpoint exists, but the requested comparison period is underspecified and chat output lacks a truth assertion. |
| 20 | Largest deal in each major therapy area. | 🟡 | Straightforward SQL, but no demonstrated product workflow/golden result yet. |

**Measured score: 7 Strong, 3 Partial**

---

## Category 3: Strategic / Recommendation

| # | Question | Rating | Current assessment |
|---|---|---:|---|
| 21 | What should we pay for a lung-cancer bispecific company? | 🟡 | Comp inputs exist, but no acquisition framework or evidence-weighted recommendation. |
| 22 | Most likely acquisition targets in ADC oncology? | 🔧 | No target-screening model with explainable criteria. |
| 23 | Build a comp set for a Phase 2 NSCLC bispecific license. | 🟡 | All requested dimensions now constrain candidates and return their matched values; comp quality and financial coverage still need a full truth set. |
| 24 | Competitive landscape for CAR-T in hematology. | 🟡 | Data and briefing components exist; no complete landscape workflow or market map. |
| 25 | Build, buy, or partner for solid-tumor ADC assets? | ❌ | Requires internal R&D, strategic fit, cost, and risk inputs that are not present. |
| 26 | Which companies are divesting oncology assets? | 🟡 | Queryable candidates, but divestiture intent/classification is not governed. |
| 27 | Expected acquisition premium for a Phase 3 company? | 🟡 | Deal values exist; pre-announcement market capitalization/stock prices do not. |
| 28 | Generate a DD package on Pfizer. | ✅ | The direct DD workflow populates all ten advertised sections. SEC, contract, territory-scope, and comparable records retain source, coverage, and methodology metadata; aggregate counts match independent Cortellis and EDGAR truth. |
| 29 | Warm introduction paths between us and Company Y. | 🟡 | Deal-network paths exist; personal relationship data does not. |
| 30 | Recommend deals/targets I have not seen. | 🟡 | Recommendation endpoint is primarily recency/value based, not behavioral personalization. |

**Catalog rating: 1 Strong, 7 Partial, 1 Needs Work, 1 Cannot**

---

## Category 4: Competitive Intelligence

| # | Question | Rating | Current assessment |
|---|---|---:|---|
| 31 | What has Pfizer done in the last 90 days? | 🟡 | Company profile works with an ID, but natural-language entity resolution is unreliable. |
| 32 | Who is most actively acquiring oncology assets? | ✅ | Top-acquirers analytics supports therapy filtering. |
| 33 | Compare our deal pace to Merck's. | 🟡 | “Our company” is not configured and comparison selection is cumbersome. |
| 34 | Alert me when a competitor does an ADC deal. | 🟡 | Saved-search alerts, Celery checks, notifications, and email exist; configuration UX/validation remains limited. |
| 35 | What is Roche's oncology strategy from its deal pattern? | 🟡 | Canonical-company chat is checked against agreement-pattern truth, and the company profile now adds deterministic five-year deal-pattern statements, focus areas, evidence deal IDs, overlap peers, and explicit non-inference caveats. The chat path does not yet call that richer service directly. |
| 36 | Which companies just entered the bispecific space? | 🔧 | Query logic is feasible but no tested new-entrant workflow exists. |
| 37 | Show Pfizer's partnership network. | 🔧 | The direct ID endpoint works, but chat currently extracts the company name heuristically rather than binding canonical ID 18767. |
| 38 | How does AbbVie's deal structure differ from Gilead's? | 🟡 | Distributions can be retrieved; grounded comparison synthesis is not proven. |
| 39 | Are competitors building ADC portfolios faster than us? | ❌ | “Us,” portfolio boundaries, and velocity metric are not defined. |
| 40 | Weekly competitive briefing for oncology. | 🟡 | Weekly personalized intelligence digests now use correct seven-day and therapy/company filters and can include sourced upcoming clinical catalysts; competitor-focused narrative and delivery QA remain incomplete. |

**Catalog rating: 1 Strong, 6 Partial, 2 Needs Work, 1 Cannot**

---

## Category 5: Due Diligence & Deal Execution

| # | Question | Rating | Current assessment |
|---|---|---:|---|
| 41 | Full DD on Pfizer. | ✅ | Chat recognizes explicit DD intent, resolves canonical Pfizer ID 18767, invokes the governed ten-section package instead of generated SQL, cites Cortellis and SEC, and exposes truth-checked section totals. |
| 42 | What territories are available for Drug Y? | 🟡 | Territory-rights endpoint works for a concrete drug ID; the placeholder question has no resolvable asset. |
| 43 | Contracts mentioning royalty rates for this drug. | 🟡 | 25,977 contracts/897,041 chunks are searchable; exact drug scoping and structured extraction need validation. |
| 44 | Risk flags for this acquisition target. | 🟡 | Basic heuristic flags exist and filings/contracts are available elsewhere in the package, but risk synthesis does not yet integrate litigation, clinical, contract, filing, and financial-risk evidence. |
| 45 | Export a comp set with deal values to Excel. | 🔧 | Comp PowerPoint export is shipped; comp-specific Excel export is not. |
| 46 | What SEC filings relate to this deal? | 🟡 | 76,448 candidate links exist, but only 692 CIK mappings and date-proximity matching needs precision review. |
| 47 | Milestone structure for comparable deals. | 🔧 | No milestone-specific comp view or governed extraction table. |
| 48 | IP landscape for KRAS inhibitors. | ❌ | Limited deal-linked patent metadata exists, but not claims/families/status/assignee coverage for an IP landscape. |
| 49 | Timeline of all deals for this target company. | 🟡 | Company timeline is supported after an explicit entity selection; the standalone placeholder has no target context. |
| 50 | Who else licensed this company's technology? | 🟡 | Partner history is available after an explicit company selection; conversational referent handling is not deterministic. |

**Catalog rating: 1 Strong, 6 Partial, 2 Needs Work, 1 Cannot**

---

## Category 6: Market Landscape & Reporting

| # | Question | Rating | Current assessment |
|---|---|---:|---|
| 51 | Oncology deal landscape 2024 for the board. | 🟡 | Analytics and briefings exist; no board-ready, source-cited report template. |
| 52 | Top 20 largest pharma deals ever. | ✅ | Top-deals endpoint supports disclosed-value ranking. |
| 53 | Deal-activity heatmap by therapy area. | ✅ | Dedicated heatmap endpoint and visualization exist. |
| 54 | Deal volume by geography. | ✅ | Geographic-distribution endpoint exists. |
| 55 | M&A vs licensing split in oncology over time. | 🟡 | Components exist but no combined time-series workflow. |
| 56 | Market map of NSCLC deal activity. | ❌ | No companies-by-indications market-map visualization. |
| 57 | PDF export of this board analysis. | 🟡 | DD PDF and comp PPTX are wired; analytics/board PDF is not. |
| 58 | Our therapeutic focus versus the industry. | 🟡 | Industry distribution exists; “our company” overlay does not. |
| 59 | Quarterly deal report for Q2 2025. | 🟡 | Data is available, but no tested quarterly-report template. |
| 60 | Indications with the most deal-activity growth. | 🟡 | Queryable, but no dedicated demonstrated workflow/golden result. |

**Catalog rating: 3 Strong, 6 Partial, 1 Cannot**

---

## Category 7: SEC Filing Intelligence

| # | Question | Rating | Current assessment |
|---|---|---:|---|
| 61 | Find 8-K filings mentioning ADC partnerships. | 🟡 | Form-aware full-text filtering works, the historical backlog is caught up, and the regression is green; ADC-partnership-specific precision truth is still broader than the current form-filter oracle. |
| 62 | Show Pfizer's 10-K risk factors. | 🟡 | Generic sections and a section endpoint exist; reliable form-aware Item 1A extraction/filtering is incomplete. |
| 63 | Cross-reference this Cortellis deal with SEC filings. | 🟡 | Matcher is implemented with 76,448 links; company/date candidates need content-based ranking and precision evaluation. |
| 64 | Material contracts from recent 8-K filings. | 🟡 | Recent ingestion extracts EX-10 exhibits, form filtering works, and the backlog is current; structured contract classification and precision truth remain incomplete. |
| 65 | S-1 analysis for a pre-IPO biotech. | 🟡 | S-1 text is searchable; structured pipeline/financial/risk extraction is incomplete. |

**Catalog rating: 5 Partial**

---

## Measured Scorecard

This score is generated from the ratings in the executable 65-case catalog.

| Category | Strong ✅ | Partial 🟡 | Needs Work 🔧 | Cannot ❌ | Total |
|---|---:|---:|---:|---:|---:|
| Quick Factual | 4 | 5 | 1 | 0 | 10 |
| Analytical | 7 | 3 | 0 | 0 | 10 |
| Strategic | 1 | 7 | 1 | 1 | 10 |
| Competitive Intelligence | 1 | 6 | 2 | 1 | 10 |
| Due Diligence | 1 | 6 | 2 | 1 | 10 |
| Market Landscape | 3 | 6 | 0 | 1 | 10 |
| SEC Filings | 0 | 5 | 0 | 0 | 5 |
| **Total** | **17** | **38** | **6** | **4** | **65** |

**Measured catalog rating: 17/65 Strong (26.2%); 55/65 at least Partial
(84.6%).** This corrects arithmetic drift in the previous hand-maintained
scorecard and should be regenerated from YAML after future rating changes.

The breadth remains useful, but correctness and grounding—not feature count—are
the limiting factors.

## Executable Evaluation Specification

All 65 questions are versioned in `unified_api/evals/question_cases.yaml`. The
eight regression-tier cases have deterministic production assertions. Eighteen
cases compare response fields to read-only SQL truth, while 54 cases have weighted
evidence rubrics; six cases use both. Exact truth should continue to replace
narrative rubrics as governed query shapes are added. A completed truth case must
include:

```yaml
id: 1
question: How many deals did Pfizer do in 2024?
channel: chat_v2
entities:
  company_ids: [18767]
expected:
  type: scalar
  value: 26
  tolerance: 0
required_evidence:
  - generated_query
  - source_record_count
latency_budget_seconds: 10
dataset_as_of: 2026-07-14
```

Evaluation rules:

1. Build deterministic truth queries for factual/analytical questions.
2. Test the user-facing route, not only the underlying SQL.
3. Fail numerical answers that use the wrong metric even if the prose is cautious.
4. Fail unsupported claims when zero evidence rows are returned.
5. Require record IDs/source labels for Strong answers.
6. Record latency, generated query, retrieved rows, deployed commit, and data date.
7. Use an LLM judge only for presentation/coverage; never as numerical ground truth.
8. Run the golden set before deployment and publish score changes by category.

## Priority Work Derived From This Evaluation

### P0 — Trustworthiness

1. ✅ Canonical entity/alias resolution before SQL generation (initial company
   implementation; broader aliases and ownership remain).
2. 🟡 Governed upfront, milestone, royalty, total-value, and phase-at-deal
   definitions are live. Add explicit announced/closed semantics and acquisition
   premium once market-price inputs exist.
3. ✅ Evidence-only synthesis: refuse or clearly return “not found” on empty results.
4. ✅ Chat v2 returns record/aggregate citations, query provenance, evidence
   status, and underlying financial disclosure coverage.
5. ✅ Executable 65-question harness with database-truth and scored-evidence
   oracles for every case.

### P1 — Broken or incomplete workflows

6. ✅ EDGAR form filtering uses `subtype`, and recent/historical lanes are caught
   up through the current production snapshot.
7. ✅ Apply modality during comp candidate retrieval.
8. ✅ Populate DD SEC filing, contract, territory, and comparable-transaction
   sections, including governed Chat routing and independent multi-database truth.
9. Add content-based validation/ranking to deal–filing links.
10. ✅ Fix the agentic-RAG tests and tool async boundaries.

### P2 — Higher-value expansion

11. ✅ Parser-v4 milestone/royalty extraction is complete and the first governed
    benchmarks are production-truthed; add deal-specific and comp-view shapes.
12. Dynamic company comparison and “my company” configuration.
13. 🟡 Evidence-limited company strategy summaries and baseline-safe, durable
    tracked-company indication entrant alerts are implemented; add general target
    screening and modality-wide entrant detection for questions such as #36.
14. Board/quarterly report templates and analytics PDF export.
15. 🟡 ClinicalTrials.gov API-v2 current/history ingestion, provenance, exact
    company/asset/indication links, and catalyst endpoints are implemented.
    Exact PubChem InChIKey → ChEMBL → Open Targets mappings now add canonical
    Ensembl targets, mechanisms, public drug profiles, and disease-stage links.
    The primary drug-profile UI now combines those records with exact linked
    trials and the existing Cortellis deal/rights view. Governed chat resolves
    exact source-backed drug aliases and supports asset-to-trial, asset-to-target,
    asset-to-disease, and target-to-asset queries with record-level citations;
    complete the production enrichment backfill and broader screening workflows.

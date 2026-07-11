# BD Intelligence Platform — Question & Analysis Evaluation

**Reviewed:** 2026-07-11

**Production baseline:** `onebd.pchomelab.com`, commit `47cd680`

**Status:** Provisional code-and-production review with an initial five-case
remediation set; the full 65-case golden set is not yet automated

## Purpose

This document measures whether a user can obtain a correct, grounded answer from
the product—not merely whether the database contains the necessary columns or a
developer could write a suitable query by hand.

The previous score treated route existence and theoretical SQL feasibility as
successful question answering. Production checks showed that this overstated
readiness. For example, Chat v2 answered that Pfizer had zero 2024 deals because
it queried the exact name `Pfizer`; the canonical `Pfizer Inc` record has 23.

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

- 146,852 Cortellis deals and 52,860 companies.
- 39,336 deals with disclosed financial totals (26.8%).
- 25,978 indexed contracts and 897,130 embedded contract chunks.
- 314,109+ EDGAR documents and 3.35M+ filing chunks.
- 692 company mappings with CIKs (1,648 cross-references of all types).
- 66,980 candidate deal–filing links generated from company and date proximity.
- 2,156 patent records and 2,862 deal–patent associations; this is not a
  comprehensive patent landscape.
- Cortellis incremental sync is current. EDGAR has an independent recent lane,
  but its historical cursor still has a roughly 229-day backlog.

## Verified Baseline Reliability Findings

1. **Entity aliases can invalidate otherwise simple questions.** Chat v2 returned
   zero Pfizer deals for 2024; `Pfizer Inc` has 23.
2. **Financial concepts are not governed.** A milestone question generated SQL
   against total projected deal value rather than milestone payments.
3. **Empty-result synthesis is not grounded.** A Roche strategy question returned
   zero rows but still introduced unsupported historical assertions.
4. **Chat confidence is not factual confidence.** It currently reports record
   count and financial disclosure rate, without source citations or validation.
5. **EDGAR form filtering is incorrect.** Actual forms are stored in
   `documents.subtype`, while list/search routes filter `documents.doc_type`
   (`filing`). A live `doc_type=8-K` search returned no results.
6. **DD output is incomplete.** SEC filings, contracts, territory rights, and
   comparable-transaction sections are currently empty placeholders.
7. **Comp modality is scored but not used to select candidates.** High-value
   nonmatching candidates can crowd out the relevant modality before ranking.
8. **The agentic-RAG suite was not green.** Eight tests failed around async
   mocks/tool execution in the reviewed production baseline.

## Remediation in the Current Change Set

The first implementation pass addresses the most consequential baseline failures:

- Canonical company resolution is passed into SQL generation, and generated SQL
  is not executed if it drops an unambiguous company ID.
- Company/year deal counts use a deterministic, index-friendly truth query rather
  than an LLM-generated name match.
- Unsupported aggregate milestone and acquisition-premium questions return an
  explicit limitation instead of substituting total projected deal value.
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

The scorecard below remains the conservative pre-remediation baseline until those
five cases pass against the deployed commit. A passing refusal improves safety but
does not make an unavailable analytical capability Strong.

---

## Category 1: Quick Factual Lookups

*JVO in a meeting, needs a correct answer in 10 seconds.*

| # | Question | Rating | Current assessment |
|---|---|---:|---|
| 1 | How many deals did Pfizer do in 2024? | 🟡 | Data supports it, but live Chat v2 returned 0 instead of 23 because entity aliases are not resolved. |
| 2 | What was the biggest pharma deal ever? | 🟡 | Deterministic over disclosed totals, but “pharma,” currency/amount semantics, and disclosure scope need explicit handling. |
| 3 | Who are the top 5 most active acquirers this year? | ✅ | Dedicated analytics endpoint provides a bounded, reproducible query. |
| 4 | How many ADC deals have been done? | 🟡 | Queryable, but ADC synonym/technology normalization and end-to-end chat accuracy are unverified. |
| 5 | What is BeiGene's total deal count? | 🟡 | Queryable after resolving BeiGene/BeOne and duplicate company entities. |
| 6 | When was the last oncology M&A deal over $1B? | 🟡 | Queryable, but generated multi-table SQL and financial units need golden-answer validation. |
| 7 | Is there a deal between Pfizer and Seagen? | ✅ | Graph/SQL relationship lookup exists when canonical company IDs are resolved. |
| 8 | What phase is drug X in? | 🟡 | Phase exists, but drug aliases, multiple assets, phase provenance, and “current” semantics need resolution. |
| 9 | How many deals closed last week? | 🟡 | Relative dates, timezone, and closed-vs-announced field selection are not deterministic. |
| 10 | What is the average deal size in oncology? | ✅ | Analytics can calculate it with a disclosure caveat; null and unit handling must remain explicit. |

**Provisional score: 3 Strong, 7 Partial**

---

## Category 2: Analytical / Benchmarking

| # | Question | Rating | Current assessment |
|---|---|---:|---|
| 11 | Typical upfront payments for Phase 2 ADC assets? | 🟡 | Phase valuation analytics exists, but modality and upfront-specific semantics are not consistently combined. |
| 12 | Valuation range for oncology M&A deals, 2020–2025? | ✅ | Supported by deterministic analytics filters with disclosure caveats. |
| 13 | How have deal values trended over five years? | ✅ | Market-trends endpoint supports reproducible trend output. |
| 14 | Median milestone payment for Phase 3 license deals? | 🔧 | No governed milestone aggregation; live chat incorrectly queried total projected value. |
| 15 | Compare Pfizer vs Merck vs Novartis deal activity. | 🟡 | Endpoint exists; frontend uses hardcoded IDs and entity selection is not robust. |
| 16 | Typical royalty rates for oncology bispecifics? | 🔧 | Contract retrieval exists, but structured royalty extraction is not complete at scale. |
| 17 | Deals with disclosed upfront over $100M. | ✅ | Advanced search can filter disclosed financial fields when “upfront” is mapped to the correct column. |
| 18 | Percentage of 2024 deals that were M&A vs licensing. | ✅ | Agreement-type distribution endpoint supports the calculation. |
| 19 | YoY deal-volume growth by therapy area. | ✅ | Dedicated YoY analytics endpoint exists. |
| 20 | Largest deal in each major therapy area. | 🟡 | Straightforward SQL, but no demonstrated product workflow/golden result yet. |

**Provisional score: 5 Strong, 3 Partial, 2 Needs Work**

---

## Category 3: Strategic / Recommendation

| # | Question | Rating | Current assessment |
|---|---|---:|---|
| 21 | What should we pay for a lung-cancer bispecific company? | 🟡 | Comp inputs exist, but no acquisition framework or evidence-weighted recommendation. |
| 22 | Most likely acquisition targets in ADC oncology? | 🔧 | No target-screening model with explainable criteria. |
| 23 | Build a comp set for a Phase 2 NSCLC bispecific license. | 🟡 | Comp builder exists, but modality is not currently applied to candidate selection. |
| 24 | Competitive landscape for CAR-T in hematology. | 🟡 | Data and briefing components exist; no complete landscape workflow or market map. |
| 25 | Build, buy, or partner for solid-tumor ADC assets? | ❌ | Requires internal R&D, strategic fit, cost, and risk inputs that are not present. |
| 26 | Which companies are divesting oncology assets? | 🟡 | Queryable candidates, but divestiture intent/classification is not governed. |
| 27 | Expected acquisition premium for a Phase 3 company? | 🟡 | Deal values exist; pre-announcement market capitalization/stock prices do not. |
| 28 | Generate a DD package on Company X. | 🟡 | Six useful sections exist; four advertised sections are empty placeholders. |
| 29 | Warm introduction paths between us and Company Y. | 🟡 | Deal-network paths exist; personal relationship data does not. |
| 30 | Recommend deals/targets I have not seen. | 🟡 | Recommendation endpoint is primarily recency/value based, not behavioral personalization. |

**Provisional score: 8 Partial, 1 Needs Work, 1 Cannot**

---

## Category 4: Competitive Intelligence

| # | Question | Rating | Current assessment |
|---|---|---:|---|
| 31 | What has Pfizer done in the last 90 days? | 🟡 | Company profile works with an ID, but natural-language entity resolution is unreliable. |
| 32 | Who is most actively acquiring oncology assets? | ✅ | Top-acquirers analytics supports therapy filtering. |
| 33 | Compare our deal pace to Merck's. | 🟡 | “Our company” is not configured and comparison selection is cumbersome. |
| 34 | Alert me when a competitor does an ADC deal. | 🟡 | Saved-search alerts, Celery checks, notifications, and email exist; configuration UX/validation remains limited. |
| 35 | What is Roche's oncology strategy from its deal pattern? | ❌ | Live test synthesized unsupported background claims after retrieving zero rows. |
| 36 | Which companies just entered the bispecific space? | 🔧 | Query logic is feasible but no tested new-entrant workflow exists. |
| 37 | Show Pfizer's partnership network. | ✅ | Graph network page and endpoint exist with canonical ID resolution. |
| 38 | How does AbbVie's deal structure differ from Gilead's? | 🟡 | Distributions can be retrieved; grounded comparison synthesis is not proven. |
| 39 | Are competitors building ADC portfolios faster than us? | ❌ | “Us,” portfolio boundaries, and velocity metric are not defined. |
| 40 | Weekly competitive briefing for oncology. | 🟡 | Weekly personalized email digests now exist; competitor-focused narrative and delivery QA remain incomplete. |

**Provisional score: 2 Strong, 5 Partial, 1 Needs Work, 2 Cannot**

---

## Category 5: Due Diligence & Deal Execution

| # | Question | Rating | Current assessment |
|---|---|---:|---|
| 41 | Full DD on Company X. | 🟡 | Overview, deals, drugs, partners, financials, and basic risks are populated; four sections are empty. |
| 42 | What territories are available for Drug Y? | ✅ | Territory-rights endpoint and UI report committed/terminated records. |
| 43 | Contracts mentioning royalty rates for this drug. | 🟡 | 25,978 contracts/897,130 chunks are searchable; exact drug scoping and structured extraction need validation. |
| 44 | Risk flags for this acquisition target. | 🟡 | Basic heuristic flags exist, but litigation, filings, contracts, clinical, and financial-risk evidence are absent. |
| 45 | Export a comp set with deal values to Excel. | 🔧 | Comp PowerPoint export is shipped; comp-specific Excel export is not. |
| 46 | What SEC filings relate to this deal? | 🟡 | 66,980 candidate links exist, but only 692 CIK mappings and date-proximity matching needs precision review. |
| 47 | Milestone structure for comparable deals. | 🔧 | No milestone-specific comp view or governed extraction table. |
| 48 | IP landscape for KRAS inhibitors. | ❌ | Limited deal-linked patent metadata exists, but not claims/families/status/assignee coverage for an IP landscape. |
| 49 | Timeline of all deals for this target company. | ✅ | Company timeline is directly supported after canonical entity selection. |
| 50 | Who else licensed this company's technology? | ✅ | Partner graph and deal history support the lookup. |

**Provisional score: 3 Strong, 4 Partial, 2 Needs Work, 1 Cannot**

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

**Provisional score: 3 Strong, 6 Partial, 1 Cannot**

---

## Category 7: SEC Filing Intelligence

| # | Question | Rating | Current assessment |
|---|---|---:|---|
| 61 | Find 8-K filings mentioning ADC partnerships. | 🟡 | Full-text is fast, but form filtering uses the wrong column and the historical backfill has a gap. |
| 62 | Show Pfizer's 10-K risk factors. | 🟡 | Generic sections and a section endpoint exist; reliable form-aware Item 1A extraction/filtering is incomplete. |
| 63 | Cross-reference this Cortellis deal with SEC filings. | 🟡 | Matcher is implemented with 66,980 links; company/date candidates need content-based ranking and precision evaluation. |
| 64 | Material contracts from recent 8-K filings. | 🟡 | Recent ingestion extracts EX-10 exhibits, but form/subtype filtering and backlog coverage must be corrected. |
| 65 | S-1 analysis for a pre-IPO biotech. | 🟡 | S-1 text is searchable; structured pipeline/financial/risk extraction is incomplete. |

**Provisional score: 5 Partial**

---

## Provisional Scorecard

This is a conservative code-and-smoke-test review, not the final measured score.

| Category | Strong ✅ | Partial 🟡 | Needs Work 🔧 | Cannot ❌ | Total |
|---|---:|---:|---:|---:|---:|
| Quick Factual | 3 | 7 | 0 | 0 | 10 |
| Analytical | 5 | 3 | 2 | 0 | 10 |
| Strategic | 0 | 8 | 1 | 1 | 10 |
| Competitive Intelligence | 2 | 5 | 1 | 2 | 10 |
| Due Diligence | 3 | 4 | 2 | 1 | 10 |
| Market Landscape | 3 | 6 | 0 | 1 | 10 |
| SEC Filings | 0 | 5 | 0 | 0 | 5 |
| **Total** | **16** | **38** | **6** | **5** | **65** |

**Provisional: 16/65 Strong (25%); 54/65 at least Partial (83%).**

The breadth remains useful, but correctness and grounding—not feature count—are
the limiting factors.

## Executable Evaluation Specification

The 65 questions should become versioned fixtures. The first five production
regressions are now represented in `unified_api/evals/question_cases.yaml`; the
remaining 60 still need truth fixtures. Each case must include:

```yaml
id: 1
question: How many deals did Pfizer do in 2024?
channel: chat_v2
entities:
  company_ids: [18767]
expected:
  type: scalar
  value: 23
  tolerance: 0
required_evidence:
  - generated_query
  - source_record_count
latency_budget_seconds: 10
dataset_as_of: 2026-07-11
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
2. Governed metric definitions for upfront, milestones, royalties, total value,
   announced/closed dates, acquisition premium, and phase-at-deal.
3. ✅ Evidence-only synthesis: refuse or clearly return “not found” on empty results.
4. Source references and meaningful confidence/provenance in Chat v2.
5. 🟡 Executable golden-set harness seeded with 5 of 65 questions.

### P1 — Broken or incomplete workflows

6. 🟡 Fix EDGAR form filtering to use `subtype` (implemented); complete the
   historical backfill (remaining).
7. ✅ Apply modality during comp candidate retrieval.
8. Populate DD SEC filing, contract, territory, and comparable-transaction sections.
9. Add content-based validation/ranking to deal–filing links.
10. ✅ Fix the agentic-RAG tests and tool async boundaries.

### P2 — Higher-value expansion

11. Milestone and royalty extraction/analytics.
12. Dynamic company comparison and “my company” configuration.
13. Target screening, new-entrant detection, and strategy summaries after grounding.
14. Board/quarterly report templates and analytics PDF export.
15. ClinicalTrials.gov/AACT and broader asset/indication enrichment.

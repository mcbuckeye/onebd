# BD Intelligence Platform - Priority Implementation Checklist

## 2026 Continuing Improvement Roadmap

The next phase prioritizes trustworthy deployments, observable data freshness,
and fast retrieval before adding more external data volume.

1. **Repair and verify Dokploy automatic deployment**
   - [x] A push to `main` creates a Dokploy deployment record and queue job.
   - [x] The checkout advances to the pushed SHA and affected services rebuild.
   - [x] Health checks pass and the deployed SHA is visible from the API image.
   - [x] A post-Dokploy GitHub workflow waits for the expected SHA and visibly
         fails if deployment health or the five production regressions fail.
   - [x] Add a concurrency-safe automated revert after a failed production gate;
         the revert passes the protected pre-deploy checks, redeploys through the
         existing GitHub/Dokploy integration, and is verified in production.
         Controlled run `29166857870` intentionally failed deployed SHA
         `9fce3f4`, merged protected rollback PR #19, served rollback SHA
         `34340b2`, and passed the production regressions and EDGAR latency gate.

2. **Separate current EDGAR ingestion from historical backfill**
   - [x] A recent-data lane always processes the latest SEC business days.
   - [x] A separate resumable cursor advances the historical backlog.
   - [x] Both lanes remain idempotent and safe when their windows overlap.
   - [ ] Run bounded catch-up jobs until the historical cursor reaches current data.
         A verified manual run advanced 2025-11-23 through 2025-11-30 and added
         139 filings, 275 documents, and 3,653 chunks without error.
   - [x] Persist append-only recent/backfill run history and report observed
         cursor throughput, filings/hour, remaining runs, and estimated catch-up.

3. **Add unified source-sync monitoring and alerts**
   - [x] Persist a common last-attempt, last-success, status, exponential retry
         advisory, consecutive-failure, error, and alert-transition model for
         Cortellis, both EDGAR lanes, and Neo4j graph syncs.
   - [x] Standardize cursor, source-data date, lag, duration, and count fields in
         a versioned common payload for every instrumented source job.
   - [x] Report those fields plus throughput and ETA for both EDGAR lanes; retry
         state still needs a common model across Cortellis and graph syncs.
   - [x] Mark `/api/health/data` degraded when a source exceeds its lag budget.
   - [x] Treat partial source runs as degraded even when their timestamp is fresh.
   - [x] Add deduplicated warning/critical/recovery events for failed or stale
         Cortellis, EDGAR, and graph jobs, with optional webhook/email delivery
         and durable in-app history when no delivery channel is configured.
   - [x] Add a credential-free external operations channel: a scheduled GitHub
         workflow opens one deduplicated source-health issue and closes it on
         recovery; webhook/email delivery remains available when configured.

4. **Verify and harden Cortellis incremental synchronization**
   - [x] Compare the API's newest modified deals with the local watermark.
   - [x] Use an overlap window so date-only API filters cannot skip same-day updates.
   - [x] Validate zero-result runs against a nonempty source catalog and reject
         future/stale watermarks instead of advancing them as successful.
   - [x] Mark omitted/failed API batches partial so the last successful watermark
         remains eligible for retry, and expose the batch error from the worker.
   - [x] Add regression tests for midnight, same-day, timezone, and retry boundaries.
   - [x] Compare the advertised API catalog count with the local count on every
         incremental run and mark a mismatch partial instead of claiming success.
   - [x] Add a weekly full-ID reconciliation that restores historical omissions
         in bounded API batches without deleting local-only records.
   - [ ] Complete the first reconciliation: the 2026-07-13 audit found 149,006
         source deals versus 146,931 local deals (2,075 missing before repair).
   - [ ] Complete a durable all-deal contract metadata scan; 41,626 contracts are
         local, but only 16,194 deals currently have a persisted checked state.

5. **Improve EDGAR full-text and semantic-search performance**
   - [x] Rank a bounded indexed candidate set instead of every matching chunk.
   - [x] Capture representative `EXPLAIN (ANALYZE, BUFFERS)` plans for common,
         filtered, rare-term, and 40-probe vector searches in production.
   - [x] Create the production IVFFlat cosine index on `chunks.vector`, configure
         semantic queries with 40 probes, and make the integrity test blocking.
   - [x] Remove the unused duplicate 994 MB GIN index concurrently after proving
         equivalence and retaining the index selected by PostgreSQL.
   - [x] Add a deployable HTTP latency smoke budget for common and filtered terms.
   - [x] Enforce common and filtered EDGAR HTTP latency budgets after every
         production deployment and again after any automated rollback.

6. **Make builds reproducible and establish CI deployment gates**
   - [x] Pin direct Python dependencies and API/frontend container base images.
   - [x] Use `npm ci` with the committed frontend lockfile.
   - [x] Resolve frontend dependency audit findings (zero vulnerabilities on
         2026-07-11 after the Vite/Axios/router updates).
   - [x] Fix the existing agentic-RAG test failures.
   - [x] Add a GitHub Actions quality gate for the 65-case catalog, unit tests,
         critical lint, frontend build/audit, and Compose validation.
   - [x] Protect `main` with required `backend`, `frontend`, and `compose` checks;
         Dokploy only receives normal merged commits after those checks pass.

7. **Improve canonical company and asset identity resolution**
   - [x] Promote cross-source normalized-exact legal names and seed alias records.
         Production now has 2,890 aliases across all 1,648 xrefs and 48.9%
         high-confidence matches (up from 19.5%).
   - [x] Add a provenance-aware parent/subsidiary relationship model without
         silently rolling subsidiaries into parents.
   - [ ] Add LEI/domain identifiers and populate reviewed ownership relationships.
   - [x] Add provenance/review schemas for company LEIs/domains and public drug
         identifiers; external identifier population remains pending.
   - [x] Add conservative, resumable exact-name PubChem enrichment for CID,
         InChIKey, connectivity SMILES, and source-verified public titles.
   - [ ] Normalize INN/development codes and add ChEMBL/UniProt/Open Targets IDs.
   - [x] Seed normalized Cortellis display names and conservative development-code
         candidates for all drugs without treating organization suffixes as aliases.
   - [x] Store match evidence, confidence, method, review status, reviewer, and
         source reference for company aliases/identifiers, ownership, and drugs.
   - [x] Replace the per-deal EDGAR session/query loop with bounded bulk queries,
         an indexed in-memory date join, and batched idempotent inserts.

8. **Add ClinicalTrials.gov/AACT as the first new external source**
   - [ ] Link trials to existing companies, assets, indications, and targets.
   - [ ] Preserve sponsor, phase, status history, endpoints, enrollment, dates,
         results, collaborators, and locations with source provenance.
   - [ ] Detect upcoming catalysts, stopped programs, and status changes.

9. **Refactor reusable Mammal public-data clients**
   - [ ] Share rate limiting, caching, retry, identifier normalization, source
         freshness, and provenance primitives.
   - [ ] Adapt Open Targets, ChEMBL, PubChem, UniProt, Europe PMC, and
         ClinicalTrials.gov without coupling OneBD to BeOne-specific CSV outputs.

10. **Build higher-value intelligence workflows after the foundation is stable**
    - [x] Normalize Cortellis JSON upfront, milestone, and royalty terms into a
          provenance-preserving beta table with resumable scheduled extraction.
    - [ ] Validate extracted term precision/coverage before enabling governed
          aggregate answers; add contract-derived scale-clause extraction.
          Parser-v2 audit found 1,818 `B`/`T` values scaled incorrectly and 2,343
          known percentage terms without bounds. Parser v3 and a deterministic
          population/sample validation gate are being deployed before release.
    - [ ] Deal-to-trial and deal-to-regulatory-event timelines.
    - [ ] Company strategy summaries, competitive maps, and new-entrant alerts.
    - [ ] Catalyst calendars, scheduled reports, and decision-ready exports.

### Immediate Reliability Sprint

- [x] Repair and prove the GitHub-to-Dokploy deployment path.
- [x] Deploy independent EDGAR recent and backfill jobs.
- [x] Expose actionable source freshness and lag in health reporting.
- [x] Prove and correct Cortellis incremental watermark behavior.
- [x] Reduce representative EDGAR full-text search latency to seconds or less.

### Evaluation Trustworthiness Sprint

- [x] Regrade the 65-question evaluation using end-to-end correctness criteria.
- [x] Resolve unambiguous company mentions to canonical IDs before SQL generation.
- [x] Refuse unsupported milestone/premium metrics instead of substituting total value.
- [x] Prevent synthesis from adding claims when no populated evidence is returned.
- [x] Fix EDGAR form filters to use the actual filing subtype.
- [x] Apply requested modality filters before comp-set candidate ranking.
- [x] Seed an executable evaluation harness with the first five regression cases.
- [x] Convert all 65 questions into executable, versioned fixtures: 5 blocking
      regression truths and 60 catalog probes awaiting deterministic truth values.
- [x] Publish governed definitions for supported and unsupported financial metrics.
- [x] Return source IDs/query provenance and evidence status from Chat v2.
- [x] Validate the full catalog and regression harness in CI.
- [x] Require every Strong-rated case to compare the deployed response with a
      read-only database truth query. Ten cases now meet this standard; six
      optimistic/context-dependent ratings were downgraded pending real proof.
- [x] Replace each remaining catalog probe's basic response assertion with
      deterministic truth or an evidence-scored narrative rubric. All 65 cases
      now have an oracle: 11 run read-only database truth comparisons and 55 run
      scored grounding/provenance rubrics (Roche strategy uses both).

## Implementation Status vs PRD

### ✅ Phase 0: System Integration Foundation (COMPLETE)
- [x] Unified Docker Compose
- [x] Neo4j deployment
- [x] Entity Resolution service (692 companies linked)
- [x] Graph Population (55K companies, 145K deals, 289K relationships)
- [x] Unified API scaffold
- [x] Celery workers

### ✅ Phase 1: Unified Search & Profiles (MOSTLY COMPLETE)
- [x] Query router (SQL/RAG/Graph)
- [x] Advanced deal search with multi-criteria filters
- [x] **Company profile enhancement** (`/company/{id}/profile` endpoint)
- [x] **Drug/asset profile page** (`/drug/{id}/profile` endpoint)
- [ ] SEC filing viewer
- [ ] User accounts
- [x] Export (Excel/CSV) - Added `/export/deals/excel`, `/export/search-results/excel`

### ✅ Phase 2-5: Mostly Complete
- [x] Analytics dashboards (13 endpoints: trends, valuations, geographic, M&A, heatmap, YoY growth)
- [x] Network visualization API (`/graph/partnership-network/{id}`, `/graph/industry-network`)
- [x] Watchlists/alerts (tables + endpoints created)
- [x] Contract NLP extraction (GPT-4o clause extraction + term comparison)
- [ ] Team collaboration
- [ ] User accounts

---

## Completed Features ✅

### 1. Company Intelligence Profile (F3) ✅
**Status:** ✅ COMPLETE
**Endpoint:** `GET /api/company/{company_id}/profile`

Features:
- [x] Deal count by role (Principal/Partner)
- [x] Deal timeline by year
- [x] Top 10 partners by deal count
- [x] Therapeutic focus distribution (indications)
- [x] Financial summary (avg/total deal value)
- [x] Recent activity (last 12 months)
- [x] Associated drugs/assets with phase
- [x] SEC filing integration (if CIK matched)

---

### 2. Export to Excel/CSV (F12) ✅
**Status:** ✅ COMPLETE

Endpoints:
- [x] `POST /api/export/deals/csv` - Export deals with filters
- [x] `POST /api/export/deals/excel` - Export deals to Excel
- [x] `GET /api/export/company/{id}/deals/csv` - Company deals CSV
- [x] `GET /api/export/company/{id}/deals/excel` - Company deals Excel
- [x] `GET /api/export/search-results/excel` - Advanced search to Excel
- [x] `GET /api/export/analytics/market-trends/csv` - Trends export
- [x] `GET /api/export/analytics/valuations/csv` - Valuations export

---

### 3. Partnership Network API (F7) ✅
**Status:** ✅ COMPLETE

Endpoints:
- [x] `GET /api/graph/partnership-network/{company_id}` - D3.js-compatible network
- [x] `GET /api/graph/company/{id}/partners-summary` - Detailed partner list
- [x] `GET /api/graph/industry-network` - Industry-wide network
- [x] `GET /api/graph/network/{company_id}` - Full network with deals
- [x] `GET /api/graph/top-partners` - Top partners by deal count
- [x] `GET /api/graph/path` - Find path between companies
- [x] `GET /api/graph/deals-between` - Deals between two companies

---

### 4. Deal Watchlist & Notes (F14) ✅
**Status:** ✅ COMPLETE

Tables created:
- [x] `user_watchlist` - Track deals with status/tags
- [x] `deal_notes` - Personal notes on deals
- [x] `saved_searches` - Save search criteria (with alert flag)

Endpoints:
- [x] `GET /api/watchlist` - Get user's watchlist
- [x] `POST /api/watchlist` - Add deal to watchlist
- [x] `PATCH /api/watchlist/{deal_id}` - Update status/tags
- [x] `DELETE /api/watchlist/{deal_id}` - Remove from watchlist
- [x] `GET /api/watchlist/stats` - Watchlist statistics
- [x] `GET /api/deals/{deal_id}/notes` - Get notes for deal
- [x] `POST /api/deals/{deal_id}/notes` - Create note
- [x] `PATCH /api/notes/{note_id}` - Update note
- [x] `DELETE /api/notes/{note_id}` - Delete note
- [x] `GET /api/saved-searches` - Get saved searches
- [x] `POST /api/saved-searches` - Create saved search
- [x] `DELETE /api/saved-searches/{id}` - Delete saved search

---

## Remaining Priorities

### 5. New Deal Alerts (F2) ✅
**Status:** ✅ COMPLETE

Implemented:
- [x] Celery task for daily alert check (`check_alerts` runs at 8:00 AM)
- [x] In-app notification endpoint (`GET /api/notifications`)
- [x] Manual trigger endpoint (`POST /api/alerts/trigger`)
- [ ] Email notification integration (SendGrid/SES) - Future enhancement

---

### 6. Entity Resolution Coverage ✅
**Status:** ✅ COMPLETE (692 companies linked, only 2 were missing from Edgar)

Completed:
- [x] Entity resolution at 100% coverage for matched companies
- [x] Added missing Edgar companies (Novartis AG, Roche Holding Ltd)
- [x] 173 SEC filings imported for new companies

---

### 7. Drug/Asset Profile Page ✅
**Status:** ✅ COMPLETE
**Endpoint:** `GET /api/drug/{drug_id}/profile`

Features:
- [x] Drug overview (name, phase, indication)
- [x] Complete deal history for drug
- [x] Current rights holders by territory
- [x] Financial summary across deals
- [x] Related companies (owners/partners)

---

## Improvement Opportunities

### Data Quality
- [x] **Entity Resolution Coverage** - 692 companies linked via CIK, missing companies added
- [x] **Financial Data Toggle** - "disclosed_only" filter available in search
- [x] **Company Deduplication** - Duplicate detection + merge workflow (`/xref/duplicates`, `/xref/merge-companies`)

### Performance
- [x] **Redis Query Caching** - Caching service with TTL for analytics/autocomplete (`services/cache.py`)
- [x] **Materialized Views** - 4 MVs: market trends, agreement types, therapy areas, company stats
- [x] **Neo4j Composite Indexes** - 4 composite indexes on Company/Deal nodes

### Search Enhancement
- [x] **Autocomplete for Filters** - Typeahead for companies, indications, and drugs
- [x] **Saved Searches** - Users can save and name filter combinations
- [x] **Search History** - Track and retrieve recent searches

### Contract Intelligence
- [x] **Clause Extraction Pipeline** - GPT-4o extraction of royalty rates, milestones, license scope
- [x] **Term Comparison** - Side-by-side deal comparison with financials, milestones, drugs

---

## Session Summary

### Session 1 - Completed:
1. ✅ Verified Company Intelligence Profile endpoint (already existed)
2. ✅ Added Excel export functionality (3 new endpoints)
3. ✅ Added D3.js-optimized Partnership Network API (3 new endpoints)
4. ✅ Created Watchlist tables and endpoints (3 tables, 11 endpoints)

### Session 2 - Completed:
1. ✅ Created Drug/Asset Profile endpoint (`GET /api/drug/{id}/profile`)
2. ✅ Created Deal Alerts Celery task (daily at 8:00 AM)
3. ✅ Added Notifications API endpoints
4. ✅ Added missing Edgar companies (Novartis AG, Roche Holding Ltd)
5. ✅ Imported 173 SEC filings for new companies

### Session 3 - Completed:
1. ✅ Analytics dashboard endpoints (7 new: geographic, agreement type, status funnel, therapy heatmap, M&A, company comparison, YoY growth)
2. ✅ SEC filing viewer (content viewer, sections, related-deals cross-reference)
3. ✅ Redis query caching service (`services/cache.py`)
4. ✅ 4 Materialized views (market trends, agreement types, therapy areas, company stats)
5. ✅ 4 Neo4j composite indexes
6. ✅ Autocomplete for companies, indications, drugs
7. ✅ Search history tracking (record, retrieve, clear)
8. ✅ Company deduplication (duplicate detection + merge workflow)
9. ✅ Clause extraction pipeline (GPT-4o NLP)
10. ✅ Term comparison (side-by-side deal analysis)

### New Files Created:
- `unified_api/routers/watchlist.py` - Watchlist, notes, and notifications endpoints
- `unified_api/routers/contracts.py` - Contract intelligence (clause extraction, term comparison)
- `unified_api/services/cache.py` - Redis caching service
- `unified_api/services/clause_extractor.py` - GPT-4o clause extraction
- `unified_api/scripts/create_watchlist_tables.py` - Migration script
- `unified_api/scripts/add_missing_edgar_companies.py` - Edgar data gap filler

### Files Modified:
- `unified_api/routers/analytics.py` - 7 new dashboard endpoints + cache
- `unified_api/routers/edgar.py` - Filing viewer, sections, related-deals
- `unified_api/routers/search.py` - Autocomplete + search history
- `unified_api/routers/xref.py` - Deduplication + merge
- `unified_api/routers/export.py` - Excel export endpoints
- `unified_api/routers/graph.py` - D3 network visualization endpoints
- `unified_api/routers/entities.py` - Drug Profile endpoint
- `unified_api/workers/celery_app.py` - Alert check + MV refresh tasks
- `unified_api/main.py` - Registered contracts router
- `unified_api/requirements.txt` - Added openpyxl dependency

### All API Endpoints (Total: 50+)
| Category | Endpoint | Method |
|----------|----------|--------|
| **Analytics** | `/api/analytics/market-trends` | GET |
| | `/api/analytics/valuations/by-phase` | GET |
| | `/api/analytics/valuations/by-indication` | GET |
| | `/api/analytics/valuations/by-deal-type` | GET |
| | `/api/analytics/top-deals` | GET |
| | `/api/analytics/top-acquirers` | GET |
| | `/api/analytics/deal-activity-summary` | GET |
| | `/api/analytics/geographic-distribution` | GET |
| | `/api/analytics/agreement-type-distribution` | GET |
| | `/api/analytics/deal-status-funnel` | GET |
| | `/api/analytics/therapy-area-heatmap` | GET |
| | `/api/analytics/ma-analytics` | GET |
| | `/api/analytics/company-comparison` | GET |
| | `/api/analytics/yoy-growth` | GET |
| | `/api/analytics/cache/invalidate` | POST |
| **Filing Viewer** | `/api/edgar/filings/{id}/content` | GET |
| | `/api/edgar/filings/{id}/sections` | GET |
| | `/api/edgar/filings/{id}/related-deals` | GET |
| **Autocomplete** | `/api/search/autocomplete/companies` | GET |
| | `/api/search/autocomplete/indications` | GET |
| | `/api/search/autocomplete/drugs` | GET |
| **Search History** | `/api/search/history` | GET, POST, DELETE |
| **Deduplication** | `/api/xref/duplicates` | GET |
| | `/api/xref/merge-companies` | POST |
| **Contracts** | `/api/contracts/extract-clauses` | POST |
| | `/api/contracts/{deal_id}/clauses` | GET |
| | `/api/contracts/compare` | GET |
| **Export** | `/api/export/deals/excel` | POST |
| | `/api/export/company/{id}/deals/excel` | GET |
| | `/api/export/search-results/excel` | GET |
| **Graph** | `/api/graph/partnership-network/{id}` | GET |
| | `/api/graph/company/{id}/partners-summary` | GET |
| | `/api/graph/industry-network` | GET |
| **Watchlist** | `/api/watchlist` | GET, POST |
| | `/api/watchlist/{deal_id}` | PATCH, DELETE |
| | `/api/watchlist/stats` | GET |
| **Notes** | `/api/deals/{deal_id}/notes` | GET, POST |
| | `/api/notes/{note_id}` | PATCH, DELETE |
| **Saved Searches** | `/api/saved-searches` | GET, POST |
| | `/api/saved-searches/{id}` | DELETE |
| **Notifications** | `/api/notifications` | GET |
| | `/api/notifications/{id}` | DELETE |
| **Alerts** | `/api/alerts/trigger` | POST |
| **Drug Profile** | `/api/drug/{id}/profile` | GET |

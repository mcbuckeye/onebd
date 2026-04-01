# PageIndex Enhancement Roadmap — OneBD

> Last updated: 2026-04-01
> Status: ALL PHASES COMPLETE. 143 tests, ~8,000 LOC added across 2 days.

## ✅ Phase 1: Core Integration (COMPLETE)
- [x] HTML cleaner service (40 tests)
- [x] Tree cache table + service (18 tests)
- [x] PageIndex agentic RAG tool (13 tests)
- [x] Agent keyword routing + router wiring
- [x] Clause extractor upgrade — tree-guided (9 tests)
- [x] DB table on MachomeLab, vendored PageIndex, live-tested 4/4

---

## Phase 2: Scale & Pre-indexing
*Goal: Make every contract query instant, extract structured data at scale.*

### 2A. Batch Pre-index Top Contracts
Celery task to pre-generate PageIndex trees for the largest contracts. Run overnight. First user query on any pre-indexed deal is instant (2-5s instead of 19s+).
- Management command: iterate `contract_content` by `word_count DESC`
- Target: top 500-1000 contracts (covers all deals >10K words)
- Skip contracts that already have cached trees
- Log progress, report failures

### 2B. Auto-extract and Cache Clause Data
When a tree is generated (batch or on-demand), automatically run tree-guided clause extraction and store structured output in a new `contract_extracted_clauses` JSONB column on `contract_content`.
- Extracted fields: upfront, royalties, milestones, termination, license scope, territories
- Makes structured fields SQL-queryable: "deals with upfront > $50M"
- Incremental: only extract for contracts that don't have cached extractions

### 2C. Multi-contract Queries
Upgrade PageIndex tool to accept multiple deal_ids. Agent uses SQL/Neo4j to find relevant deals, then PageIndex reads each contract, then synthesizes a comparison.
- Query format: `deal_ids:150059,107441,112856 Compare the milestone structures`
- Agent orchestration: SQL finds deals → PageIndex reads each → LLM synthesizes comparison
- Limit: max 5 contracts per query (cost control)

---

## Phase 3: Advanced Retrieval & UX

### 3A. PDF Support
Index original SEC/EDGAR PDF filings directly (not just HTML text). PageIndex PDF mode gives page-number citations instead of line numbers.
- Use `deal_contracts.pdf_file_path` for source PDFs
- Store PDF trees alongside markdown trees in cache
- Prefer PDF tree when available (better page references)

### 3B. Contract Comparison Endpoint Upgrade
Upgrade existing `/contracts/compare` to do full-text contract comparison using PageIndex.
- Compare royalty structures, termination provisions, IP ownership across 2-5 deals
- Output: side-by-side structured comparison table + narrative summary
- BD analyst workflow: "How does this deal compare to the last 3 ADC licensing deals?"

### 3C. Streaming Answers with Reasoning Trace
Wire up `/agentic-rag/chat/stream` (currently 501) to show real-time reasoning:
- "Finding contract..." → "Checking tree cache..." → "Searching Section 7: Financial Terms..." → "Answer found in Section 7.1"
- SSE events with reasoning step metadata
- Frontend shows agent thinking in real-time, builds trust

---

## Phase 4: Domain Expansion

### 4A. Clinical Protocol Analyzer
Dedicated mode for clinical study protocols. Upload PDF, auto-index, query.
- Optimized prompts for clinical questions (endpoints, I/E criteria, dosing, sample size, safety)
- Protocol-specific tree navigation (knows protocol structure)
- Could be standalone feature or OneBD module for clinical ops team

### 4B. Clinical Evidence Library (JVO FEATURE)
Curated, pre-indexed library of clinical evidence documents for competitive intelligence.
Enables queries like: "Compare PFS rates at 12/24/36 months across BTK inhibitors in B-cell malignancies."

**Document types to index:**
- FDA prescribing labels (Drugs@FDA PDFs) — approved indications, efficacy tables, safety
- Pivotal trial publications (NEJM, Lancet, JCO) — landmark PFS/OS rates, Kaplan-Meier data
- FDA briefing documents — ODAC advisory committee reviews (200-500 pages)
- EMA assessment reports (EPARs) — European regulatory assessments
- NCCN guidelines — treatment algorithms, comparative recommendations

**Initial therapeutic areas (BeiGene priority):**
- BTK inhibitors: zanubrutinib (Brukinsa), acalabrutinib (Calquence), ibrutinib (Imbruvica), pirtobrutinib (Jaypirca)
- B-cell malignancies: CLL/SLL, MCL, WM, MZL, FL, DLBCL
- PD-1/PD-L1: tislelizumab (Tevimbra) competitive landscape
- ADCs in hematology and solid tumors

**Architecture:**
- New `evidence_documents` table: doc_id, drug_name, doc_type (label/publication/briefing), therapeutic_area, source_url, pdf_path, tree_cached
- New `evidence_tree_index` table: mirrors `contract_tree_index` for evidence docs
- Celery task to fetch and index FDA labels automatically from Drugs@FDA
- New agentic RAG tool: `EvidenceTool` — searches across multiple drugs' evidence
- Multi-document synthesis: agent reads relevant docs for each drug, then compares

**PoC validated (2026-03-31):** Successfully indexed and queried FDA labels for Brukinsa, Calquence, and Imbruvica. Generated competitive comparison table with PFS, CR, and ORR data across B-cell malignancies. Limitation: FDA labels have median PFS/HRs but not always landmark rates — need published trial manuscripts for 12/24/36-month data.

### 4C. Regulatory Document Search
Index FDA briefing documents, EMA assessment reports, advisory committee transcripts.
- 200-500 page PDFs with complex cross-references
- Tree-based retrieval handles nested regulatory document structure
- Pre-index key regulatory docs for top therapeutic areas

### 4D. Deal Alerts with Contract Intelligence
When new contracts appear via `cortellis-sync`, auto-index and extract key terms.
- Push summary to Telegram: "New Pfizer/BioNTech collaboration — $200M upfront, 8% royalty"
- Celery task triggered on new `contract_content` rows
- Uses tree-guided extraction for structured deal terms

---

## Build Status
| # | Item | Tests | Status | Date |
|---|------|-------|--------|------|
| 1 | **2A** Batch pre-index | 9 | ✅ | 2026-04-01 |
| 2 | **2C** Multi-contract queries | 7 | ✅ | 2026-04-01 |
| 3 | **2B** Auto-extract clauses | 6 | ✅ | 2026-04-01 |
| 4 | **4B** Clinical Evidence Library | 8 | ✅ | 2026-04-01 |
| 5 | **3C** Streaming answers | 7 | ✅ | 2026-04-01 |
| 6 | **3B** Contract comparison | 3 | ✅ | 2026-04-01 |
| 7 | **3A** PDF support | 4 | ✅ | 2026-04-01 |
| 8 | **4D** Deal alerts | 4 | ✅ | 2026-04-01 |
| 9 | **4A** Protocol analyzer | 11 | ✅ | 2026-04-01 |
| 10 | **4C** Regulatory docs | 4 | ✅ | 2026-04-01 |
| — | **Phase 1** (core) | 80 | ✅ | 2026-03-31 |
| **Total** | | **143** | | |

## Principles
- TDD on everything — tests first, no exceptions
- Each enhancement is a clean commit with its own tests
- Sub-agents for implementation, review between each
- No infrastructure changes — everything runs inside existing OneBD stack
- Cost control: cache aggressively, limit concurrent LLM calls

# BD Intelligence Platform — Product Requirements Document
## Version 2.0

---

## Executive Summary

The BD Intelligence Platform is a strategic decision-support system for pharmaceutical business development. It combines the Cortellis deals database (145K+ deals), SEC EDGAR filings (314K+ documents), and a Neo4j graph layer (55K+ companies, 289K+ relationships) into a unified intelligence platform that serves every level of the BD organization — from the CEO asking "Should we build, buy, or partner in solid tumors?" to the analyst compiling comparable deal terms for a negotiation.

This PRD defines the complete vision: a multi-modal interface system that adapts to the user's intent, from one-line natural language questions to structured multi-criteria analysis to automated strategic briefings.

---

## 1. Design Philosophy: Multiple Operating Modes

The platform's primary user — CEO John Oyler — is an MIT engineering graduate, Stanford MBA, and former McKinsey consultant. He thinks in frameworks, wants data-backed answers fast, and will shift fluidly between quick strategic questions and deep analytical dives. The platform must match that fluidity.

### 1.1 The Five Interaction Modes

| Mode | Interface | User Intent | Response Time | Example |
|------|-----------|-------------|---------------|---------|
| **Ask** | Natural language chat | Quick answer with supporting data | < 10 seconds | "How many ADC deals closed last quarter?" |
| **Explore** | Visual dashboards | Scan landscape, spot patterns | Instant (pre-computed) | Open Market Trends → filter to Oncology → see deal volume spike |
| **Search** | Structured filters + results table | Find specific deals matching criteria | < 3 seconds | Phase 2+ / Solid tumors / ADC / 2022-2025 / Disclosed value > $500M |
| **Analyze** | Comp builder, benchmarks, network graphs | Deep analytical work, prepare materials | Interactive (multi-step) | Build comp set for bispecific lung cancer asset → export to Excel |
| **Brief** | Auto-generated reports, email digests | Stay informed without logging in | Scheduled (daily/weekly) | Monday morning: "3 new deals in your tracked indications" |

**Principle:** Every insight available through one mode should be reachable from any other mode. Ask a question in chat → get an answer with a "View in Dashboard" link. See a trend in analytics → click to get the underlying deals. The modes are entry points, not silos.

### 1.2 The "Ask" Mode — Conversational Intelligence

This is the CEO's default mode. Type a question, get an answer — not a table of raw data, but a synthesized response with:

- **Direct answer** in plain language
- **Supporting data** (numbers, charts, tables embedded inline)
- **Confidence indicator** (how complete is the underlying data)
- **Follow-up suggestions** (what related questions matter)
- **Action links** (save this search, add to watchlist, export, view full dashboard)

The system must handle a spectrum of query complexity:

**Simple factual:**
> "How many deals did Pfizer do in 2024?"
→ "Pfizer completed 47 deals in 2024, up from 38 in 2023. 12 were oncology-related. [View Pfizer Profile] [View Deals]"

**Analytical:**
> "What are typical upfront payments for Phase 2 oncology ADC assets?"
→ "Based on 23 disclosed Phase 2 ADC deals in oncology (2019-2025), median upfront payment is $150M (IQR: $75M-$300M). The trend is increasing — 2024 median was $200M vs $100M in 2020. [View Deals] [Build Comp Set]"
→ Inline box-plot chart

**Strategic / Recommendation:**
> "We're considering acquiring a company with a Phase 2 bispecific in NSCLC. What should we expect to pay?"
→ Synthesized briefing: comparable M&A transactions, valuation benchmarks by phase/modality, recent market trends, key risk factors (pipeline concentration, IP landscape). Sources cited for every data point.
→ "Based on 8 comparable acquisitions, expect $800M-$2.5B total consideration. Key drivers: Phase 2 data readout proximity, indication breadth, and manufacturing platform value. [Full Analysis] [Export Briefing]"

**Implementation:** The existing chat endpoint (`/api/chat`) routes to SQL or RAG. Enhance it with:
- A reasoning layer that classifies query intent (factual / analytical / strategic)
- A response formatter that synthesizes data into narrative + visuals
- An action bar that connects chat answers to the rest of the platform
- Conversation memory within a session (follow-up questions reference prior context)

---

## 2. Target Users & Personas

### 2.1 Primary: CEO (John Oyler)

**Profile:** MIT engineering, Stanford MBA, McKinsey background. Thinks in frameworks. Wants defensible data, not opinions. Comfortable with both a quick question and a structured 2x2 matrix.

**Daily workflow:**
- Morning: Glance at executive dashboard — any notable deals overnight? Any alerts?
- Ad-hoc: Ask questions during meetings — "What's the biggest ADC deal ever?" (needs answer in 10 seconds)
- Weekly: Review competitive landscape, check tracked companies/indications
- Strategic: Deep dives on acquisition targets — wants the full DD picture

**What he does NOT want:**
- Raw data dumps without synthesis
- Answers without confidence levels or source attribution
- Having to learn a query language or complex UI to get basic answers
- Stale data — if a deal closed yesterday, he expects to see it

### 2.2 Secondary: VP/Head of Business Development

**Daily workflow:**
- Run structured searches for deal opportunities
- Build comp sets for active negotiations
- Monitor competitor deal activity
- Prepare briefing materials for CEO/board

**Key needs:**
- Multi-criteria search that's faster than manual Excel filtering
- Comp builder with export to Excel/PowerPoint
- Competitor tracking with alerts
- Deal pipeline management (watchlist with status tracking)

### 2.3 Tertiary: BD Associate / Analyst

**Daily workflow:**
- Research target companies and assets
- Compile deal histories and financial data
- Draft company profiles and market maps
- Maintain watchlists and track deal progress

**Key needs:**
- Efficient data gathering across all sources (deals + filings + contracts + graph)
- Export and formatting tools
- Saved searches and templates
- Collaboration features (share findings with team)

---

## 3. Platform Architecture

### 3.1 Current State (Built)

| Layer | Technology | Status |
|-------|-----------|--------|
| **Frontend** | React + Vite + TypeScript + Tailwind | Chat-only interface (5 components, 1,442 LOC) |
| **API** | FastAPI (unified_api/) | 50+ endpoints across 11 routers |
| **Cortellis DB** | PostgreSQL 16 + pgvector | 145K deals, 52K companies, 903K contract chunks |
| **EDGAR DB** | PostgreSQL 16 + pgvector | 314K filings, 3.3M embedded chunks |
| **Graph** | Neo4j 5.15 | 55K companies, 145K deals, 289K relationships |
| **Cache** | Redis 7 | Analytics caching with TTLs |
| **Workers** | Celery + Redis | 6 scheduled tasks (sync, alerts, MV refresh) |
| **Deployment** | Docker Compose (8 services) → Dokploy | Auto-deploy on git push |

**Key insight:** The backend is substantially complete. 50+ API endpoints cover search, analytics, graph, contracts, watchlist, export, alerts, and entity resolution. The gap is almost entirely in the frontend and the intelligence layer (how data becomes insight).

### 3.2 Target Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        BD INTELLIGENCE PLATFORM v2                       │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  INTERACTION LAYER                                                       │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────┐ ┌─────────┐ │
│  │ Ask        │ │ Explore    │ │ Search     │ │ Analyze  │ │ Brief   │ │
│  │ (Chat +    │ │ (Dashboards│ │ (Filters + │ │ (Comps,  │ │ (Email  │ │
│  │  Synthesis)│ │  + Charts) │ │  Results)  │ │  DD, Map)│ │  Digest)│ │
│  └─────┬──────┘ └─────┬──────┘ └─────┬──────┘ └────┬─────┘ └────┬────┘ │
│        │              │              │              │             │      │
│  ──────┴──────────────┴──────────────┴──────────────┴─────────────┴───  │
│                                                                          │
│  INTELLIGENCE LAYER (NEW)                                                │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ Query Intent Classifier → Response Synthesizer → Action Router  │   │
│  │ Comp Engine → Recommendation Engine → Briefing Generator        │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  DATA LAYER (EXISTING)                                                   │
│  ┌────────────┐ ┌────────────┐ ┌──────────┐ ┌───────┐ ┌────────────┐  │
│  │ Cortellis  │ │ EDGAR      │ │ Neo4j    │ │ Redis │ │ Celery     │  │
│  │ PostgreSQL │ │ PostgreSQL │ │ Graph    │ │ Cache │ │ Workers    │  │
│  │ 145K deals │ │ 314K files │ │ 289K rel │ │       │ │ 6 tasks    │  │
│  └────────────┘ └────────────┘ └──────────┘ └───────┘ └────────────┘  │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Feature Requirements

### Phase 1: Executive Foundation (Weeks 1-4)
*Goal: JVO can open the platform and get value in 30 seconds*

#### F1: Executive Dashboard
**Priority:** P0 — this is the landing page

The dashboard must answer "What's happening?" without requiring any input.

**Layout:**
```
┌─────────────────────────────────────────────────────────────────────┐
│ BD Intelligence Platform               [Ask anything...] [👤 JVO] │
├───────┬─────────────────────────────────────────────────────────────┤
│       │                                                             │
│  Nav  │  ┌─── Market Pulse ──────────────┐  ┌── Your Alerts ─────┐ │
│       │  │ Deal volume trend (12mo)      │  │ 3 new deals match  │ │
│ Dash  │  │ Avg deal value trend          │  │ "ADC Oncology"     │ │
│ Search│  │ Top therapy areas this month  │  │ Pfizer acquired... │ │
│ Analyt│  └───────────────────────────────┘  └────────────────────┘ │
│ Deals │                                                             │
│ Graph │  ┌─── Notable Deals (30d) ──────────────────────────────┐  │
│ Filing│  │ Deal | Parties | Type | Value | Indication | Phase   │  │
│ Contra│  │ ──────────────────────────────────────────────────── │  │
│       │  │ [Top 10 recent high-value deals with key details]    │  │
│       │  └──────────────────────────────────────────────────────┘  │
│       │                                                             │
│       │  ┌── Competitor Activity ──┐  ┌── Your Watchlist ────────┐ │
│       │  │ Pfizer: 5 deals (30d)  │  │ 12 tracked deals         │ │
│       │  │ Merck: 3 deals         │  │ 2 status changes         │ │
│       │  │ AbbVie: 4 deals        │  │ [Quick view]             │ │
│       │  └────────────────────────┘  └───────────────────────────┘ │
└───────┴─────────────────────────────────────────────────────────────┘
```

**Requirements:**
- All widgets load from pre-computed/cached data (< 1 second)
- "Market Pulse" — deal volume and value trends, configurable time window
- "Your Alerts" — matches from saved searches, new deals in tracked indications
- "Notable Deals" — highest-value or most-significant recent deals
- "Competitor Activity" — deal counts for tracked competitor companies
- "Your Watchlist" — summary of tracked deals with status changes
- Global search bar ("Ask anything...") always visible — this is the entry point to Ask mode
- Each widget links to its full view (dashboard → analytics, alert → deal detail, etc.)

#### F2: Conversational Intelligence (Ask Mode)
**Priority:** P0 — JVO's primary interaction pattern

Upgrade the existing chat interface from raw SQL/RAG output to synthesized intelligence.

**Requirements:**
- **Intent classification:** Detect whether the question is factual, analytical, or strategic
- **Synthesized responses:** Narrative answer + inline data (tables, mini-charts) + confidence level
- **Source attribution:** Every claim links to underlying deals/filings/contracts
- **Confidence indicators:**
  - Data completeness: "Based on 23 of 31 deals with disclosed values (74%)"
  - Temporal coverage: "Data current as of [last sync date]"
  - Sample size warnings: "Note: only 4 comparable deals found — interpret with caution"
- **Follow-up suggestions:** "You might also want to know..." with clickable queries
- **Action bar:** Save search | Add to watchlist | Export | View in dashboard | Build comp set
- **Conversation memory:** Follow-up questions reference prior context within session
- **Streaming responses:** Partial results appear immediately for complex queries

**Query spectrum to support:**

| Complexity | Example | Response Type |
|------------|---------|---------------|
| Lookup | "What was the biggest pharma deal in 2024?" | Single answer + deal card |
| Filter | "Show me Phase 3 oncology M&A deals over $1B" | Table with summary stats |
| Benchmark | "What's a typical upfront for a Phase 2 ADC asset?" | Statistical summary + chart + comps |
| Compare | "How does Pfizer's oncology M&A compare to Merck's?" | Side-by-side analysis + charts |
| Strategic | "We want to acquire a bispecific antibody company in lung cancer. What should we know?" | Multi-section briefing: comps, valuations, landscape, risks, recommendations |

#### F3: Authentication & User Context
**Priority:** P0 — required for personalization

**Requirements:**
- JWT-based auth with email/password (phase 1)
- SSO integration hooks for future Okta/Azure AD
- User profiles with role (CEO, VP BD, Analyst, Viewer)
- Per-user: saved searches, watchlists, alert preferences, recent activity
- Session management with secure token refresh

#### F4: Advanced Search (Search Mode)
**Priority:** P0 — the BD team's daily driver

**Requirements:**
- Multi-criteria filter panel (collapsible sidebar):
  - Therapy area (with Oncology prominent/default)
  - Indication (autocomplete, multi-select)
  - Technology/modality (ADC, CAR-T, bispecific, small molecule, etc.)
  - Company (Principal and/or Partner role, with autocomplete)
  - Agreement type (License, M&A, Co-development, Option — 21 types)
  - Development phase at deal time
  - Date range (deal start/announced)
  - Deal value range with "disclosed only" toggle
  - Territory scope
  - Deal status (Active, Completed, Terminated)
- Results table: sortable columns, row expansion for deal summary, bulk actions
- Quick actions per row: Add to watchlist, View detail, Add to comp set, Export
- Save search criteria as named template (reusable + alertable)
- Export filtered results to Excel/CSV
- Pagination with total count and "X of Y deals have disclosed financial data"

#### F5: Company Intelligence Profile
**Priority:** P1

**Requirements (API exists — needs frontend):**
- Company header: name, type, HQ, total deal count
- Deal activity timeline (sparkline + full chart)
- Top 10 partners by deal frequency
- Therapeutic focus: indication distribution pie/bar chart
- Financial summary: average/total deal values, largest deal
- Recent activity: last 12 months of deals
- Drug/asset portfolio: list with current phase
- SEC filing integration: related EDGAR filings (if CIK-matched)
- Partnership network mini-graph (top connections)
- Action bar: Track competitor, Export profile, Compare with...

#### F6: Drug/Asset Profile
**Priority:** P1

**Requirements (API exists — needs frontend):**
- Drug header: name, display name, highest phase, mechanism
- Complete deal history (chronological timeline)
- Current rights holders by territory (table + map)
- Financial summary across all deals involving this drug
- Related companies (owners, licensees, partners)
- Indication coverage
- Action bar: Track asset, View contracts, Export

---

### Phase 2: Analytical Power (Weeks 5-10)
*Goal: The BD team stops using Excel for analysis*

#### F7: Analytics Dashboards (Explore Mode)
**Priority:** P0

**14 backend endpoints exist. Build the frontend.**

**Market Trends Dashboard:**
- Deal volume over time (line chart, quarterly/yearly)
- Deal value over time (disclosed only, with sample size)
- Breakdown by agreement type (stacked bar)
- Filter by therapy area, indication, technology, date range
- YoY growth rates

**Valuation Benchmarks Dashboard:**
- Box plots: deal value by development phase
- Box plots: deal value by indication
- Box plots: deal value by agreement type
- Median trend lines over time
- Data quality badges: "N=23, 74% disclosed"
- **Critical:** Always show sample size and disclosure rate. A CEO with McKinsey training will immediately question unsupported statistics.

**Geographic Dashboard:**
- Territory distribution (choropleth or bubble map)
- Deal activity by region over time

**Competitive Landscape Dashboard:**
- Top acquirers by deal count and value
- Therapy area heatmap (company × therapy area matrix)
- M&A-specific analytics (acquisition premium trends, deal structure breakdown)
- Company comparison: side-by-side metrics for 2-4 companies

#### F8: Partnership Network Visualization (Graph Mode)
**Priority:** P1

**Requirements (API exists — needs frontend):**
- Interactive force-directed graph (D3.js or vis.js)
- Node = company, sized by deal count
- Edge = deal relationship, thickness by frequency, colored by deal type
- Click node → company profile panel
- Click edge → deals between the two companies
- Filter by: therapy area, indication, date range, deal type
- Industry-wide view (top N most-connected companies)
- Company-centric view (one company + its network)
- Path finder: "How are Company A and Company B connected?"
- **Strategic value:** Identifies warm introduction paths and partnership patterns

#### F9: Comp Builder (Analyze Mode)
**Priority:** P0 — this is the #1 BD workflow

**User flow:**
1. Define target profile: indication + modality + phase + deal type + date range
2. System returns ranked comparable deals with match score
3. User selects 2-8 deals for comparison set
4. Side-by-side comparison view: parties, financials, milestones, territory, phase
5. Statistical summary: median/mean/range for key terms
6. Save comp set with name and notes
7. Export to Excel (formatted) or PDF (presentation-ready)

**Requirements:**
- Match scoring algorithm (weighted similarity across criteria)
- Comparison table with uniform column structure
- Inline financial data with disclosure indicators
- Chart: deal value distribution of comp set
- "Add more like this" — find additional similar deals
- Comp set history (saved per user)

**Data dependencies:**
- Parse `finance_detail_raw` → structured milestone breakdowns
- Parse `payments_to_principal/partner` → payment timelines
- Extract royalty rates from contracts (NLP pipeline)

#### F10: Contract Term Analyzer
**Priority:** P1

**Requirements (NLP extraction exists — needs enhancement + frontend):**
- Structured term database: royalty rates, milestones, upfront payments, territory clauses
- Query by term type: "What are typical royalty rates for Phase 2 oncology ADC assets?"
- Statistical aggregation: median, range, distribution by deal characteristics
- Source linking: every extracted term links to source contract text
- Confidence scoring: NLP extraction confidence with human review workflow
- Compare terms across deals: side-by-side clause comparison

---

### Phase 3: Strategic Intelligence (Weeks 11-16)
*Goal: The platform generates insights, not just answers*

#### F11: Due Diligence Package Generator
**Priority:** P1

**User flow:**
1. Select target company or asset
2. System auto-generates comprehensive DD package:
   - Company profile with full deal history
   - All assets/drugs with phase and territory status
   - Partnership network and key relationships
   - Financial history (deal values, trends)
   - SEC filings (if CIK-matched): 10-K, 10-Q, 8-K, S-1
   - Related contracts with key extracted terms
   - Territory rights map (committed vs. available)
   - Comparable transactions
   - Risk flags (concentrated partnerships, terminated deals, litigation filings)
3. Review and customize sections
4. Export as organized PDF or ZIP (one section per file)

**Value proposition:** What takes an analyst 2 weeks of manual research, the platform produces in minutes — with the same sources the analyst would use, already cross-referenced.

#### F12: Territory Rights Visualization
**Priority:** P1

**Requirements:**
- World map (Leaflet or Mapbox) showing territory commitments per asset
- Color coding: committed (red), available (green), partially committed (yellow)
- Click territory → see rights holder, deal terms, expiration
- Timeline slider: show how rights have changed over time
- "White space" analysis: uncommitted territories across a company's portfolio
- Export territory map as image for presentations

#### F13: SEC Filing Intelligence
**Priority:** P2

**Requirements (API exists — needs frontend + enhancement):**
- Filing viewer: full text with table of contents and section navigation
- Cross-reference panel: "Cortellis deals related to this filing"
- Material contract extraction: flag 8-K filings with deal implications
- Search within filings: keyword + semantic search across 3.3M chunks
- Company filing timeline: all filings for a company, filterable by type

#### F14: Automated Briefing System (Brief Mode)
**Priority:** P1

**Requirements:**
- **Daily digest email:**
  - New deals matching saved search criteria
  - Competitor activity summary
  - Watchlist status changes
  - Notable deals (high-value, strategic significance)

- **Weekly landscape report (auto-generated):**
  - Deal activity summary by therapy area
  - Trending indications/modalities
  - Notable M&A activity
  - New entrants in tracked spaces

- **On-demand briefing:**
  - "Brief me on [company/indication/modality]"
  - Generates structured report: overview, recent activity, key players, deal trends, outlook
  - Exportable as PDF/PowerPoint

- **Email delivery:** SendGrid or AWS SES integration
- **Format:** Clean HTML email with embedded charts (or chart images) and deep links back to platform

#### F15: Recommendation Engine
**Priority:** P2

**Requirements:**
- **"Deals you should know about"** — surface deals the user hasn't seen that match their profile (based on search history, watchlist patterns, tracked indications)
- **"Companies to watch"** — flag companies with unusual deal activity or strategic fit
- **"Similar to deals you've tracked"** — collaborative filtering across watchlist items
- **Reasoning transparency:** Every recommendation includes "Why we flagged this" with data points

---

### Phase 4: Collaboration & Production (Weeks 17-22)
*Goal: The entire BD team uses this as their primary tool*

#### F16: Team Collaboration
**Priority:** P2

**Requirements:**
- Team workspaces with shared watchlists
- Deal comments/threads (per deal, visible to team)
- @mentions with in-app + email notifications
- Activity feed: who searched what, who saved what (privacy-controlled)
- Role-based permissions: Admin, Editor, Viewer
- Shared comp sets and saved searches

#### F17: Competitor Intelligence Dashboard
**Priority:** P1

**Requirements:**
- Define competitor watchlist (company-level tracking)
- Competitor activity feed: chronological deal activity
- Competitor comparison matrix: deal volume, value, therapeutic focus, preferred deal structures
- Trend analysis: is competitor accelerating or slowing M&A activity?
- Alert on competitor deals in your tracked indications
- **Strategic questions it should answer:**
  - "What is Pfizer's oncology deal strategy?"
  - "Who is competing with us for ADC assets?"
  - "Which companies are divesting oncology assets?" (potential acquisition targets)

#### F18: Data Quality & Enrichment
**Priority:** P1 (ongoing)

**Requirements:**
- Company deduplication: expand beyond current 692 CIK-matched companies
- Financial data enrichment: parse `finance_detail_raw` for all 145K deals
- Indication hierarchy: parent/child relationships (e.g., "Breast Cancer" → "Oncology")
- Real-time CI sync: connect `cortellis-ci-sync` to live Cortellis API (currently mock data)
- Data freshness indicator on every page: "Last synced: [date/time]"
- Automated data quality scoring per deal record

#### F19: Production Hardening
**Priority:** P1

**Requirements:**
- Load testing: handle 20+ concurrent users with sub-3-second responses
- Query performance optimization: identify and fix slow endpoints
- Database connection pooling tuning
- Monitoring: uptime, error rates, query latency (Prometheus + Grafana or similar)
- Automated PostgreSQL backups (both databases)
- Disaster recovery plan for 65GB+ EDGAR data volume
- Rate limiting on API endpoints
- Audit logging: who accessed what, when

---

## 5. Data Model Enhancements

### 5.1 New Tables

```sql
-- ============================================
-- USER & AUTH
-- ============================================
CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  email VARCHAR(255) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  name VARCHAR(255),
  role VARCHAR(50) DEFAULT 'analyst',  -- ceo, vp_bd, analyst, viewer
  preferences JSONB DEFAULT '{}',      -- UI preferences, default filters
  created_at TIMESTAMP DEFAULT NOW(),
  last_login TIMESTAMP
);

CREATE TABLE teams (
  id SERIAL PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE team_members (
  team_id INT REFERENCES teams(id),
  user_id INT REFERENCES users(id),
  role VARCHAR(50) DEFAULT 'member',  -- admin, member, viewer
  PRIMARY KEY (team_id, user_id)
);

-- ============================================
-- COMPETITOR TRACKING
-- ============================================
CREATE TABLE competitor_watchlist (
  id SERIAL PRIMARY KEY,
  user_id INT REFERENCES users(id),
  company_id INT NOT NULL,
  label VARCHAR(255),                  -- user's label for this competitor
  tracked_since TIMESTAMP DEFAULT NOW(),
  UNIQUE(user_id, company_id)
);

-- ============================================
-- COMP SETS
-- ============================================
CREATE TABLE comp_sets (
  id SERIAL PRIMARY KEY,
  user_id INT REFERENCES users(id),
  name VARCHAR(255) NOT NULL,
  description TEXT,
  criteria JSONB,                      -- search criteria used to build set
  deal_ids INT[] NOT NULL,             -- selected comparable deals
  notes TEXT,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- EXTRACTED CONTRACT TERMS (enhanced)
-- ============================================
CREATE TABLE contract_extracted_terms (
  id SERIAL PRIMARY KEY,
  deal_id INT NOT NULL,
  contract_id INT,
  term_type VARCHAR(100) NOT NULL,     -- royalty_rate, milestone_clinical,
                                       -- milestone_regulatory, milestone_commercial,
                                       -- upfront_payment, territory_clause,
                                       -- opt_in_out, co_promote, sublicense
  term_value VARCHAR(500),             -- "5-10%", "$50M on FDA approval", etc.
  term_numeric NUMERIC,                -- parsed numeric value where applicable
  currency VARCHAR(10),
  confidence FLOAT NOT NULL,
  source_text TEXT,                     -- excerpt from contract
  reviewed BOOLEAN DEFAULT FALSE,       -- human verification flag
  reviewed_by INT REFERENCES users(id),
  extracted_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_contract_terms_type ON contract_extracted_terms(term_type);
CREATE INDEX idx_contract_terms_deal ON contract_extracted_terms(deal_id);

-- ============================================
-- BRIEFINGS
-- ============================================
CREATE TABLE briefings (
  id SERIAL PRIMARY KEY,
  user_id INT REFERENCES users(id),
  briefing_type VARCHAR(50),           -- daily_digest, weekly_landscape, on_demand
  subject VARCHAR(500),
  content_html TEXT,
  content_json JSONB,                  -- structured data for re-rendering
  delivered_at TIMESTAMP,
  delivery_method VARCHAR(50),         -- email, in_app
  created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- ACTIVITY LOG
-- ============================================
CREATE TABLE activity_log (
  id SERIAL PRIMARY KEY,
  user_id INT REFERENCES users(id),
  action VARCHAR(100) NOT NULL,        -- search, view_deal, export, save_comp, etc.
  entity_type VARCHAR(50),             -- deal, company, drug, search, comp_set
  entity_id INT,
  metadata JSONB,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_activity_user ON activity_log(user_id, created_at DESC);

-- ============================================
-- DEAL COMMENTS (team collaboration)
-- ============================================
CREATE TABLE deal_comments (
  id SERIAL PRIMARY KEY,
  deal_id INT NOT NULL,
  user_id INT REFERENCES users(id),
  parent_id INT REFERENCES deal_comments(id),  -- threading
  content TEXT NOT NULL,
  mentions INT[],                      -- user_ids mentioned
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
```

### 5.2 Data Enrichment Pipeline

| Task | Source | Target | Method | Priority |
|------|--------|--------|--------|----------|
| Parse `finance_detail_raw` | deals table | structured milestone fields | Regex + GPT extraction | P0 |
| Parse payment timelines | `payments_to_principal/partner` | payment_events table | Regex parsing | P1 |
| Extract contract terms | 26K contract texts | contract_extracted_terms | GPT-4o with schema | P1 |
| Build indication hierarchy | indications table | indication_parents table | Manual curation + NLP | P2 |
| Expand entity resolution | 52K companies | company_xref | Trigram + embedding matching | P2 |
| Real CI data integration | Cortellis CI API | ci_sync tables | API client (replace mock) | P1 |

---

## 6. UI/UX Specification

### 6.1 Design Principles

1. **Density over decoration.** JVO reads Bloomberg terminals. The UI should be information-dense, not consumer-app sparse. Every pixel earns its place with data.

2. **Progressive disclosure.** Dashboard → click for detail → click for raw data. Never overwhelm, but never hide.

3. **Data integrity transparency.** Always show: sample size, disclosure rate, data freshness, confidence level. A McKinsey-trained mind will distrust unlabeled statistics.

4. **Speed.** Dashboard loads in < 1 second (pre-cached). Search returns in < 3 seconds. Chat answers stream in < 5 seconds. No loading spinners longer than 2 seconds.

5. **Export everything.** Every table, chart, and analysis should be exportable to Excel, CSV, or PDF. Board presentations come from this tool.

### 6.2 Navigation

```
┌──────────────────────────────────────────────────────────────────┐
│ ☰  BD Intelligence    [🔍 Ask anything...]    [🔔 3]  [👤 JVO] │
├──────┬───────────────────────────────────────────────────────────┤
│      │                                                           │
│  📊  │   (Active page content)                                   │
│ Dash │                                                           │
│      │                                                           │
│  🔍  │                                                           │
│Search│                                                           │
│      │                                                           │
│  📈  │                                                           │
│Analyt│                                                           │
│      │                                                           │
│  🏢  │                                                           │
│Compet│                                                           │
│      │                                                           │
│  🤝  │                                                           │
│Graph │                                                           │
│      │                                                           │
│  📄  │                                                           │
│Filing│                                                           │
│      │                                                           │
│  📋  │                                                           │
│Contra│                                                           │
│      │                                                           │
│  ⭐   │                                                           │
│My    │                                                           │
│Deals │                                                           │
│      │                                                           │
│  💬  │                                                           │
│ Ask  │                                                           │
│      │                                                           │
└──────┴───────────────────────────────────────────────────────────┘
```

**Global elements:**
- Persistent "Ask anything..." bar in top nav (opens chat panel/overlay)
- Notification bell with unread count
- User menu: profile, preferences, logout
- Collapsible left nav with icons + labels

### 6.3 Component Library

| Component | Library | Usage |
|-----------|---------|-------|
| Charts | Recharts | Time series, bar, pie, box plots |
| Network Graph | vis.js or react-force-graph | Partnership network |
| World Map | react-simple-maps + d3-geo | Territory visualization |
| Data Table | TanStack Table (React Table v8) | All tabular data |
| Date Range | react-datepicker | Filter panels |
| Autocomplete | Downshift or Headless UI Combobox | Company/indication/drug search |
| Document Viewer | Custom (HTML renderer) | SEC filings, contracts |
| Markdown/Rich Text | react-markdown | Chat responses, briefings |
| Export | xlsx (SheetJS) + jsPDF | Excel and PDF generation |
| Icons | Lucide React | Consistent iconography |

---

## 7. API Enhancements Required

### 7.1 New Endpoints

| Endpoint | Method | Purpose | Phase |
|----------|--------|---------|-------|
| `/api/auth/register` | POST | User registration | 1 |
| `/api/auth/login` | POST | JWT token issuance | 1 |
| `/api/auth/refresh` | POST | Token refresh | 1 |
| `/api/auth/me` | GET | Current user profile | 1 |
| `/api/chat/v2` | POST | Enhanced chat with synthesis | 1 |
| `/api/dashboard/executive` | GET | Pre-computed dashboard data | 1 |
| `/api/dashboard/alerts-summary` | GET | Alert count + recent matches | 1 |
| `/api/comps/build` | POST | Generate comp set from criteria | 2 |
| `/api/comps` | GET/POST | List/save comp sets | 2 |
| `/api/comps/{id}` | GET/PUT/DELETE | Manage saved comp set | 2 |
| `/api/comps/{id}/export/excel` | GET | Export comp set to Excel | 2 |
| `/api/comps/{id}/export/pdf` | GET | Export comp set to PDF | 2 |
| `/api/competitors` | GET/POST | Competitor watchlist | 2 |
| `/api/competitors/activity` | GET | Recent competitor deals | 2 |
| `/api/competitors/compare` | GET | Side-by-side competitor metrics | 2 |
| `/api/dd/generate` | POST | Generate DD package for company/asset | 3 |
| `/api/dd/{id}` | GET | Retrieve generated DD package | 3 |
| `/api/dd/{id}/export` | GET | Export DD as PDF/ZIP | 3 |
| `/api/briefings/generate` | POST | On-demand briefing | 3 |
| `/api/briefings` | GET | User's briefing history | 3 |
| `/api/territory/{drug_id}/map` | GET | Territory rights GeoJSON | 3 |
| `/api/recommendations` | GET | Personalized deal recommendations | 3 |
| `/api/activity` | GET | User/team activity feed | 4 |
| `/api/comments/{deal_id}` | GET/POST | Deal comment threads | 4 |

### 7.2 Enhanced Existing Endpoints

| Endpoint | Enhancement | Phase |
|----------|-------------|-------|
| `/api/chat` | Add intent classification, synthesis layer, confidence scoring, action links | 1 |
| `/api/analytics/*` | Add user-scoped caching, export format parameter | 2 |
| `/api/search/advanced` | Add match scoring, comp-set-add action | 2 |
| `/api/watchlist` | Add team sharing, comment count, status change history | 4 |
| `/api/contracts/extract-clauses` | Add batch mode, confidence threshold, human review queue | 3 |

---

## 8. Implementation Phases — Summary

| Phase | Weeks | Theme | Key Deliverables |
|-------|-------|-------|-----------------|
| **1** | 1-4 | Executive Foundation | Dashboard, enhanced chat with synthesis, auth, advanced search UI, company/drug profile pages |
| **2** | 5-10 | Analytical Power | Analytics dashboard frontend, network graph visualization, comp builder, contract term frontend, competitor tracking |
| **3** | 11-16 | Strategic Intelligence | DD package generator, territory map, SEC filing viewer, automated briefings, recommendation engine |
| **4** | 17-22 | Collaboration & Scale | Team features, comments, activity feed, email notifications, production hardening, monitoring |

---

## 9. Success Metrics

### Adoption Metrics
| Metric | Target | Measurement |
|--------|--------|-------------|
| CEO weekly sessions | ≥ 3 | Login tracking |
| BD team daily active | 80%+ of team | Session analytics |
| Questions asked (chat) | 20+ per user/week | Chat logs |
| Comp sets built | 5+ per analyst/month | Database |

### Efficiency Metrics
| Metric | Target | Measurement |
|--------|--------|-------------|
| Time to find comps | < 5 minutes (was hours) | User testing |
| Time to build DD package | < 15 minutes (was weeks) | Workflow timing |
| Time to answer strategic question | < 30 seconds (was "let me get back to you") | Chat response time |
| Deals reviewed per session | 15+ | Click analytics |

### Quality Metrics
| Metric | Target | Measurement |
|--------|--------|-------------|
| Chat answer accuracy | > 95% for factual queries | Spot-check audit |
| Contract term extraction accuracy | > 90% (with confidence > 0.8) | Human review |
| Data freshness | < 24 hours lag | Sync monitoring |
| System uptime | 99.5%+ | Health checks |

---

## 10. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Financial data gaps (73% undisclosed) | Valuation benchmarks misleading | Certain | Always display sample size + disclosure rate. "Disclosed only" toggle. Never present statistics without N. |
| Chat hallucination (LLM invents data) | CEO makes decision on false data | Medium | SQL-first approach (verifiable). Source attribution on every claim. Confidence indicators. Audit trail. |
| Contract NLP inaccuracy | Wrong term extraction | Medium | Confidence thresholds (reject < 0.7). Human review queue. Flag unreviewed extractions. |
| Performance under load | Slow dashboards = no adoption | Medium | Pre-computed materialized views. Redis caching. Query optimization. Load testing. |
| Data staleness | Missed recent deals | Low | Daily sync + freshness indicators on UI. Alert on sync failures. |
| Company deduplication errors | Incorrect aggregation | Medium | Conservative matching (high threshold). Manual review for merges. Audit log. |
| Scope creep | Never ships | High | Strict phase gating. Phase 1 must ship before Phase 2 starts. MVP mindset per phase. |

---

## 11. Open Questions for Stakeholder Input

1. **SSO:** Should auth integrate with BeiGene's identity provider (Okta/Azure AD), or is standalone auth acceptable for initial deployment?

2. **Data scope:** Is oncology the primary focus, or should all 19 therapy areas be equally prominent? (Current: oncology-default with full data available)

3. **Briefing audience:** Should automated briefings be CEO-only, or should the full BD team get personalized digests?

4. **Export format:** Beyond Excel/PDF, does the BD team need PowerPoint-formatted slides for board presentations?

5. **CRM integration:** Is there a Salesforce or other CRM that deal tracking should sync with?

6. **Access control:** Should all users see all data, or are there sensitivity levels (e.g., M&A pipeline deals visible only to VP+ level)?

7. **Mobile:** Does JVO need mobile access (responsive web), or is desktop sufficient?

8. **Real-time vs. batch:** Is daily data sync acceptable, or are there scenarios requiring real-time deal alerts (e.g., breaking 8-K filings)?

---

## Appendix A: Example Interactions by Mode

### Ask Mode — CEO Examples

**Morning check-in:**
> "Anything notable in oncology deals this week?"

Response: Narrative summary of 3-5 significant deals with parties, values, and why they matter. Links to each deal. "Compared to last week: deal volume up 15%, one deal over $2B (unusual)."

**Meeting prep:**
> "Quick profile of Seagen — their deal history and current partnerships"

Response: Company card with key stats, top 5 recent deals, major partners, therapeutic focus chart. "Seagen was acquired by Pfizer in 2023 for $43B. Prior to acquisition, they had 28 active partnerships primarily in ADC technology."

**Board preparation:**
> "Build me a market landscape summary for ADC deals in solid tumors, 2020-2025"

Response: Multi-section briefing with deal volume trend, top players, valuation benchmarks, notable transactions, and outlook. Each section sourced. Exportable as PDF.

### Search Mode — Analyst Examples

**Target identification:**
Filters: Oncology → Solid Tumors → ADC → Phase 2+ → License/Option → 2022-2025 → Disclosed value
Result: 34 deals, sorted by value. Each row expandable. Bulk export. "Save as: ADC Solid Tumor P2+ Licenses"

### Analyze Mode — VP BD Examples

**Negotiation prep:**
Build comp set: bispecific antibody, NSCLC, Phase 2, license deals, 2020-2025
Result: 12 comparable deals. Select 5 most relevant. Side-by-side: upfront ($50M-$300M), total ($500M-$3.2B), royalties (8-15%), milestones (clinical: 3-5, regulatory: 2-3, commercial: 2-4).
Export to Excel for term sheet discussion.

---

## Appendix B: Database Schema Reference

See existing implementation:
- `scripts/init_db.sql` — Full schema
- `src/models.py` — SQLAlchemy ORM models
- `unified_api/routers/*.py` — All 50+ endpoint implementations
- `PRIORITY_TODO.md` — Current implementation status

Core tables: deals, companies, deal_companies, drugs, indications, technologies, therapy_areas, territories, deal_finance_summary, deal_timeline_events, deal_contracts, contract_content, contract_chunks, user_watchlist, deal_notes, saved_searches, search_history, company_xref

---

## Appendix C: Competitive Intelligence Sync

Two supporting repositories feed data into the platform:

- **cortellis-sync** (`~/repos/cortellis-sync`) — ETL pipeline for Cortellis Deal Intelligence API. Syncs deal records to PostgreSQL.
- **cortellis-ci-sync** (`~/repos/cortellis-ci-sync`) — Competitive intelligence service tracking drugs, clinical trials, and company developments in oncology. Currently running mock data — needs real API connection.

Both deploy to MachomeLab via Dokploy.

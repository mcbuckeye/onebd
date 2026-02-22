# BD Intelligence Platform

A unified strategic intelligence platform for pharmaceutical business development. Combines the Cortellis deals database (145K+ deals) with SEC EDGAR filings (314K+ documents) through a Neo4j graph integration layer, enabling deal discovery, competitive intelligence, valuation benchmarking, and due diligence workflows.

## Data Assets

| Source | Volume | Description |
|--------|--------|-------------|
| **Deals** | 145,458 | Pharmaceutical deal records from Cortellis |
| **Companies** | 52,397 | Company profiles with cross-references |
| **Drugs** | 33,428 | Drug/asset records with phase tracking |
| **SEC Filings** | 314,097 | 10-K, 10-Q, 8-K, S-1 filings from EDGAR |
| **Contracts** | 26,115 | Full-text indexed contract documents |
| **Contract Chunks** | 903,650 | Embedded chunks for semantic search (RAG) |
| **EDGAR Chunks** | 3,354,626 | Embedded SEC filing chunks |
| **Graph Nodes** | 55,000+ companies | Neo4j with 289K+ relationships |
| **Entity Links** | 692 | Companies linked across Cortellis/EDGAR via CIK |

## Architecture

```
+-----------------------------------------------------------------------------------+
|                       BD INTELLIGENCE PLATFORM                                    |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|  +----------------+   +-----------------+   +-------------+   +-----------+       |
|  | React Frontend |-->| Unified API     |-->| Cortellis   |   | Celery    |       |
|  | (Vite + TS)    |   | (FastAPI)       |   | PostgreSQL  |   | Workers   |       |
|  | :3000          |   | :8000           |   | :5433       |   |           |       |
|  +----------------+   +---------+-------+   +-------------+   +-----+-----+       |
|                             |   |                                   |             |
|                             |   +---------> +-------------+        |             |
|                             |               | Edgar Source |        |             |
|                             |               | PostgreSQL  |        |             |
|                             |               | :5432       |        |             |
|                             |               +-------------+        |             |
|                             |                                      |             |
|                             +---------> +-------------+            |             |
|                             |           | Neo4j Graph |<-----------+             |
|                             |           | :7474/:7687 |                          |
|                             |           +-------------+                          |
|                             |                                                    |
|                             +---------> +-------------+                          |
|                                         | Redis       |<-------------------------+
|                                         | :6379       |                          |
|                                         +-------------+                          |
|                                                                                   |
+-----------------------------------------------------------------------------------+
```

**Query Router**: The API routes queries to the appropriate backend based on intent:
- Structured deal queries -> Cortellis PostgreSQL
- SEC filing queries -> Edgar PostgreSQL
- Relationship/network queries -> Neo4j (Cypher)
- Semantic search -> pgvector (4.2M combined chunks)

## Quick Start

### 1. Setup Environment

```bash
cp .env.unified.example .env.unified
# Edit .env.unified with your credentials
```

Required environment variables:

| Variable | Description |
|----------|-------------|
| `CORTELLIS_PASSWORD` | Cortellis database password |
| `OPENAI_API_KEY` | OpenAI API key (GPT-4o + embeddings) |
| `NEO4J_PASSWORD` | Neo4j graph database password |
| `CORTELLIS_API_USERNAME` | Cortellis REST API username (for sync) |
| `CORTELLIS_API_PASSWORD` | Cortellis REST API password (for sync) |

### 2. Start All Services

```bash
docker compose -f docker-compose.unified.yml up -d
```

This starts 8 containers:

| Service | Container | Port | Description |
|---------|-----------|------|-------------|
| **Frontend** | `bd-frontend` | 3000 | React chat interface |
| **API** | `bd-api` | 8000 | Unified FastAPI backend |
| **Cortellis DB** | `bd-cortellis-db` | 5433 | Deals + companies + contracts |
| **Edgar DB** | `bd-edgar-source-db` | 5432 | SEC filings + embeddings |
| **Neo4j** | `bd-neo4j` | 7474/7687 | Graph database |
| **Redis** | `bd-redis` | 6379 | Cache + Celery broker |
| **Crawl Worker** | `bd-crawl-worker` | - | Rate-limited EDGAR fetching |
| **Beat Scheduler** | `bd-beat` | - | Periodic task scheduling |

### 3. Access the Platform

- **Web UI**: http://localhost:3000
- **API Docs**: http://localhost:8000/docs
- **Neo4j Browser**: http://localhost:7474

## API Endpoints (50+)

### Search & Discovery

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | POST | Natural language query (SQL/RAG auto-routing) |
| `/api/search/advanced` | POST | Multi-criteria deal search with filters |
| `/api/search/autocomplete/companies` | GET | Company name typeahead (trigram) |
| `/api/search/autocomplete/indications` | GET | Indication typeahead |
| `/api/search/autocomplete/drugs` | GET | Drug name typeahead |
| `/api/search/history` | GET/POST/DELETE | Search history tracking |

### Company & Drug Profiles

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/company/{id}/profile` | GET | Full company intelligence profile |
| `/api/drug/{id}/profile` | GET | Drug/asset profile with deal history |
| `/api/entities/companies` | GET | Browse companies |
| `/api/entities/drugs` | GET | Browse drugs |
| `/api/entities/indications` | GET | Browse indications |

### Analytics Dashboards

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/analytics/market-trends` | GET | Deal volume/value over time |
| `/api/analytics/valuations/by-phase` | GET | Benchmarks by development phase |
| `/api/analytics/valuations/by-indication` | GET | Benchmarks by indication |
| `/api/analytics/valuations/by-deal-type` | GET | Benchmarks by agreement type |
| `/api/analytics/top-deals` | GET | Largest deals by value |
| `/api/analytics/top-acquirers` | GET | Most active acquirers |
| `/api/analytics/deal-activity-summary` | GET | Overall activity metrics (cached) |
| `/api/analytics/geographic-distribution` | GET | Deals by territory |
| `/api/analytics/agreement-type-distribution` | GET | Deals by agreement type |
| `/api/analytics/deal-status-funnel` | GET | Status distribution funnel |
| `/api/analytics/therapy-area-heatmap` | GET | Activity by therapy area + year |
| `/api/analytics/ma-analytics` | GET | M&A-specific analytics |
| `/api/analytics/company-comparison` | GET | Side-by-side company metrics |
| `/api/analytics/yoy-growth` | GET | Year-over-year growth rates |
| `/api/analytics/cache/invalidate` | POST | Clear analytics cache |

### Graph & Network Visualization

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/graph/partnership-network/{id}` | GET | D3.js-compatible network graph |
| `/api/graph/company/{id}/partners-summary` | GET | Detailed partner list |
| `/api/graph/industry-network` | GET | Industry-wide partnership map |
| `/api/graph/network/{id}` | GET | Full network with deal details |
| `/api/graph/top-partners` | GET | Top partners by deal count |
| `/api/graph/path` | GET | Find path between two companies |
| `/api/graph/deals-between` | GET | All deals between two companies |

### SEC Filing Viewer

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/edgar/filings/{id}/content` | GET | Full filing text (paginated) |
| `/api/edgar/filings/{id}/sections` | GET | Table of contents |
| `/api/edgar/filings/{id}/related-deals` | GET | Cross-reference Cortellis deals |

### Contract Intelligence

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/contracts/extract-clauses` | POST | GPT-4o clause extraction from text |
| `/api/contracts/{deal_id}/clauses` | GET | Get/extract clauses for a deal |
| `/api/contracts/compare` | GET | Side-by-side deal term comparison |

### Export

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/export/deals/csv` | POST | Export deals to CSV |
| `/api/export/deals/excel` | POST | Export deals to Excel |
| `/api/export/company/{id}/deals/csv` | GET | Company deals CSV |
| `/api/export/company/{id}/deals/excel` | GET | Company deals Excel |
| `/api/export/search-results/excel` | GET | Search results to Excel |
| `/api/export/analytics/market-trends/csv` | GET | Market trends CSV |
| `/api/export/analytics/valuations/csv` | GET | Valuation benchmarks CSV |

### Watchlist & Notes

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/watchlist` | GET/POST | View/add to deal watchlist |
| `/api/watchlist/{deal_id}` | PATCH/DELETE | Update/remove from watchlist |
| `/api/watchlist/stats` | GET | Watchlist statistics |
| `/api/deals/{deal_id}/notes` | GET/POST | Deal notes |
| `/api/notes/{note_id}` | PATCH/DELETE | Update/delete note |
| `/api/saved-searches` | GET/POST | Saved search criteria |
| `/api/saved-searches/{id}` | DELETE | Delete saved search |

### Notifications & Alerts

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/notifications` | GET | In-app notifications |
| `/api/notifications/{id}` | DELETE | Dismiss notification |
| `/api/alerts/trigger` | POST | Manually trigger alert check |

### Entity Resolution & Data Quality

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/xref/duplicates` | GET | Detect duplicate companies (trigram) |
| `/api/xref/merge-companies` | POST | Merge duplicate company records |

## Performance Optimizations

### Redis Caching
Query results are cached in Redis (database 2) with configurable TTLs:
- Analytics queries: 1 hour
- Autocomplete: 2 hours
- Search results: 5 minutes
- Statistics: 30 minutes

### Materialized Views
Four materialized views are refreshed daily at 8:30 AM for fast analytics:
- `mv_market_trends_yearly` - Deal count/value by year
- `mv_agreement_type_stats` - Agreement type breakdown by year
- `mv_therapy_area_trends` - Therapy area activity by year
- `mv_company_deal_stats` - Company deal metrics by role

### Neo4j Composite Indexes
Optimized graph queries with composite indexes on:
- `Company(source, name)`
- `Deal(source, date_start)`
- `Deal(agreement_type, date_start)`
- `Company(company_type)`

## Background Tasks (Celery Beat)

| Time (UTC) | Task | Description |
|------------|------|-------------|
| 02:00 | `fetch_new_filings` | Fetch new SEC EDGAR filings |
| 06:30 | `sync_cortellis_deals` | Sync deals from Cortellis API |
| 07:00 | `sync_neo4j_graph` | Sync data to Neo4j graph |
| 07:30 | `link_deals_to_filings` | Auto-match deals to 8-K filings |
| 08:00 | `check_deal_alerts` | Check saved searches for new matches |
| 08:30 | `refresh_materialized_views` | Refresh analytics MVs + clear cache |

## Project Structure

```
cortellis/
+-- docker-compose.unified.yml   # All 8 services (primary)
+-- .env.unified                  # Environment configuration
+-- CLAUDE.md                     # AI assistant instructions
+-- PRD.md                        # Product requirements document
+-- PRIORITY_TODO.md              # Implementation checklist
|
+-- unified_api/                  # Unified FastAPI Backend
|   +-- main.py                   # App entrypoint, router registration
|   +-- config.py                 # Settings (DB URLs, API keys)
|   +-- Dockerfile
|   +-- requirements.txt
|   +-- routers/
|   |   +-- analytics.py          # 14 analytics dashboard endpoints
|   |   +-- chat.py               # NL query with SQL/RAG routing
|   |   +-- contracts.py          # Clause extraction, term comparison
|   |   +-- edgar.py              # SEC filing viewer, sections, related deals
|   |   +-- entities.py           # Company/drug/indication profiles
|   |   +-- export.py             # Excel/CSV export endpoints
|   |   +-- graph.py              # Neo4j network visualization
|   |   +-- health.py             # Health checks
|   |   +-- search.py             # Advanced search, autocomplete, history
|   |   +-- watchlist.py          # Watchlist, notes, notifications, alerts
|   |   +-- xref.py               # Entity resolution, deduplication, merge
|   +-- services/
|   |   +-- cache.py              # Redis caching with TTL management
|   |   +-- clause_extractor.py   # GPT-4o contract clause extraction
|   |   +-- database.py           # SQLAlchemy session management
|   |   +-- edgar.py              # SEC EDGAR API client
|   |   +-- embed.py              # OpenAI embedding service
|   |   +-- entity_resolution.py  # Trigram company matching
|   |   +-- graph_sync.py         # PostgreSQL -> Neo4j synchronization
|   |   +-- llm.py                # OpenAI chat completion service
|   |   +-- parse.py              # Document parsing (HTML/PDF)
|   |   +-- chunk.py              # Text chunking service
|   +-- workers/
|   |   +-- celery_app.py         # Celery config, beat schedule, all tasks
|   +-- scripts/
|       +-- create_watchlist_tables.py
|       +-- add_missing_edgar_companies.py
|       +-- create_materialized_views.sql
|
+-- frontend/                     # React + Vite + TypeScript + Tailwind
|   +-- src/
|   |   +-- App.tsx
|   |   +-- components/
|   |   |   +-- ChatInterface.tsx
|   |   |   +-- MessageBubble.tsx
|   |   |   +-- Sidebar.tsx
|   |   +-- types.ts
|   +-- Dockerfile
|   +-- nginx.conf
|
+-- src/                          # Original CLI & ETL Pipeline
|   +-- api_client.py             # Cortellis REST API client
|   +-- sync.py                   # Full/incremental sync
|   +-- contract_indexer.py       # Full-text + RAG indexing
|   +-- models.py                 # SQLAlchemy ORM models
|   +-- main.py                   # CLI commands
|
+-- agent/
|   +-- query_agent.py            # OpenAI query agent with RAG
|
+-- scripts/
|   +-- init_db.sql               # Database schema initialization
|
+-- OLD/                          # Legacy (pre-unification)
    +-- api/                      # Original single-file FastAPI backend
    +-- docker-compose.yml        # Original docker-compose (single DB)
    +-- Dockerfile                # Original Dockerfile
```

## Database Schema

### Core Tables (Cortellis)

| Table | Records | Description |
|-------|---------|-------------|
| `deals` | 145,458 | Deal records with agreement_type, status, dates |
| `companies` | 52,397 | Company profiles |
| `drugs` | 33,428 | Drug/asset records (name_display, phase_highest_now) |
| `indications` | 2,574 | Medical indications |
| `technologies` | 650 | Technology/modality types |
| `therapy_areas` | 19 | Therapy area categories |
| `territories` | 256 | Geographic territories |

### Relationship Tables

| Table | Records | Description |
|-------|---------|-------------|
| `deal_companies` | 289,065 | Deal-company links with role (Principal/Partner) |
| `deal_indications` | 214,724 | Deal-indication associations |
| `deal_technologies` | 339,640 | Deal-technology associations |
| `deal_drugs` | 77,507 | Deal-drug associations |
| `deal_territories` | 58,879 | Deal-territory scope |
| `deal_finance_summary` | ~39,000 | Financial terms (26.8% disclosed) |
| `deal_timeline_events` | - | Milestones, events, payments |

### Contract & Search Tables

| Table | Records | Description |
|-------|---------|-------------|
| `deal_contracts` | ~58,000 | Contract metadata |
| `contract_content` | 26,115 | Full-text content with tsvector index |
| `contract_chunks` | 903,650 | 512-token chunks with pgvector embeddings |

### User & Workflow Tables

| Table | Description |
|-------|-------------|
| `user_watchlist` | Track deals with status/tags |
| `deal_notes` | Personal notes on deals |
| `saved_searches` | Saved filter criteria with alert flag |
| `search_history` | Recent search tracking |
| `company_xref` | Cross-reference Cortellis/EDGAR companies |

### Entity Resolution

| Table | Description |
|-------|-------------|
| `company_xref` | Maps cortellis_id <-> CIK (SEC identifier) |
| 692 companies linked across systems via automated trigram matching + manual curation |

## Key Design Decisions

- **`agreement_type`** (not `deal_type`) classifies deals into 21 types
- **`agreement_type = 'Company - M&A (in whole or part)'`** identifies M&A deals (`is_merger_acquisition` is all NULL)
- **`drugs.name_display`** (not `name`) and **`drugs.phase_highest_now`** (not `phase`) are the correct column names
- **Financial disclosure**: Only 26.8% of deals have disclosed values - use `disclosed_only` filter
- **Federated architecture**: Two PostgreSQL databases kept separate with Neo4j as integration layer (lower risk than immediate merge)

## Development

### Rebuild After Code Changes

```bash
docker compose -f docker-compose.unified.yml build api frontend
docker compose -f docker-compose.unified.yml up -d
```

### Restart API Only

```bash
docker restart bd-api
```

### View Logs

```bash
# All services
docker compose -f docker-compose.unified.yml logs -f

# Specific service
docker compose -f docker-compose.unified.yml logs -f api
docker compose -f docker-compose.unified.yml logs -f crawl-worker
```

### Direct Database Access

```bash
# Cortellis DB
docker exec -it bd-cortellis-db psql -U cortellis -d cortellis

# Edgar DB
docker exec -it bd-edgar-source-db psql -U postgres -d deals

# Neo4j (via browser)
open http://localhost:7474
```

### Run Tests

```bash
docker exec bd-api pytest unified_api/tests/
```

## CLI Commands (ETL Pipeline)

### Data Sync

| Command | Description |
|---------|-------------|
| `full-sync` | Initial full sync of all deals from Cortellis API |
| `incremental-sync` | Sync only modified deals |
| `sync-contracts` | Download contract documents |

### Contract Indexing

| Command | Description |
|---------|-------------|
| `index-contracts` | Index contracts for full-text search |
| `embed-contracts` | Generate RAG embeddings (text-embedding-3-small) |
| `resume-embedding` | Resume interrupted embedding batch |
| `index-status` | Show indexing progress |

```bash
docker compose run --rm app python -m src.main <command>
```

## License

Proprietary - Internal use only.

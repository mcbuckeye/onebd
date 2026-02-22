# Testing Guide - BD Intelligence Platform

## Overview

The test suite validates the full stack of the BD Intelligence Platform:
- **Database connections** (Cortellis PostgreSQL, Edgar PostgreSQL, Neo4j)
- **Data integrity** (row counts, foreign keys, required fields, quality metrics)
- **Entity resolution** (company cross-reference matching between Cortellis and Edgar)
- **Search functionality** (fulltext, semantic/vector, unified cross-source)
- **API endpoints** (health, search, entities, Edgar, cross-reference, graph)
- **Graph sync** (Neo4j node/relationship creation, bulk sync, queries)

## Prerequisites

All tests run **inside the Docker container** (`bd-api`). The Docker stack must be running with all services healthy.

### Start the stack

```bash
docker compose -f docker-compose.unified.yml up -d
```

### Verify services are healthy

```bash
docker compose -f docker-compose.unified.yml ps
```

All services should show `(healthy)`:
- `bd-cortellis-db` - Cortellis PostgreSQL (port 5433)
- `bd-edgar-source-db` - Edgar PostgreSQL (port 5432)
- `bd-neo4j` - Neo4j Graph Database (ports 7474, 7687)
- `bd-redis` - Redis cache/broker (port 6379)
- `bd-api` - FastAPI application (port 8000)

### Install test dependencies (first time)

```bash
docker exec bd-api pip install pytest pytest-asyncio pytest-cov pytest-timeout
```

## Running Tests

### All tests

```bash
docker exec bd-api python -m pytest unified_api/tests/ -v
```

### Unit tests only

```bash
docker exec bd-api python -m pytest unified_api/tests/unit/ -v
```

### Integration tests only

```bash
docker exec bd-api python -m pytest unified_api/tests/integration/ -v
```

### Specific test file

```bash
docker exec bd-api python -m pytest unified_api/tests/unit/test_data_integrity.py -v
docker exec bd-api python -m pytest unified_api/tests/integration/test_graph_sync.py -v
```

### Specific test class or method

```bash
docker exec bd-api python -m pytest unified_api/tests/unit/test_data_integrity.py::TestCortellisDataIntegrity -v
docker exec bd-api python -m pytest unified_api/tests/unit/test_data_integrity.py::TestCortellisDataIntegrity::test_deals_table_exists_and_populated -v
```

### By marker

```bash
# Only Cortellis DB tests
docker exec bd-api python -m pytest unified_api/tests/ -m cortellis -v

# Only Edgar DB tests
docker exec bd-api python -m pytest unified_api/tests/ -m edgar -v

# Only Neo4j tests
docker exec bd-api python -m pytest unified_api/tests/ -m neo4j -v

# Skip slow tests
docker exec bd-api python -m pytest unified_api/tests/ -m "not slow" -v
```

### With coverage

```bash
docker exec bd-api python -m pytest unified_api/tests/ --cov=unified_api --cov-report=term-missing
```

## Test Structure

```
unified_api/tests/
├── conftest.py                          # Shared fixtures and configuration
├── pytest.ini                           # Pytest configuration
├── unit/
│   ├── __init__.py
│   ├── test_database_connections.py     # DB connectivity, pools, schema
│   ├── test_data_integrity.py           # Row counts, FK integrity, quality
│   └── test_entity_resolution.py        # Company xref matching validation
└── integration/
    ├── __init__.py
    ├── test_api_endpoints.py            # FastAPI endpoint testing
    ├── test_search.py                   # Fulltext, semantic, deal search
    └── test_graph_sync.py              # Neo4j sync and graph queries
```

## Test Categories

### Unit Tests (68 tests)

| File | Tests | What it validates |
|------|-------|-------------------|
| `test_database_connections.py` | 20 | Cortellis/Edgar connectivity, pgvector extension, session management, connection pools, schema verification |
| `test_data_integrity.py` | 27 | Row counts within expected ranges, FK integrity, required fields populated, embedding coverage, index existence |
| `test_entity_resolution.py` | 21 | company_xref structure, coverage metrics, match confidence, known company mappings (Pfizer, AbbVie, etc.), CIK/ticker format validation |

### Integration Tests (64 tests)

| File | Tests | What it validates |
|------|-------|-------------------|
| `test_api_endpoints.py` | 24 | Health endpoints, search API, entity CRUD, Edgar endpoints, xref lookup, response formats, CORS |
| `test_search.py` | 17 | Fulltext search (Cortellis + Edgar), semantic vector similarity, unified cross-source search, deal filtering, pagination, sorting, performance |
| `test_graph_sync.py` | 23 | Neo4j connectivity, APOC plugin, GraphSyncService CRUD, company/deal node sync, relationship creation, bulk sync, graph queries |

## Fixtures

Defined in `conftest.py`:

| Fixture | Scope | Description |
|---------|-------|-------------|
| `cortellis_engine` | session | SQLAlchemy engine for Cortellis DB |
| `edgar_engine` | session | SQLAlchemy engine for Edgar DB |
| `edgar_source_engine` | session | Alias for edgar_engine (backwards compat) |
| `cortellis_session` | function | Transactional session, auto-rollback |
| `edgar_session` | function | Transactional session, auto-rollback |
| `edgar_source_session` | function | Transactional session, auto-rollback |
| `neo4j_driver` | session | Neo4j driver with connectivity verification |
| `neo4j_session` | function | Neo4j session |
| `api_client` | module | FastAPI TestClient |
| `mock_cortellis_session` | function | Mock session for unit tests without DB |
| `mock_edgar_session` | function | Mock session for unit tests without DB |
| `sample_deal_data` | function | Sample deal dict |
| `sample_company_data` | function | Sample company dict |
| `sample_edgar_company_data` | function | Sample Edgar company dict |
| `sample_contract_chunk` | function | Sample contract chunk dict |
| `sample_xref_data` | function | Sample cross-reference dict |

## Markers

| Marker | Description |
|--------|-------------|
| `@pytest.mark.integration` | Requires live database connections |
| `@pytest.mark.cortellis` | Requires Cortellis PostgreSQL |
| `@pytest.mark.edgar` | Requires Edgar PostgreSQL |
| `@pytest.mark.neo4j` | Requires Neo4j |
| `@pytest.mark.slow` | Long-running tests (vector search, bulk sync) |

## Configuration

Tests auto-detect connection URLs from environment variables:

| Variable | Default (inside Docker) |
|----------|------------------------|
| `CORTELLIS_DB_URL` | `postgresql://cortellis:changeme@cortellis-db:5432/cortellis` |
| `EDGAR_SOURCE_DB_URL` | `postgresql://postgres:postgres@edgar-source-db:5432/deals` |
| `NEO4J_URI` | `bolt://neo4j:7687` |
| `NEO4J_USER` | `neo4j` |
| `NEO4J_PASSWORD` | `bdplatform123` |

### Skip flags for partial environments

```bash
SKIP_CORTELLIS_TESTS=true  # Skip Cortellis DB tests
SKIP_EDGAR_TESTS=true      # Skip Edgar DB tests
SKIP_NEO4J_TESTS=true      # Skip Neo4j tests
```

## E2E Tests (Playwright)

End-to-end browser tests using Playwright, running in a Docker container against the live frontend.

### Prerequisites

The main Docker stack must be running (`docker compose -f docker-compose.unified.yml up -d`).

### Running E2E tests

```bash
# Run all e2e tests (first run downloads Playwright image ~1GB)
docker compose -f docker-compose.e2e.yml run --rm playwright

# Run only page load + responsive tests (no OpenAI needed)
docker compose -f docker-compose.e2e.yml run --rm playwright \
  bash -c "pip install -q -r /app/e2e/requirements.txt && playwright install chromium && \
  pytest /app/e2e/test_page_load.py /app/e2e/test_responsive.py -v --base-url=http://frontend:80"

# Run chat tests (requires OPENAI_API_KEY in main stack)
docker compose -f docker-compose.e2e.yml run --rm playwright \
  bash -c "pip install -q -r /app/e2e/requirements.txt && playwright install chromium && \
  pytest /app/e2e/ -m chat -v --base-url=http://frontend:80"

# View failure screenshots/videos
ls test-results/
```

### E2E Test Structure

```
e2e/
├── conftest.py              # Playwright fixtures, health wait
├── pytest.ini               # Config (base_url, markers)
├── requirements.txt         # pytest-playwright pinned deps
├── test_page_load.py        # Page load, sidebar, welcome state (5 tests)
├── test_chat_flow.py        # Send messages, responses, new chat (5 tests)
├── test_search_modes.py     # Auto/SQL/RAG mode toggle (3 tests)
├── test_deal_detail.py      # Deal panel open/close, sections (3 tests)
├── test_responsive.py       # Mobile viewport, sidebar toggle (3 tests)
└── helpers/
    └── selectors.py         # Centralized data-testid selectors
```

### E2E Markers

| Marker | Description |
|--------|-------------|
| `chat` | Requires LLM (OpenAI) - sends messages and waits for responses |
| `slow` | Long-running tests |

## Current Test Results

```
Unit tests:       68 passed, 1 skipped
Integration tests: 55 passed, 6 skipped
E2E tests:        17 passed, 2 skipped
Total:            140 passed, 9 skipped, 0 failures
```

Skipped tests:
- `test_chunks_embedding_index` - Vector index on Edgar chunks not yet created
- `test_companies_list_endpoint` - Companies API returns 404 (endpoint not at `/api/companies`)
- `test_company_detail_endpoint` - Depends on companies list
- `test_deal_detail_endpoint` - Depends on deals list format
- `test_network_endpoint` - Depends on company list
- `test_protected_endpoints_require_auth` - Auth not yet implemented
- `test_rate_limit_headers` - Rate limiting not yet implemented

## Schema Gotchas (Common Test Pitfalls)

These are documented lessons from debugging test failures:

- **`deals.deal_type` is EMPTY** - Always use `deals.agreement_type` for the 21 deal classifications
- **`company_xref` uses `cik` column** (not `edgar_company_id`) to link to Edgar companies
- **Edgar `chunks` table uses `vector` column** (not `embedding`) for pgvector embeddings
- **Edgar `documents.doc_type` is all "filing"** - Form types (10-K, 8-K) are in `raw_documents.filing_metadata->>'form_type'`
- **Finance values are in millions** - `deal_finance_summary.total_projected_current_amount` max is ~160,150 ($160B)
- **Edgar companies CIK coverage** - Only ~26% (710/2688) of Edgar companies have CIK identifiers
- **Match confidence** - Only ~24% of xref matches are "high confidence" (>=0.9); many are trigram-based

## Adding New Tests

1. Place unit tests in `unified_api/tests/unit/`
2. Place integration tests in `unified_api/tests/integration/`
3. Use appropriate markers (`@pytest.mark.cortellis`, etc.)
4. Use fixtures from `conftest.py` for database sessions
5. Wrap potentially-unavailable service calls in try/except with `pytest.skip()`
6. After writing tests, run inside Docker: `docker exec bd-api python -m pytest <path> -v`

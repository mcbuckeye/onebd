# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Run Commands

### Docker (Primary)
```bash
# Start all services (frontend, API, database)
docker compose up -d

# Rebuild after code changes
docker compose build api frontend
docker compose up -d

# View logs
docker compose logs -f api
docker compose logs -f frontend

# Run CLI commands
docker compose run --rm app python -m src.main <command>
```

### Frontend Development (Local)
```bash
cd frontend
npm install
npm run dev      # Dev server at localhost:5173
npm run build    # Production build
npm run lint     # ESLint
```

### CLI Commands
```bash
# Data sync
docker compose run --rm app python -m src.main full-sync
docker compose run --rm app python -m src.main incremental-sync
docker compose run --rm app python -m src.main sync-contracts

# Contract indexing
docker compose run --rm app python -m src.main index-contracts
docker compose run --rm app python -m src.main embed-contracts --api-batch 250
docker compose run --rm app python -m src.main resume-embedding --api-batch 250
docker compose run --rm app python -m src.main index-status

# Search
docker compose run --rm app python -m src.main search-contracts "query"
docker compose run --rm app python -m src.main search-similar "query"
```

## Architecture

Three main components communicate through PostgreSQL:

1. **Python CLI** (`src/`) - ETL pipeline that syncs data from Cortellis REST API
2. **FastAPI Backend** (`api/`) - REST API serving the chat interface
3. **React Frontend** (`frontend/`) - Chat UI with Vite + TypeScript + Tailwind

### Data Flow

```
Cortellis API → api_client.py → sync.py → PostgreSQL
                                              ↓
                              contract_indexer.py (full-text + embeddings)
                                              ↓
User Question → FastAPI → query_agent.py → OpenAI GPT
                              ↓
                    Auto-detect: SQL or RAG
                              ↓
              SQL: generate query → execute → explain results
              RAG: embed question → vector search → answer with context
```

### Key Modules

- **`src/sync.py`** - `SyncService` orchestrates full/incremental syncs, transforms API XML to ORM objects
- **`src/api_client.py`** - `CortellisClient` handles authentication and API calls (token-based, 30 records per batch max)
- **`src/contract_indexer.py`** - `ContractIndexer` manages full-text search (PostgreSQL tsvector) and RAG embeddings (pgvector)
- **`agent/query_agent.py`** - `QueryAgent` routes questions to SQL generation or RAG based on keyword detection
- **`api/main.py`** - FastAPI endpoints: `/chat`, `/health`, `/index-status`, `/search/*`

### Database

PostgreSQL 16 with pgvector extension. Key tables:
- `deals` - 145k pharmaceutical deal records
- `contract_content` - Full contract text with tsvector index (26k docs)
- `contract_chunks` - ~500 token chunks with OpenAI embeddings (900k rows)

### OpenAI Integration

- Model: `gpt-4o` (configurable via `OPENAI_MODEL`)
- Embeddings: `text-embedding-3-small` (1536 dimensions)
- Batch limit: 250 chunks per API call to stay under 300k token limit

## Important Patterns

### Query Agent Mode Detection
`query_agent.py` checks for contract-related keywords (royalty, milestone, indemnif, etc.) to route to RAG vs SQL. Force modes with `rag <query>` or via API `mode` parameter.

### Contract Chunking
Contracts are split into ~512 token chunks with 50 token overlap using tiktoken. Chunks are stored in `contract_chunks` with pgvector embeddings for cosine similarity search.

### API Proxy
Frontend nginx proxies `/api/*` to FastAPI backend. In dev mode, Vite proxies the same routes.

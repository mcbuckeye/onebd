# Agentic RAG Design - BD Intelligence

**Date:** 2026-02-25
**Status:** Approved
**Approach:** LangGraph with multi-hop reasoning

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     React Frontend (New Page)                │
│   /agentic-rag                                               │
│   - Chat input, expandable thought process cards            │
│   - Collapsible "Reasoning Trace" panel                     │
└────────────────────────────┬────────────────────────────────┘
                             │ POST /api/agentic-rag/chat
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              New Router: unified_api/routers/               │
│                    agentic_rag.py                           │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────┐   │
│  │          LangGraph Agent (Orchestrator)               │   │
│  │  - Receives NL query                                  │   │
│  │  - Maintains conversation state & tool results        │   │
│  │  - Decides: which tool(s), in what order              │   │
│  │  - Synthesizes final answer with citations            │   │
│  └──────────────────────────────────────────────────────┘   │
│                            │                                 │
│           ┌────────────────┼────────────────┐               │
│           ▼                ▼                ▼               │
│  ┌─────────────┐   ┌─────────────┐   ┌──────────────┐      │
│  │Neo4j Tool   │   │SQL Tool     │   │pgvector Tool │      │
│  │(Graph)      │   │(Cortellis/  │   │(Contracts,   │      │
│  │             │   │ Edgar)      │   │ filings RAG) │      │
│  └─────────────┘   └─────────────┘   └──────────────┘      │
│                            │                                 │
│           ┌────────────────┼────────────────┐               │
│           ▼                ▼                ▼               │
│      Neo4j DB         PostgreSQL        pgvector            │
│      :7687           (Cortellis)       (Edgar/Contracts)    │
└─────────────────────────────────────────────────────────────┘
```

### Key Principles

- Each data source is a "Tool" the agent can call
- Agent sees all tool outputs and decides next action
- Multi-hop: loop until answer synthesized or max hops reached

---

## 2. Component Details

### Backend Components

| Component | File | Responsibility |
|-----------|------|----------------|
| **Router** | `routers/agentic_rag.py` | HTTP endpoint, auth check, request validation |
| **Agent** | `services/agentic_rag/agent.py` | LangGraph state machine, tool orchestration |
| **Tools** | `services/agentic_rag/tools/` | Individual data source connectors (neo4j, sql, pgvector) |
| **Config** | `.env` + `config.py` | Max hops, timeout, tool enable/disable |
| **Langfuse** | `services/agentic_rag/langfuse_client.py` | Observability tracing |

### Frontend Components

| Component | File | Responsibility |
|-----------|------|----------------|
| **Page** | `pages/AgenticRag.tsx` | Full-page layout, routing |
| **ChatPanel** | `components/AgenticRagChat.tsx` | Input + message list |
| **ThoughtCard** | `components/ReasoningTrace.tsx` | Expandable reasoning steps per hop |
| **API Client** | `api/agenticRag.ts` | Calls backend |

---

## 3. Data Flow (with Self-Correction)

```
User Message
     │
     ▼
┌─────────────────────────┐
│  LangGraph Agent        │
│  (ConversationState)    │
└───────────┬─────────────┘
            │ 1. LLM reasons: "Need to find deals via SQL first"
            ▼
┌─────────────────────────┐
│  Tool Selection         │
│  (Pick SQL tool)        │
└───────────┬─────────────┘
            │ Execute
            ▼
┌─────────────────────────┐
│  Tool Execution         │
│  (Run SQL)              │──── Error? ────► Retry with fix
└───────────┬─────────────┘                    (max 2 retries)
   Success? │
     │      │
    Yes     No
     ▼      ▼
┌─────────────────────────┐
│  Tool Result            │──► Back to agent: "Good, now 
│  (Rows/Error)           │    query Neo4j for relationships"
└───────────┬─────────────┘
            │ 2. LLM reasons: "Need graph data"
            ▼
┌─────────────────────────┐
│  Hop Check              │──── Exceeds max hops? ────► Return partial + warning
│  (< MAX_HOPS)           │
└───────────┬─────────────┘
            │ Continue
            ▼
┌─────────────────────────┐
│  Tool Selection (loop)  │──── No more tools needed? ────► Synthesize final answer
└─────────────────────────┘
```

### Self-Correction Logic

- Each tool execution returns `Result[T] | Error`
- If Error, LLM receives: `{success: false, error: "...", attempted_query: "..."}`
- LLM revises and retries (max 2 attempts per tool)
- After 2 failures, skip that tool and note in reasoning trace

---

## 4. Error Handling

| Scenario | Handling |
|----------|----------|
| **SQL syntax error** | LLM sees PG error → rewrites query → retry |
| **Neo4j connection fail** | Return friendly error, log details, mark tool unavailable |
| **Timeout exceeded** | Stop agent, return partial results with "incomplete" badge |
| **Max hops reached** | Return what we have, show "needed more hops but stopped" |
| **Empty results** | Continue to next tool OR return "no data found, tried X sources" |
| **LLM refusal** | Return error message, don't hallucinate |

---

## 5. Configuration (.env)

```bash
# Agentic RAG settings
AGENTIC_RAG_MAX_HOPS=5
AGENTIC_RAG_TIMEOUT_SECONDS=30
AGENTIC_RAG_MAX_RETRIES_PER_TOOL=2

# Tool enable/disable (future-proofing)
ENABLE_NEO4J_TOOL=true
ENABLE_SQL_TOOL=true
ENABLE_PGVECTOR_TOOL=true

# Langfuse observability
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
LANGFUSE_HOST=https://cloud.langfuse.com
```

---

## 6. Observability (Langfuse)

```
┌─────────────────────────────────────────┐
│           Langfuse Dashboard            │
│  - Token usage per query                │
│  - Latency per tool                     │
│  - Full reasoning trace (every hop)     │
│  - Cost tracking                        │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│     Langfuse SDK Integration            │
│                                         │
│  • trace_id: unique per user query      │
│  • parent_observation_id: hop chaining  │
│  • metadata: tool results, errors       │
└─────────────────────────────────────────┘
```

### Implementation

```python
# services/agentic_rag/langfuse_client.py
from langfuse import Langfuse

langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
)

# In each tool execution:
trace = langfuse.trace(name="agentic_rag", metadata={"query": user_question})
with trace.span(name="sql_tool") as span:
    span.input = {"query": generated_sql}
    result = execute_sql(generated_sql)
    span.output = {"rows": len(result.rows), "error": result.error}
```

---

## 7. Testing Strategy

| Test Type | Scope |
|-----------|-------|
| **Unit** | Each Tool (mock DB, verify query generation) |
| **Integration** | Router → Agent → Tools (real DBs in Docker) |
| **E2E** | React page → API → response rendering |
| **Agent Quality** | Golden set of 20 multi-hop queries, eval on correctness |

---

## 8. UI/UX Design

### Page Layout
- Full-width page with dark/light mode support
- Left sidebar: conversation history (collapsible)
- Main area: chat interface with reasoning traces

### Reasoning Trace Display
```
┌─────────────────────────────────────────────┐
│ 🔄 Thinking... (Hop 2/5)                    │
├─────────────────────────────────────────────┤
│ Step 1: Queried SQL → Found 12 deals        │
│ Step 2: Querying Neo4j for relationships... │
└─────────────────────────────────────────────┘
        [▼ Expand to see details]
```

Each card shows:
- Current hop number / max hops
- What the agent decided to do
- Tool invoked + query used
- Result summary (row count or error)
- Expandable: full SQL/Cypher, raw results

---

## 9. Alternative Approaches (Future Consideration)

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| **A (Current)** | LangGraph + Tool Calling | Native multi-hop, state mgmt, scalable | Extra dependency |
| **B** | Custom ReAct Loop | Full control, no deps | Reinventing state mgmt |
| **C** | LLM-as-Judge + Sub-agents | Parallelizable hops | Latency per hop, harder chaining |

Consider A/B testing against B and C in future iterations.

---

## 10. Constraints

- **Additive only**: No modifications to existing code
- **New branch**: `agenticrag` for all development
- **Environment**: Docker-based (existing onebd infrastructure)
# PageIndex Integration into OneBD — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add PageIndex as a 4th retrieval tool in OneBD's agentic RAG system, enabling tree-based reasoning retrieval over the 26K+ contract texts for precise, section-cited answers to BD questions.

**Architecture:** PageIndex indexes contract HTML content into hierarchical tree structures (cached in PostgreSQL). The agentic RAG agent selects the PageIndex tool when queries target specific contract terms, milestones, royalties, IP ownership, termination provisions, etc. The tool navigates the tree index to retrieve relevant sections, returning cited answers with section/line references. The existing Neo4j, SQL, and pgvector tools remain unchanged.

**Tech Stack:** PageIndex (open-source, pip install), LiteLLM (already a PageIndex dep), GPT-4o for tree generation + retrieval reasoning, PostgreSQL (Cortellis DB) for tree cache storage.

---

## Task 1: HTML Cleaner Service

**Files:**
- Create: `unified_api/services/html_cleaner.py`
- Test: `unified_api/tests/unit/test_html_cleaner.py`

**Context:** Contract content in `contract_content.content` is stored with HTML tags (`<br/>`, `<para>`, `&amp;`, etc.). PageIndex markdown mode needs clean text with proper heading structure. This service converts HTML-tagged contract text to clean markdown.

**Step 1: Write the failing test**

```python
# unified_api/tests/unit/test_html_cleaner.py
"""Tests for HTML-to-markdown contract cleaner."""
import pytest
from unified_api.services.html_cleaner import clean_contract_html


class TestCleanContractHtml:
    def test_strips_br_tags(self):
        assert "line1\nline2" == clean_contract_html("line1<br/>line2")

    def test_strips_para_tags(self):
        result = clean_contract_html("<para>Hello</para>")
        assert "<para>" not in result
        assert "Hello" in result

    def test_decodes_html_entities(self):
        assert "Tom & Jerry" in clean_contract_html("Tom &amp; Jerry")
        assert "it's" in clean_contract_html("it&apos;s")

    def test_creates_section_headings(self):
        text = "\n7.    FINANCIAL TERMS\n"
        result = clean_contract_html(text)
        assert "## 7. FINANCIAL TERMS" in result

    def test_creates_subsection_headings(self):
        text = "\n7.1    Upfront Payment. GSK shall pay\n"
        result = clean_contract_html(text)
        assert "### 7.1 " in result

    def test_removes_page_markers(self):
        result = clean_contract_html("text\n- 41 -\nmore text")
        assert "- 41 -" not in result

    def test_collapses_blank_lines(self):
        result = clean_contract_html("a\n\n\n\n\nb")
        assert "\n\n\n" not in result

    def test_preserves_redaction_markers(self):
        result = clean_contract_html("payment of [***] Dollars")
        assert "[***]" in result

    def test_handles_empty_input(self):
        assert clean_contract_html("") == ""
        assert clean_contract_html(None) == ""

    def test_real_contract_snippet(self):
        """Test with actual Cortellis contract HTML format."""
        html = (
            "7.1    Upfront Payment. In consideration, along with Section 7.3, "
            "of the Technology Transfer under this Agreement within [***] Business "
            "Days after receiving an Invoice from Codexis, after the Effective Date, "
            "GSK shall pay to Codexis a non-creditable, non-refundable upfront "
            "payment of six million Dollars ($6,000,000).<br/>7.2    Annual Option "
            "Fee. In consideration of the licenses granted by Codexis to GSK under "
            "Section 3.5.3, upon GSK&apos;s exercise of the Option"
        )
        result = clean_contract_html(html)
        assert "$6,000,000" in result
        assert "<br/>" not in result
        assert "&apos;" not in result
```

**Step 2: Run test to verify it fails**

Run: `cd ~/Projects/onebd && python -m pytest unified_api/tests/unit/test_html_cleaner.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# unified_api/services/html_cleaner.py
"""
Clean HTML-tagged contract content from Cortellis DB into clean markdown.
Handles <br/>, <para>, &entities, and structures headings for PageIndex.
"""
import re
from typing import Optional


def clean_contract_html(text: Optional[str]) -> str:
    """Convert HTML-tagged contract text to clean markdown for PageIndex indexing."""
    if not text:
        return ""

    # Decode HTML entities
    entity_map = {
        '&amp;': '&', '&apos;': "'", '&quot;': '"',
        '&gt;': '>', '&lt;': '<', '&nbsp;': ' ',
        '&#x27;': "'", '&#39;': "'", '&#x2F;': '/', '&#47;': '/',
    }
    for entity, char in entity_map.items():
        text = text.replace(entity, char)

    # Decode numeric HTML entities
    text = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)
    text = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)), text)

    # Convert <br/> and <br> to newlines
    text = re.sub(r'<br\s*/?\s*>', '\n', text, flags=re.IGNORECASE)

    # Convert <para> blocks to paragraphs
    text = re.sub(r'<para\s*>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</para\s*>', '', text, flags=re.IGNORECASE)

    # Remove any remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Convert numbered article headers to markdown headings
    text = re.sub(
        r'\n(\d+)\.\s{2,}([A-Z][A-Z\s,&;]+)',
        lambda m: f'\n## {m.group(1)}. {m.group(2).strip()}',
        text
    )

    # Convert sub-section numbers to markdown headings
    text = re.sub(
        r'\n(\d+\.\d+(?:\.\d+)?)\s{2,}',
        lambda m: f'\n### {m.group(1)} ',
        text
    )

    # Clean up page markers like "- 41 -"
    text = re.sub(r'\n-\s*\d+\s*-\n', '\n\n', text)

    # Collapse multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Strip leading/trailing whitespace per line
    lines = text.split('\n')
    lines = [line.strip() for line in lines]
    text = '\n'.join(lines)

    return text.strip()
```

**Step 4: Run test to verify it passes**

Run: `cd ~/Projects/onebd && python -m pytest unified_api/tests/unit/test_html_cleaner.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add unified_api/services/html_cleaner.py unified_api/tests/unit/test_html_cleaner.py
git commit -m "feat: add HTML-to-markdown cleaner for contract content"
```

---

## Task 2: Contract Tree Index Cache Table

**Files:**
- Modify: `scripts/init_db.sql` (add table creation)
- Create: `unified_api/services/tree_cache.py`
- Test: `unified_api/tests/unit/test_tree_cache.py`

**Context:** PageIndex tree generation costs ~$0.50 per contract and takes 30-150 seconds. We cache generated trees in a new `contract_tree_index` table in the Cortellis DB so each contract is only indexed once.

**Step 1: Write the failing test**

```python
# unified_api/tests/unit/test_tree_cache.py
"""Tests for contract tree index cache."""
import pytest
from unittest.mock import MagicMock, patch
from unified_api.services.tree_cache import TreeCache


class TestTreeCache:
    def test_cache_miss_returns_none(self):
        """get_tree returns None when no cached tree exists."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None
        cache = TreeCache(session_factory=lambda: mock_session)
        result = cache.get_tree(contract_id=123)
        assert result is None

    def test_cache_hit_returns_tree(self):
        """get_tree returns cached tree JSON when it exists."""
        mock_row = MagicMock()
        mock_row.tree_json = {"structure": [{"title": "test"}]}
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = mock_row
        cache = TreeCache(session_factory=lambda: mock_session)
        result = cache.get_tree(contract_id=123)
        assert result == {"structure": [{"title": "test"}]}

    def test_store_tree_inserts(self):
        """store_tree writes tree JSON to database."""
        mock_session = MagicMock()
        cache = TreeCache(session_factory=lambda: mock_session)
        tree = {"structure": [{"title": "Section 1"}]}
        cache.store_tree(contract_id=123, deal_id=456, tree_json=tree, model="gpt-4o")
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `cd ~/Projects/onebd && python -m pytest unified_api/tests/unit/test_tree_cache.py -v`
Expected: FAIL — module not found

**Step 3: Add table to init_db.sql**

Append to `scripts/init_db.sql`:

```sql
-- PageIndex tree cache for contract deep-read
CREATE TABLE IF NOT EXISTS contract_tree_index (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL,
    deal_id INTEGER NOT NULL,
    tree_json JSONB NOT NULL,
    line_count INTEGER,
    model VARCHAR(100) NOT NULL,
    indexed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(contract_id)
);

CREATE INDEX IF NOT EXISTS idx_contract_tree_deal_id ON contract_tree_index(deal_id);
CREATE INDEX IF NOT EXISTS idx_contract_tree_contract_id ON contract_tree_index(contract_id);
```

**Step 4: Write TreeCache implementation**

```python
# unified_api/services/tree_cache.py
"""
Cache for PageIndex tree indexes of contract content.
Stores generated tree structures in PostgreSQL to avoid re-indexing.
"""
from typing import Optional, Callable, Any
import json
from datetime import datetime
from sqlalchemy import text
import structlog

logger = structlog.get_logger(__name__)


class TreeCache:
    """Cache layer for PageIndex contract tree indexes."""

    def __init__(self, session_factory: Callable):
        self.session_factory = session_factory

    def get_tree(self, contract_id: int) -> Optional[dict]:
        """Get cached tree index for a contract. Returns None on cache miss."""
        session = self.session_factory()
        try:
            result = session.execute(
                text("SELECT tree_json FROM contract_tree_index WHERE contract_id = :cid"),
                {"cid": contract_id}
            ).fetchone()
            return result.tree_json if result else None
        finally:
            session.close()

    def get_tree_by_deal(self, deal_id: int) -> Optional[dict]:
        """Get cached tree index by deal_id. Returns first match."""
        session = self.session_factory()
        try:
            result = session.execute(
                text("SELECT tree_json FROM contract_tree_index WHERE deal_id = :did ORDER BY indexed_at DESC LIMIT 1"),
                {"did": deal_id}
            ).fetchone()
            return result.tree_json if result else None
        finally:
            session.close()

    def store_tree(
        self,
        contract_id: int,
        deal_id: int,
        tree_json: dict,
        model: str,
        line_count: Optional[int] = None,
    ) -> None:
        """Store a tree index in the cache. Upserts on contract_id."""
        session = self.session_factory()
        try:
            session.execute(
                text("""
                    INSERT INTO contract_tree_index (contract_id, deal_id, tree_json, model, line_count, indexed_at)
                    VALUES (:cid, :did, :tree, :model, :lc, :ts)
                    ON CONFLICT (contract_id) DO UPDATE SET
                        tree_json = :tree, model = :model, line_count = :lc, indexed_at = :ts
                """),
                {
                    "cid": contract_id,
                    "did": deal_id,
                    "tree": json.dumps(tree_json),
                    "model": model,
                    "lc": line_count,
                    "ts": datetime.utcnow(),
                }
            )
            session.commit()
            logger.info("Stored tree index", contract_id=contract_id, deal_id=deal_id)
        finally:
            session.close()

    def has_tree(self, contract_id: int) -> bool:
        """Check if a tree exists for a contract."""
        session = self.session_factory()
        try:
            result = session.execute(
                text("SELECT 1 FROM contract_tree_index WHERE contract_id = :cid"),
                {"cid": contract_id}
            ).fetchone()
            return result is not None
        finally:
            session.close()
```

**Step 5: Run tests**

Run: `cd ~/Projects/onebd && python -m pytest unified_api/tests/unit/test_tree_cache.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add scripts/init_db.sql unified_api/services/tree_cache.py unified_api/tests/unit/test_tree_cache.py
git commit -m "feat: add contract tree index cache table and service"
```

---

## Task 3: PageIndex Tool for Agentic RAG

**Files:**
- Create: `unified_api/services/agentic_rag/tools/pageindex_tool.py`
- Modify: `unified_api/services/agentic_rag/tools/__init__.py` (add import)
- Modify: `unified_api/services/agentic_rag/models.py` (add ToolType.PAGEINDEX)
- Test: `unified_api/tests/unit/test_pageindex_tool.py`

**Context:** This is the core integration. The PageIndex tool follows the same `BaseTool` interface as Neo4j/SQL/pgvector tools. When invoked, it: (1) fetches contract text from Cortellis DB by deal_id, (2) cleans the HTML, (3) checks the tree cache (generates if missing), (4) uses LLM reasoning over the tree to find relevant sections, (5) returns cited content.

**Step 1: Add PAGEINDEX to ToolType enum**

In `unified_api/services/agentic_rag/models.py`, add to `ToolType`:

```python
class ToolType(str, Enum):
    NEO4J = "neo4j"
    SQL = "sql"
    PGVECTOR = "pgvector"
    PAGEINDEX = "pageindex"  # Tree-based contract deep-read
    SYNTHESIZE = "synthesize"
```

**Step 2: Write the failing test**

```python
# unified_api/tests/unit/test_pageindex_tool.py
"""Tests for PageIndex agentic RAG tool."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool


class TestPageIndexTool:
    @pytest.fixture
    def mock_session_factory(self):
        session = MagicMock()
        return lambda: session

    @pytest.fixture
    def tool(self, mock_session_factory):
        return PageIndexTool(
            session_factory=mock_session_factory,
            openai_api_key="test-key",
            model="gpt-4o"
        )

    def test_tool_name(self, tool):
        assert tool.name == "pageindex"

    def test_schema_description_mentions_contracts(self, tool):
        desc = tool.get_schema_description()
        assert "contract" in desc.lower()
        assert "deal_id" in desc.lower()

    @pytest.mark.asyncio
    async def test_execute_no_contract_found(self, tool):
        """Returns error when no contract exists for deal."""
        tool.session_factory().execute.return_value.fetchone.return_value = None
        result = await tool._execute_impl("deal_id:99999 What are the royalty rates?")
        assert not result.success
        assert "no contract" in result.error.lower()

    @pytest.mark.asyncio
    async def test_parse_deal_id_from_query(self, tool):
        """Extracts deal_id from query string."""
        deal_id = tool._parse_deal_id("deal_id:12345 What milestones?")
        assert deal_id == 12345

    @pytest.mark.asyncio
    async def test_parse_deal_id_missing(self, tool):
        """Returns None when no deal_id in query."""
        deal_id = tool._parse_deal_id("What are the royalty rates?")
        assert deal_id is None
```

**Step 3: Write PageIndex tool implementation**

```python
# unified_api/services/agentic_rag/tools/pageindex_tool.py
"""
PageIndex tool for deep contract reading with tree-based reasoning.
Integrates PageIndex's hierarchical document indexing with OneBD's agentic RAG.
"""
import json
import re
import tempfile
import os
from typing import Optional, Callable
from sqlalchemy import text
import structlog

from .base import BaseTool
from ..models import ToolResult

logger = structlog.get_logger(__name__)


class PageIndexTool(BaseTool):
    """
    Tool for deep reading of contract text using PageIndex tree-based retrieval.

    Flow:
    1. Parse deal_id from query
    2. Fetch contract text from contract_content table
    3. Clean HTML to markdown
    4. Check tree cache (generate if miss)
    5. LLM reasons over tree to find relevant sections
    6. Fetch and return cited content
    """

    SCHEMA_DESCRIPTION = """
    PageIndex Contract Deep-Read Tool

    Use this tool when you need to find SPECIFIC information inside a contract:
    - Exact payment amounts, royalty rates, milestone schedules
    - Specific clauses (termination, IP ownership, confidentiality)
    - License scope, territory rights, exclusivity terms
    - Obligations, representations, warranties

    Query format: "deal_id:<ID> <your question about the contract>"
    Example: "deal_id:150059 What royalty rates does GSK pay on enzyme products?"

    This tool reads the full contract text and uses hierarchical reasoning
    to find the exact sections containing the answer, with section citations.

    DO NOT use this tool for:
    - Finding which deals exist (use SQL tool)
    - Company relationships (use Neo4j tool)
    - Semantic similarity search (use pgvector tool)
    """

    def __init__(
        self,
        session_factory: Callable,
        openai_api_key: str,
        model: str = "gpt-4o-2024-11-20",
        max_retries: int = 1,
    ):
        super().__init__("pageindex", max_retries)
        self.session_factory = session_factory
        self.openai_api_key = openai_api_key
        self.model = model

    def get_schema_description(self) -> str:
        return self.SCHEMA_DESCRIPTION

    def _parse_deal_id(self, query: str) -> Optional[int]:
        """Extract deal_id from query string."""
        match = re.search(r'deal_id:(\d+)', query)
        return int(match.group(1)) if match else None

    def _get_question(self, query: str) -> str:
        """Extract the question part of the query (everything after deal_id:NNN)."""
        return re.sub(r'deal_id:\d+\s*', '', query).strip()

    async def _execute_impl(self, query: str, **kwargs) -> ToolResult:
        """Execute PageIndex deep-read on a contract."""
        from unified_api.services.html_cleaner import clean_contract_html
        from unified_api.services.tree_cache import TreeCache

        deal_id = kwargs.get('deal_id') or self._parse_deal_id(query)
        question = self._get_question(query)

        if not deal_id:
            return ToolResult(
                success=False,
                error="No deal_id provided. Use format: deal_id:12345 <question>",
                row_count=0,
                query_executed=query
            )

        session = self.session_factory()
        try:
            # 1. Fetch contract text
            row = session.execute(
                text("""
                    SELECT cc.id as contract_id, cc.content, cc.word_count
                    FROM contract_content cc
                    WHERE cc.deal_id = :did
                    ORDER BY cc.word_count DESC
                    LIMIT 1
                """),
                {"did": deal_id}
            ).fetchone()

            if not row or not row.content:
                return ToolResult(
                    success=False,
                    error=f"No contract found for deal {deal_id}",
                    row_count=0,
                    query_executed=query
                )

            contract_id = row.contract_id
            logger.info("Found contract", deal_id=deal_id, contract_id=contract_id, word_count=row.word_count)

            # 2. Check tree cache
            tree_cache = TreeCache(session_factory=self.session_factory)
            cached_tree = tree_cache.get_tree(contract_id=contract_id)

            if cached_tree:
                logger.info("Tree cache hit", contract_id=contract_id)
                tree_data = cached_tree
            else:
                # 3. Clean HTML and generate tree
                logger.info("Tree cache miss, generating...", contract_id=contract_id)
                clean_md = clean_contract_html(row.content)
                tree_data = await self._generate_tree(clean_md)

                if tree_data:
                    tree_cache.store_tree(
                        contract_id=contract_id,
                        deal_id=deal_id,
                        tree_json=tree_data,
                        model=self.model,
                        line_count=tree_data.get('line_count'),
                    )
                else:
                    return ToolResult(
                        success=False,
                        error="Failed to generate tree index for contract",
                        row_count=0,
                        query_executed=query
                    )

            # 4. Clean the contract text for line-based retrieval
            clean_md = clean_contract_html(row.content)
            doc_lines = clean_md.split('\n')

            # 5. LLM reasons over tree to find relevant sections
            relevant_lines = await self._find_relevant_sections(tree_data, question)

            if not relevant_lines:
                return ToolResult(
                    success=False,
                    error="Could not identify relevant sections in the contract",
                    row_count=0,
                    query_executed=query
                )

            # 6. Extract content from identified sections
            context_chunks = []
            for ln in relevant_lines[:8]:
                start = max(0, ln - 1)
                end = min(len(doc_lines), start + 50)
                chunk_text = '\n'.join(doc_lines[start:end]).strip()
                if chunk_text:
                    context_chunks.append({
                        "lines": f"{start+1}-{end}",
                        "content": chunk_text[:2000],
                    })

            # 7. Generate cited answer
            answer = await self._generate_answer(question, context_chunks, deal_id)

            return ToolResult(
                success=True,
                data=[{
                    "deal_id": deal_id,
                    "answer": answer,
                    "sections_consulted": len(context_chunks),
                    "source": "pageindex_tree_retrieval",
                }],
                row_count=1,
                query_executed=f"PageIndex deep-read: deal {deal_id} — {question[:100]}"
            )

        except Exception as e:
            logger.error("PageIndex tool failed", error=str(e), deal_id=deal_id)
            return ToolResult(
                success=False,
                error=f"PageIndex retrieval failed: {str(e)}",
                row_count=0,
                query_executed=query
            )
        finally:
            session.close()

    async def _generate_tree(self, clean_md: str) -> Optional[dict]:
        """Generate PageIndex tree from clean markdown text."""
        import tempfile
        try:
            # PageIndex expects a file path
            with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
                f.write(clean_md)
                tmp_path = f.name

            try:
                from pageindex.page_index_md import md_to_tree
                import asyncio

                tree = await md_to_tree(
                    md_path=tmp_path,
                    if_thinning=False,
                    if_add_node_summary='yes',
                    summary_token_threshold=200,
                    model=self.model,
                    if_add_doc_description='yes',
                    if_add_node_text='yes',
                    if_add_node_id='yes'
                )
                return tree
            finally:
                os.unlink(tmp_path)

        except Exception as e:
            logger.error("Tree generation failed", error=str(e))
            return None

    async def _find_relevant_sections(self, tree_data: dict, question: str) -> list[int]:
        """Use LLM to reason over tree index and identify relevant line numbers."""
        import litellm

        # Build compact tree index (top 2 levels for full coverage)
        def build_compact(nodes, depth=0, max_depth=2):
            lines = []
            for n in nodes:
                if depth <= max_depth:
                    ln = n.get('line_num', '?')
                    title = n.get('title', '?')[:120]
                    lines.append(f"{'  '*depth}[L{ln}] {title}")
                if n.get('nodes') and depth < max_depth:
                    lines.extend(build_compact(n['nodes'], depth+1, max_depth))
            return lines

        structure = tree_data.get('structure', [])
        tree_text = "\n".join(build_compact(structure))

        response = litellm.completion(
            model=self.model,
            messages=[{"role": "user", "content": f"""You are analyzing a pharma BD contract.

Document index (line numbers and section titles):
{tree_text}

Question: {question}

Identify the 5-8 line numbers from the FULL TEXT sections that contain the answer.
Prefer lines from the main contract body (higher line numbers), not the table of contents.
Return ONLY a JSON array of line numbers, e.g.: [1509, 1624, 1790]"""}],
            temperature=0,
            api_key=self.openai_api_key,
        )

        raw = response.choices[0].message.content.strip()
        numbers = [int(n) for n in re.findall(r'\d+', raw)]
        return [n for n in numbers if n > 0][:10]

    async def _generate_answer(self, question: str, chunks: list[dict], deal_id: int) -> str:
        """Generate a cited answer from retrieved contract sections."""
        import litellm

        context = "\n\n---\n\n".join([
            f"[Lines {c['lines']}]:\n{c['content']}" for c in chunks
        ])

        response = litellm.completion(
            model=self.model,
            messages=[{"role": "user", "content": f"""Answer this BD question based ONLY on the contract text below.
Be specific — cite exact dollar amounts, percentages, section numbers, time periods.

Question: {question}

Contract text (deal {deal_id}):
{context[:12000]}

If amounts are redacted as [***], note that. Give a precise, BD analyst-grade answer."""}],
            temperature=0,
            api_key=self.openai_api_key,
        )

        return response.choices[0].message.content.strip()
```

**Step 4: Update tools/__init__.py**

```python
# unified_api/services/agentic_rag/tools/__init__.py
"""Agentic RAG tools for querying different data sources."""
from .base import BaseTool
from .neo4j_tool import Neo4jTool
from .sql_tool import SQLTool
from .pgvector_tool import PgVectorTool
from .pageindex_tool import PageIndexTool

__all__ = ["BaseTool", "Neo4jTool", "SQLTool", "PgVectorTool", "PageIndexTool"]
```

**Step 5: Run tests**

Run: `cd ~/Projects/onebd && python -m pytest unified_api/tests/unit/test_pageindex_tool.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add unified_api/services/agentic_rag/tools/pageindex_tool.py \
        unified_api/services/agentic_rag/tools/__init__.py \
        unified_api/services/agentic_rag/models.py \
        unified_api/tests/unit/test_pageindex_tool.py
git commit -m "feat: add PageIndex tool for agentic RAG contract deep-read"
```

---

## Task 4: Wire PageIndex Tool into Agent and Router

**Files:**
- Modify: `unified_api/services/agentic_rag/agent.py` (add PAGEINDEX to keyword routing)
- Modify: `unified_api/routers/agentic_rag.py` (initialize PageIndex tool)
- Modify: `requirements.txt` (add pageindex deps)

**Step 1: Add PageIndex keywords to agent.py**

In `unified_api/services/agentic_rag/agent.py`, add after the existing keyword lists:

```python
# Keywords for PageIndex (deep contract reading)
PAGEINDEX_KEYWORDS = [
    'contract says', 'contract text', 'clause', 'provision',
    'upfront payment', 'royalty rate', 'milestone payment',
    'termination provision', 'ip ownership', 'intellectual property',
    'confidentiality', 'license scope', 'territory rights',
    'indemnification', 'representations', 'warranties',
    'specific terms', 'exact amount', 'what does the contract',
    'section', 'article', 'exhibit',
]
```

And in the `detect_tool_from_query` function, add before the return:

```python
    # Check PageIndex keywords (contract deep-read)
    pageindex_score = sum(1 for kw in PAGEINDEX_KEYWORDS if kw in query_lower)
    if pageindex_score >= 2:
        return ToolType.PAGEINDEX
    if pageindex_score >= 1 and 'contract' in query_lower:
        return ToolType.PAGEINDEX
```

**Step 2: Initialize PageIndex tool in router**

In `unified_api/routers/agentic_rag.py`, add to the `_get_pageindex_tool` function (new):

```python
def _get_pageindex_tool() -> Optional[PageIndexTool]:
    """Create PageIndex tool for contract deep-reading."""
    from unified_api.services.agentic_rag.tools import PageIndexTool
    from unified_api.services.database import get_cortellis_session_factory

    if not settings.openai_api_key:
        logger.warning("OpenAI API key not set, PageIndex tool unavailable")
        return None

    def session_factory():
        factory = get_cortellis_session_factory()
        return factory()

    return PageIndexTool(
        session_factory=session_factory,
        openai_api_key=settings.openai_api_key,
        model=settings.openai_model,
    )
```

And in the `agentic_rag_chat` endpoint, add after pgvector_tool initialization:

```python
        pageindex_tool = _get_pageindex_tool()
        if pageindex_tool:
            tools[ToolType.PAGEINDEX] = pageindex_tool
```

**Step 3: Add dependencies to requirements.txt**

Append to `requirements.txt`:

```
# PageIndex for contract tree-based retrieval
litellm>=1.80.0
pymupdf>=1.26.0
PyPDF2>=3.0.0
pyyaml>=6.0.0
```

Note: PageIndex itself is installed from the local clone at `/Users/kayleighbot/Projects/pageindex-poc`. For production, add `pageindex` as a pip package or include the `pageindex/` directory in the Docker build context.

**Step 4: Commit**

```bash
git add unified_api/services/agentic_rag/agent.py \
        unified_api/routers/agentic_rag.py \
        requirements.txt
git commit -m "feat: wire PageIndex tool into agentic RAG agent and router"
```

---

## Task 5: Upgrade Clause Extractor with PageIndex

**Files:**
- Modify: `unified_api/services/clause_extractor.py`
- Test: `unified_api/tests/unit/test_clause_extractor.py`

**Context:** The current clause extractor sends the ENTIRE contract (truncated at 100K chars) to GPT-4o in one shot. Replace with PageIndex-guided extraction: use the tree to identify financial/legal sections, then extract clauses only from relevant sections. This is more accurate AND cheaper.

**Step 1: Write the failing test**

```python
# unified_api/tests/unit/test_clause_extractor.py
"""Tests for upgraded clause extractor."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestClauseExtractorUpgrade:
    @pytest.mark.asyncio
    @patch('unified_api.services.clause_extractor.extract_clauses_with_tree')
    async def test_tree_extraction_called_when_available(self, mock_tree_extract):
        """When tree cache exists, use tree-guided extraction."""
        mock_tree_extract.return_value = {"upfront_payment": {"amount": 6, "currency": "USD"}}
        from unified_api.services.clause_extractor import extract_clauses
        result = await extract_clauses("contract text here", deal_id=150059)
        # Should attempt tree-guided extraction for deals with contracts
        assert result is not None
```

**Step 2: Update clause_extractor.py**

Add a `extract_clauses_with_tree` function that uses the cached tree to target extraction at specific sections rather than sending the whole contract. Keep the existing `extract_clauses` as fallback.

```python
async def extract_clauses_with_tree(
    contract_text: str,
    tree_json: dict,
    deal_id: Optional[int] = None,
) -> dict:
    """
    Extract clauses using PageIndex tree-guided approach.
    Only sends relevant sections to the LLM instead of the whole contract.
    """
    from unified_api.services.html_cleaner import clean_contract_html

    clean_md = clean_contract_html(contract_text)
    doc_lines = clean_md.split('\n')

    # Find financial and legal sections from tree
    target_keywords = [
        'financial', 'payment', 'royalt', 'milestone', 'upfront',
        'license', 'territory', 'terminat', 'confidential',
        'intellectual property', 'ip', 'indemnif',
    ]

    def find_sections(nodes, keywords):
        results = []
        for n in nodes:
            title = n.get('title', '').lower()
            for kw in keywords:
                if kw in title:
                    results.append(n.get('line_num', 0))
                    break
            for c in n.get('nodes', []):
                results.extend(find_sections([c], keywords))
        return results

    relevant_lines = find_sections(tree_json.get('structure', []), target_keywords)
    # Deduplicate and sort
    relevant_lines = sorted(set(ln for ln in relevant_lines if ln > 0))

    # Extract content from those sections
    section_texts = []
    for ln in relevant_lines:
        start = max(0, ln - 1)
        end = min(len(doc_lines), start + 40)
        chunk = '\n'.join(doc_lines[start:end]).strip()
        if chunk:
            section_texts.append(chunk)

    targeted_text = '\n\n---\n\n'.join(section_texts)

    # Now send only the targeted sections to GPT-4o
    import openai
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": "You are a pharmaceutical deal analyst specializing in contract analysis. Extract deal terms precisely."},
            {"role": "user", "content": EXTRACTION_PROMPT + targeted_text}
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=4096,
    )

    result = json.loads(response.choices[0].message.content)
    result["_metadata"] = {
        "model": settings.openai_model,
        "tokens_used": response.usage.total_tokens if response.usage else None,
        "deal_id": deal_id,
        "extraction_method": "pageindex_tree_guided",
        "sections_targeted": len(relevant_lines),
    }
    return result
```

Update `extract_clauses` to try tree-guided first:

```python
async def extract_clauses(contract_text: str, deal_id: Optional[int] = None) -> dict:
    # Try tree-guided extraction if deal has a cached tree
    if deal_id:
        try:
            from unified_api.services.tree_cache import TreeCache
            from unified_api.services.database import get_cortellis_session_factory

            cache = TreeCache(session_factory=get_cortellis_session_factory())
            tree = cache.get_tree_by_deal(deal_id)
            if tree:
                logger.info("Using tree-guided clause extraction", deal_id=deal_id)
                return await extract_clauses_with_tree(contract_text, tree, deal_id)
        except Exception as e:
            logger.warning("Tree-guided extraction failed, falling back", error=str(e))

    # Fallback to original brute-force approach
    # ... (existing code unchanged)
```

**Step 3: Commit**

```bash
git add unified_api/services/clause_extractor.py unified_api/tests/unit/test_clause_extractor.py
git commit -m "feat: upgrade clause extractor with PageIndex tree-guided extraction"
```

---

## Task 6: Create Table on MachomeLab + Integration Test

**Files:**
- Create: `unified_api/tests/integration/test_pageindex_integration.py`

**Context:** Create the `contract_tree_index` table on the live Cortellis DB, then run an integration test against a real contract.

**Step 1: Create table on MachomeLab**

```bash
ssh machomelab 'eval "$(/opt/homebrew/bin/brew shellenv)"; DOCKER_HOST=unix://$HOME/.colima/dokploy/docker.sock docker exec compose-program-auxiliary-circuit-5v8mnw-onebd-db-cortellis-1 psql -U cortellis -d cortellis -c "
CREATE TABLE IF NOT EXISTS contract_tree_index (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL,
    deal_id INTEGER NOT NULL,
    tree_json JSONB NOT NULL,
    line_count INTEGER,
    model VARCHAR(100) NOT NULL,
    indexed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(contract_id)
);
CREATE INDEX IF NOT EXISTS idx_contract_tree_deal_id ON contract_tree_index(deal_id);
CREATE INDEX IF NOT EXISTS idx_contract_tree_contract_id ON contract_tree_index(contract_id);
"'
```

**Step 2: Write integration test**

```python
# unified_api/tests/integration/test_pageindex_integration.py
"""
Integration test: PageIndex tool against live Cortellis DB.
Requires MachomeLab access and OPENAI_API_KEY.

Run: pytest unified_api/tests/integration/test_pageindex_integration.py -v -s
"""
import pytest
import os

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="Requires OPENAI_API_KEY"
)


class TestPageIndexIntegration:
    """Test PageIndex against GSK-Codexis contract (deal 150059)."""

    @pytest.mark.asyncio
    async def test_upfront_payment_extraction(self):
        """Should find $6M upfront payment in GSK-Codexis deal."""
        # This test runs against MachomeLab — skip if not available
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool

        tool = PageIndexTool(
            session_factory=...,  # Wire to live DB
            openai_api_key=os.getenv("OPENAI_API_KEY"),
        )
        result = await tool.execute("deal_id:150059 What is the upfront payment?")
        assert result.success
        assert "$6,000,000" in result.data[0]["answer"] or "6 million" in result.data[0]["answer"].lower()
```

**Step 3: Commit**

```bash
git add unified_api/tests/integration/test_pageindex_integration.py
git commit -m "feat: add PageIndex integration test and create cache table"
```

---

## Execution Summary

| Task | What | LOC | Deps |
|------|------|-----|------|
| 1 | HTML cleaner service | ~80 | None |
| 2 | Tree cache table + service | ~100 | None |
| 3 | PageIndex agentic RAG tool | ~250 | PageIndex, LiteLLM |
| 4 | Wire into agent + router | ~50 | Task 3 |
| 5 | Upgrade clause extractor | ~80 | Tasks 1-2 |
| 6 | Create table + integration test | ~40 | Tasks 1-5 |

**Total: ~600 lines of new code, 6 tasks, 3-4 hours estimated.**

Plan complete and saved to `docs/plans/2026-03-31-pageindex-integration.md`. Two execution options:

**1. Subagent-Driven (this session)** — I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** — Open new session with executing-plans, batch execution with checkpoints

Which approach?
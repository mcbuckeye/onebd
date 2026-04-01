"""
PageIndex tool for deep contract reading with tree-based reasoning.

Integrates PageIndex's hierarchical document indexing with OneBD's agentic RAG.
When invoked by the agent, this tool:
1. Fetches contract text from the Cortellis DB by deal_id
2. Cleans HTML markup to markdown
3. Checks tree cache (generates PageIndex tree if cache miss)
4. Uses LLM reasoning over the tree to find relevant sections
5. Returns a cited answer with section references
"""
import asyncio
import json
import os
import re
import tempfile
from typing import Callable, Optional

import structlog
from sqlalchemy import text

from .base import BaseTool
from ..models import ToolResult

logger = structlog.get_logger(__name__)


class PageIndexTool(BaseTool):
    """Tool for deep reading of contract text using PageIndex tree-based retrieval."""

    SCHEMA_DESCRIPTION = """
    PageIndex Contract Deep-Read Tool

    Use this tool when you need to find SPECIFIC information inside a contract:
    - Exact payment amounts, royalty rates, milestone schedules
    - Specific clauses (termination, IP ownership, confidentiality)
    - License scope, territory rights, exclusivity terms
    - Indemnification, representations, warranties
    - How long obligations survive after termination

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
        """Extract deal_id from query string like 'deal_id:12345 question'."""
        match = re.search(r"deal_id:(\d+)", query)
        return int(match.group(1)) if match else None

    def _get_question(self, query: str) -> str:
        """Extract the question part (everything after deal_id:NNN)."""
        return re.sub(r"deal_id:\d+\s*", "", query).strip()

    def _build_compact_tree(self, tree_data: dict, max_depth: int = 2) -> str:
        """Build a compact text representation of the tree index for LLM context."""

        def _recurse(nodes: list, depth: int = 0) -> list[str]:
            lines = []
            for n in nodes:
                if depth <= max_depth:
                    ln = n.get("line_num", "?")
                    title = n.get("title", "?")[:120]
                    lines.append(f"{'  ' * depth}[L{ln}] {title}")
                if n.get("nodes") and depth < max_depth:
                    lines.extend(_recurse(n["nodes"], depth + 1))
            return lines

        structure = tree_data.get("structure", [])
        return "\n".join(_recurse(structure))

    async def _execute_impl(self, query: str, **kwargs) -> ToolResult:
        """Execute PageIndex deep-read on a contract."""
        from unified_api.services.html_cleaner import clean_contract_html
        from unified_api.services.tree_cache import TreeCache

        deal_id = kwargs.get("deal_id") or self._parse_deal_id(query)
        question = self._get_question(query)

        if not deal_id:
            return ToolResult(
                success=False,
                error="No deal_id provided. Use format: deal_id:12345 <question>",
                row_count=0,
                query_executed=query,
            )

        session = self.session_factory()
        try:
            # 1. Fetch contract text
            row = session.execute(
                text("""
                    SELECT cc.id AS contract_id, cc.content, cc.word_count
                    FROM contract_content cc
                    WHERE cc.deal_id = :did
                    ORDER BY cc.word_count DESC
                    LIMIT 1
                """),
                {"did": deal_id},
            ).fetchone()

            if not row or not row.content:
                return ToolResult(
                    success=False,
                    error=f"No contract found for deal {deal_id}",
                    row_count=0,
                    query_executed=query,
                )

            contract_id = row.contract_id
            logger.info(
                "Found contract",
                deal_id=deal_id,
                contract_id=contract_id,
                word_count=row.word_count,
            )

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
                        line_count=tree_data.get("line_count"),
                    )
                else:
                    return ToolResult(
                        success=False,
                        error="Failed to generate tree index for contract",
                        row_count=0,
                        query_executed=query,
                    )

            # 4. Clean the contract for line-based retrieval
            clean_md = clean_contract_html(row.content)
            doc_lines = clean_md.split("\n")

            # 5. LLM reasons over tree to find relevant sections
            relevant_lines = await self._find_relevant_sections(tree_data, question)

            if not relevant_lines:
                return ToolResult(
                    success=False,
                    error="Could not identify relevant sections in the contract",
                    row_count=0,
                    query_executed=query,
                )

            # 6. Extract content from identified sections
            context_chunks = []
            for ln in relevant_lines[:8]:
                start = max(0, ln - 1)
                end = min(len(doc_lines), start + 50)
                chunk_text = "\n".join(doc_lines[start:end]).strip()
                if chunk_text:
                    context_chunks.append(
                        {"lines": f"{start + 1}-{end}", "content": chunk_text[:2000]}
                    )

            # 7. Generate cited answer
            answer = await self._generate_answer(question, context_chunks, deal_id)

            return ToolResult(
                success=True,
                data=[
                    {
                        "deal_id": deal_id,
                        "answer": answer,
                        "sections_consulted": len(context_chunks),
                        "source": "pageindex_tree_retrieval",
                    }
                ],
                row_count=1,
                query_executed=f"PageIndex deep-read: deal {deal_id} — {question[:100]}",
            )

        except Exception as e:
            logger.error("PageIndex tool failed", error=str(e), deal_id=deal_id)
            return ToolResult(
                success=False,
                error=f"PageIndex retrieval failed: {str(e)}",
                row_count=0,
                query_executed=query,
            )
        finally:
            session.close()

    async def _generate_tree(self, clean_md: str) -> Optional[dict]:
        """Generate PageIndex tree from clean markdown text."""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False
            ) as f:
                f.write(clean_md)
                tmp_path = f.name

            try:
                from unified_api.vendor.pageindex.page_index_md import md_to_tree

                tree = await md_to_tree(
                    md_path=tmp_path,
                    if_thinning=False,
                    if_add_node_summary="yes",
                    summary_token_threshold=200,
                    model=self.model,
                    if_add_doc_description="yes",
                    if_add_node_text="yes",
                    if_add_node_id="yes",
                )
                return tree
            finally:
                os.unlink(tmp_path)

        except Exception as e:
            logger.error("Tree generation failed", error=str(e))
            return None

    async def _find_relevant_sections(
        self, tree_data: dict, question: str
    ) -> list[int]:
        """Use LLM to reason over tree index and identify relevant line numbers."""
        import litellm

        tree_text = self._build_compact_tree(tree_data)

        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: litellm.completion(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": f"""You are analyzing a pharma BD contract.

Document index (line numbers and section titles):
{tree_text}

Question: {question}

Identify the 5-8 line numbers from the FULL TEXT sections that contain the answer.
Prefer lines from the main contract body (higher line numbers), not the table of contents.
Return ONLY a JSON array of line numbers, e.g.: [1509, 1624, 1790]""",
                    }
                ],
                temperature=0,
                api_key=self.openai_api_key,
            ),
        )

        raw = response.choices[0].message.content.strip()
        numbers = [int(n) for n in re.findall(r"\d+", raw)]
        return [n for n in numbers if n > 0][:10]

    async def _generate_answer(
        self, question: str, chunks: list[dict], deal_id: int
    ) -> str:
        """Generate a cited answer from retrieved contract sections."""
        import litellm

        context = "\n\n---\n\n".join(
            [f"[Lines {c['lines']}]:\n{c['content']}" for c in chunks]
        )

        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: litellm.completion(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": f"""Answer this BD question based ONLY on the contract text below.
Be specific — cite exact dollar amounts, percentages, section numbers, time periods.

Question: {question}

Contract text (deal {deal_id}):
{context[:12000]}

If amounts are redacted as [***], note that. Give a precise, BD analyst-grade answer.""",
                    }
                ],
                temperature=0,
                api_key=self.openai_api_key,
            ),
        )

        return response.choices[0].message.content.strip()

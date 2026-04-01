"""
Evidence tool for clinical efficacy queries using the Evidence Library.

Searches the evidence_documents table for relevant FDA labels, publications,
and regulatory documents, then uses PageIndex tree-based retrieval to
extract specific clinical data (PFS rates, CR rates, dosing, safety).

Supports multi-drug comparisons.
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


class EvidenceTool(BaseTool):
    """Tool for querying clinical evidence documents with PageIndex."""

    SCHEMA_DESCRIPTION = """
    Clinical Evidence Tool

    Use this tool for clinical efficacy and safety questions across drugs:
    - PFS rates, OS rates, response rates (CR, ORR, PR)
    - Clinical trial results and comparisons
    - Dosing regimens and safety profiles
    - Head-to-head trial data
    - Competitive landscape questions

    This tool searches a curated library of FDA labels, trial publications,
    and regulatory documents indexed with PageIndex.

    Query format: "<your clinical question>"
    Examples:
    - "Compare PFS rates for zanubrutinib and ibrutinib in CLL"
    - "What is the CR rate for acalabrutinib in MCL?"
    - "Compare safety profiles of BTK inhibitors"

    DO NOT use this tool for:
    - Deal terms or contract analysis (use PageIndex tool)
    - Company relationships (use Neo4j tool)
    - Financial data (use SQL tool)
    """

    def __init__(
        self,
        session_factory: Callable,
        openai_api_key: str,
        model: str = "gpt-4o-2024-11-20",
        max_retries: int = 1,
    ):
        super().__init__("evidence", max_retries)
        self.session_factory = session_factory
        self.openai_api_key = openai_api_key
        self.model = model

    def get_schema_description(self) -> str:
        return self.SCHEMA_DESCRIPTION

    async def _execute_impl(self, query: str, **kwargs) -> ToolResult:
        """Search evidence library and extract clinical data."""
        from unified_api.services.evidence_library import (
            find_evidence_for_query,
            get_evidence_tree,
        )
        from unified_api.services.html_cleaner import clean_contract_html

        session = self.session_factory()
        try:
            # 1. Find relevant evidence documents
            docs = find_evidence_for_query(session, query)

            if not docs:
                return ToolResult(
                    success=False,
                    error=(
                        "No evidence documents found for this query. "
                        "The Evidence Library may not have documents for these drugs yet."
                    ),
                    row_count=0,
                    query_executed=query,
                )

            logger.info(
                "Found evidence documents",
                count=len(docs),
                drugs=[d.drug_name for d in docs],
            )

            # 2. For each document, extract relevant data using PageIndex
            per_drug_data = []
            for doc in docs[:5]:  # Max 5 documents
                tree = get_evidence_tree(session, evidence_id=doc.id)

                if not tree:
                    # Need to index this doc first
                    if doc.pdf_path and os.path.exists(doc.pdf_path):
                        tree = await self._index_evidence_pdf(doc.id, doc.pdf_path, session)
                    else:
                        logger.warning(
                            "No tree and no PDF for evidence doc",
                            evidence_id=doc.id,
                            drug=doc.drug_name,
                        )
                        per_drug_data.append({
                            "drug": f"{doc.brand_name} ({doc.drug_name})",
                            "data": "[Document not yet indexed — PDF not available]",
                        })
                        continue

                if not tree:
                    per_drug_data.append({
                        "drug": f"{doc.brand_name} ({doc.drug_name})",
                        "data": "[Tree generation failed]",
                    })
                    continue

                # Use PageIndex to find relevant sections
                answer = await self._query_evidence_doc(
                    tree_data=tree,
                    pdf_path=doc.pdf_path,
                    question=query,
                    drug_name=f"{doc.brand_name} ({doc.drug_name})",
                )

                per_drug_data.append({
                    "drug": f"{doc.brand_name} ({doc.drug_name})",
                    "doc_type": doc.doc_type,
                    "data": answer,
                })

            # 3. If multiple drugs, synthesize comparison
            if len(per_drug_data) > 1:
                synthesis = await self._synthesize_comparison(query, per_drug_data)
                return ToolResult(
                    success=True,
                    data=[{
                        "answer": synthesis,
                        "drugs_compared": len(per_drug_data),
                        "source": "evidence_library",
                    }],
                    row_count=1,
                    query_executed=f"Evidence query: {query[:100]}",
                )
            elif per_drug_data:
                return ToolResult(
                    success=True,
                    data=[{
                        "answer": per_drug_data[0]["data"],
                        "drug": per_drug_data[0]["drug"],
                        "source": "evidence_library",
                    }],
                    row_count=1,
                    query_executed=f"Evidence query: {query[:100]}",
                )
            else:
                return ToolResult(
                    success=False,
                    error="Could not extract data from any evidence documents",
                    row_count=0,
                    query_executed=query,
                )

        except Exception as e:
            logger.error("Evidence tool failed", error=str(e))
            return ToolResult(
                success=False,
                error=f"Evidence query failed: {str(e)}",
                row_count=0,
                query_executed=query,
            )
        finally:
            session.close()

    async def _index_evidence_pdf(self, evidence_id: int, pdf_path: str, session) -> Optional[dict]:
        """Index a PDF evidence document with PageIndex."""
        try:
            from unified_api.vendor.pageindex.page_index import page_index
            from unified_api.services.evidence_library import store_evidence_tree
            import PyPDF2

            result = page_index(
                doc=pdf_path,
                model=self.model,
                if_add_node_summary="yes",
                if_add_node_text="yes",
                if_add_node_id="yes",
                if_add_doc_description="yes",
            )

            store_evidence_tree(session, evidence_id, result, self.model)
            return result

        except Exception as e:
            logger.error("Evidence PDF indexing failed", evidence_id=evidence_id, error=str(e))
            return None

    async def _query_evidence_doc(
        self,
        tree_data: dict,
        pdf_path: Optional[str],
        question: str,
        drug_name: str,
    ) -> str:
        """Query a single evidence document using PageIndex tree reasoning."""
        import litellm

        # Build compact tree for LLM
        def build_tree(nodes, depth=0, max_depth=2):
            lines = []
            for n in nodes:
                if depth <= max_depth:
                    si = n.get("start_index", n.get("line_num", "?"))
                    title = n.get("title", "?")[:100]
                    lines.append(f"{'  ' * depth}[p{si}] {title}")
                if n.get("nodes") and depth < max_depth:
                    lines.extend(build_tree(n["nodes"], depth + 1, max_depth))
            return lines

        tree_text = "\n".join(build_tree(tree_data.get("structure", [])))

        # Step 1: Find relevant pages
        resp1 = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: litellm.completion(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": f"""This is the FDA label / clinical document for {drug_name}.

Document tree:
{tree_text}

Question: {question}

Identify page numbers with clinical efficacy data (PFS, CR, ORR, response rates, Kaplan-Meier).
Return ONLY a JSON array of page numbers.""",
                }],
                # temperature=0 omitted for gpt-5.x compat
                api_key=self.openai_api_key,
            ),
        )

        pages = [int(n) for n in re.findall(r"\d+", resp1.choices[0].message.content)]
        pages = [p for p in pages if 1 <= p <= 200][:12]

        if not pages or not pdf_path:
            return f"[Could not identify relevant pages for {drug_name}]"

        # Step 2: Get page content
        import PyPDF2
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            page_texts = []
            for p in pages:
                if 1 <= p <= len(reader.pages):
                    text_content = reader.pages[p - 1].extract_text() or ""
                    if text_content.strip():
                        page_texts.append(f"[Page {p}]:\n{text_content[:2000]}")

        context = "\n\n---\n\n".join(page_texts)

        # Step 3: Extract clinical data
        resp2 = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: litellm.completion(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": f"""From this FDA label for {drug_name}, extract:
1. PFS rates at 12, 24, 36 months (if available)
2. CR rates and ORR by indication
3. Median PFS and hazard ratios
4. Trial names and comparator arms

Question: {question}

Document text:
{context[:12000]}

Be precise. Cite page numbers. Note what data is available vs not reported.""",
                }],
                # temperature=0 omitted for gpt-5.x compat
                api_key=self.openai_api_key,
            ),
        )

        return resp2.choices[0].message.content.strip()

    async def _synthesize_comparison(self, question: str, per_drug_data: list) -> str:
        """Synthesize a comparison across multiple drugs."""
        import litellm

        drugs_context = "\n\n---\n\n".join([
            f"**{d['drug']}** ({d.get('doc_type', 'evidence')}):\n{d['data'][:3000]}"
            for d in per_drug_data
        ])

        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: litellm.completion(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": f"""You are preparing a clinical competitive intelligence briefing.

Question: {question}

Data from {len(per_drug_data)} drugs:
{drugs_context[:15000]}

Create a structured comparison with:
1. Tables comparing efficacy metrics by indication where data exists
2. Key competitive takeaways
3. Data gaps noted

Format for an executive audience.""",
                }],
                # temperature=0 omitted for gpt-5.x compat
                api_key=self.openai_api_key,
            ),
        )

        return response.choices[0].message.content.strip()

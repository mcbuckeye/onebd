"""
PDF indexing service for PageIndex.

Indexes original SEC/EDGAR PDF filings directly, providing
page-number citations instead of line numbers.
"""
import asyncio
from typing import Optional

import structlog
from sqlalchemy import text

logger = structlog.get_logger(__name__)


async def generate_pdf_tree(
    pdf_path: str,
    model: str = "gpt-4o-2024-11-20",
) -> Optional[dict]:
    """
    Generate a PageIndex tree from a PDF file.

    Uses PageIndex's PDF mode which extracts page structure and
    provides page-number-based citations (superior to line numbers).

    Args:
        pdf_path: Path to the PDF file
        model: LLM model for tree generation

    Returns:
        Tree structure dict, or None on failure.
    """
    try:
        from unified_api.vendor.pageindex.page_index import page_index

        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: page_index(
                doc=pdf_path,
                model=model,
                if_add_node_summary="yes",
                if_add_node_text="yes",
                if_add_node_id="yes",
                if_add_doc_description="yes",
            ),
        )
        return result

    except Exception as e:
        logger.error("PDF tree generation failed", pdf_path=pdf_path, error=str(e))
        return None


def has_pdf_for_contract(session, contract_id: int) -> dict:
    """
    Check if a PDF file exists for a contract.

    Looks up deal_contracts table for pdf_file_path.

    Returns:
        Dict with has_pdf bool and pdf_file_path (or None).
    """
    row = session.execute(
        text("""
            SELECT dc.pdf_file_path, dc.has_pdf
            FROM deal_contracts dc
            JOIN contract_content cc ON cc.contract_id = dc.id
            WHERE cc.id = :cid
        """),
        {"cid": contract_id},
    ).fetchone()

    if not row:
        return {"has_pdf": False, "pdf_file_path": None}

    return {
        "has_pdf": bool(row.has_pdf and row.pdf_file_path),
        "pdf_file_path": row.pdf_file_path,
    }

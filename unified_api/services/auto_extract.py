"""
Auto-extract structured clause data from contracts.

When a PageIndex tree is generated (batch or on-demand), this service
extracts structured deal terms and stores them in a JSONB column
on contract_content, making them SQL-queryable.

Extracted fields: upfront, royalties, milestones, termination, license scope, territories.
"""
import json
from typing import Callable, Optional

import structlog
from sqlalchemy import text

logger = structlog.get_logger(__name__)


async def auto_extract_clauses(
    contract_id: int,
    deal_id: int,
    tree_json: dict,
    session_factory: Callable,
) -> dict:
    """
    Extract structured clauses from a contract using its cached PageIndex tree.

    Called after tree generation (batch or on-demand). Extracts deal terms
    and stores them in contract_content.extracted_clauses JSONB column.

    Args:
        contract_id: The contract_content.id
        deal_id: The deal.id
        tree_json: The cached PageIndex tree structure
        session_factory: Callable returning a SQLAlchemy session

    Returns:
        Dict with success status and extracted data summary.
    """
    from unified_api.services.clause_extractor import extract_clauses_with_tree

    session = session_factory()
    try:
        # Fetch contract text
        row = session.execute(
            text("SELECT content FROM contract_content WHERE id = :cid"),
            {"cid": contract_id},
        ).fetchone()

        if not row or not row.content:
            return {
                "success": False,
                "contract_id": contract_id,
                "error": f"Contract {contract_id} not found or empty",
            }

        # Extract clauses using tree-guided approach
        try:
            clauses = await extract_clauses_with_tree(
                contract_text=row.content,
                tree_json=tree_json,
                deal_id=deal_id,
            )
        except Exception as e:
            logger.error(
                "Clause extraction failed",
                contract_id=contract_id,
                error=str(e),
            )
            return {
                "success": False,
                "contract_id": contract_id,
                "error": str(e),
            }

        # Store extracted clauses in JSONB column
        session.execute(
            text("""
                UPDATE contract_content
                SET extracted_clauses = CAST(:clauses AS jsonb)
                WHERE id = :cid
            """),
            {
                "cid": contract_id,
                "clauses": json.dumps(clauses),
            },
        )
        session.commit()

        logger.info(
            "Clauses auto-extracted",
            contract_id=contract_id,
            deal_id=deal_id,
            has_upfront=clauses.get("upfront_payment") is not None,
            has_royalties=clauses.get("royalty_rates") is not None,
        )

        return {
            "success": True,
            "contract_id": contract_id,
            "deal_id": deal_id,
            "fields_extracted": [
                k for k, v in clauses.items()
                if v is not None and k != "_metadata"
            ],
        }

    except Exception as e:
        logger.error(
            "Auto-extraction failed",
            contract_id=contract_id,
            error=str(e),
        )
        session.rollback()
        return {
            "success": False,
            "contract_id": contract_id,
            "error": str(e),
        }
    finally:
        session.close()


def get_extracted_clauses(session, contract_id: int) -> Optional[dict]:
    """
    Get previously extracted clauses for a contract.

    Returns the JSONB data from contract_content.extracted_clauses,
    or None if not yet extracted.
    """
    row = session.execute(
        text("SELECT extracted_clauses FROM contract_content WHERE id = :cid"),
        {"cid": contract_id},
    ).fetchone()

    if not row:
        return None

    return row.extracted_clauses

"""
Batch pre-indexing service for PageIndex contract trees.

Generates PageIndex tree indexes for the largest contracts in the database,
caching them so user queries are instant (2-5s instead of 19s+ for first query).

Usage:
  - As Celery task: batch_index_contracts.delay(limit=500, min_words=10000)
  - As management command: python -m unified_api.services.batch_index --limit 500
"""
import asyncio
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import structlog
from sqlalchemy import text

logger = structlog.get_logger(__name__)


@dataclass
class BatchIndexStats:
    """Track progress of batch indexing."""

    _successes: list = field(default_factory=list)
    _failures: list = field(default_factory=list)

    @property
    def total_attempted(self) -> int:
        return len(self._successes) + len(self._failures)

    @property
    def succeeded(self) -> int:
        return len(self._successes)

    @property
    def failed(self) -> int:
        return len(self._failures)

    @property
    def avg_time(self) -> float:
        if not self._successes:
            return 0.0
        return sum(t for _, t in self._successes) / len(self._successes)

    def record_success(self, contract_id: int, elapsed: float) -> None:
        self._successes.append((contract_id, elapsed))

    def record_failure(self, contract_id: int, error: str) -> None:
        self._failures.append((contract_id, error))

    def to_dict(self) -> dict:
        return {
            "total_attempted": self.total_attempted,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "avg_time_seconds": round(self.avg_time, 1),
            "failed_contracts": [
                {"contract_id": cid, "error": err[:200]}
                for cid, err in self._failures
            ],
        }


def get_contracts_to_index(
    session, limit: int = 500, min_words: int = 10000
) -> list:
    """
    Get contracts that need indexing, ordered by word count descending.
    Skips contracts that already have cached trees.
    """
    rows = session.execute(
        text("""
            SELECT cc.id AS contract_id, cc.deal_id, cc.word_count
            FROM contract_content cc
            LEFT JOIN contract_tree_index cti ON cti.contract_id = cc.id
            WHERE cc.word_count >= :min_words
              AND cti.id IS NULL
            ORDER BY cc.word_count DESC
            LIMIT :limit
        """),
        {"min_words": min_words, "limit": limit},
    ).fetchall()
    return rows


async def generate_tree_from_markdown(clean_md: str, model: str = "gpt-4o-2024-11-20") -> Optional[dict]:
    """Generate a PageIndex tree from clean markdown text."""
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(clean_md)
            tmp_path = f.name

        try:
            from unified_api.vendor.pageindex.page_index_md import md_to_tree

            tree = await md_to_tree(
                md_path=tmp_path,
                if_thinning=False,
                if_add_node_summary="yes",
                summary_token_threshold=200,
                model=model,
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


async def index_single_contract(
    contract_id: int,
    deal_id: int,
    session_factory: Callable,
    model: str = "gpt-4o-2024-11-20",
) -> dict:
    """
    Index a single contract: fetch content, clean HTML, generate tree, cache.

    Returns dict with success status and metadata.
    """
    from unified_api.services.html_cleaner import clean_contract_html
    from unified_api.services.tree_cache import TreeCache

    session = session_factory()
    try:
        # Fetch contract content
        row = session.execute(
            text("SELECT content, word_count FROM contract_content WHERE id = :cid"),
            {"cid": contract_id},
        ).fetchone()

        if not row or not row.content:
            return {
                "success": False,
                "contract_id": contract_id,
                "error": f"Contract {contract_id} not found or empty",
            }

        # Clean HTML to markdown
        clean_md = clean_contract_html(row.content)

        # Generate tree
        tree_data = await generate_tree_from_markdown(clean_md, model=model)

        if not tree_data:
            return {
                "success": False,
                "contract_id": contract_id,
                "error": "Tree generation failed",
            }

        # Cache the tree
        cache = TreeCache(session_factory=session_factory)
        cache.store_tree(
            contract_id=contract_id,
            deal_id=deal_id,
            tree_json=tree_data,
            model=model,
            line_count=tree_data.get("line_count"),
        )

        # Auto-extract clauses from the tree
        try:
            from unified_api.services.auto_extract import auto_extract_clauses

            extract_result = await auto_extract_clauses(
                contract_id=contract_id,
                deal_id=deal_id,
                tree_json=tree_data,
                session_factory=session_factory,
            )
            clauses_extracted = extract_result.get("success", False)
        except Exception as e:
            logger.warning(
                "Auto-extraction failed (non-fatal)",
                contract_id=contract_id,
                error=str(e),
            )
            clauses_extracted = False

        return {
            "success": True,
            "contract_id": contract_id,
            "deal_id": deal_id,
            "line_count": tree_data.get("line_count"),
            "nodes": len(tree_data.get("structure", [])),
            "clauses_extracted": clauses_extracted,
        }

    except Exception as e:
        logger.error(
            "Failed to index contract",
            contract_id=contract_id,
            error=str(e),
        )
        return {
            "success": False,
            "contract_id": contract_id,
            "error": str(e),
        }
    finally:
        session.close()


async def run_batch_index(
    session_factory: Callable,
    limit: int = 500,
    min_words: int = 10000,
    model: str = "gpt-4o-2024-11-20",
) -> dict:
    """
    Main batch indexing function. Finds un-indexed contracts and generates trees.

    Args:
        session_factory: Callable that returns a SQLAlchemy session
        limit: Max contracts to index in this batch
        min_words: Minimum word count to consider for indexing
        model: LLM model for tree generation

    Returns:
        Dict with batch statistics
    """
    stats = BatchIndexStats()

    # Get contracts needing indexing
    session = session_factory()
    try:
        contracts = get_contracts_to_index(session, limit=limit, min_words=min_words)
    finally:
        session.close()

    total = len(contracts)
    logger.info(
        "Batch indexing started",
        total_contracts=total,
        limit=limit,
        min_words=min_words,
    )

    for i, contract in enumerate(contracts):
        start = time.time()
        logger.info(
            f"Indexing contract {i+1}/{total}",
            contract_id=contract.contract_id,
            deal_id=contract.deal_id,
            word_count=contract.word_count,
        )

        try:
            result = await index_single_contract(
                contract_id=contract.contract_id,
                deal_id=contract.deal_id,
                session_factory=session_factory,
                model=model,
            )

            elapsed = time.time() - start

            if result["success"]:
                stats.record_success(contract.contract_id, elapsed)
                logger.info(
                    f"Indexed {i+1}/{total}",
                    contract_id=contract.contract_id,
                    elapsed=f"{elapsed:.1f}s",
                )
            else:
                stats.record_failure(contract.contract_id, result.get("error", "unknown"))
                logger.warning(
                    f"Failed {i+1}/{total}",
                    contract_id=contract.contract_id,
                    error=result.get("error", "unknown"),
                )

        except Exception as e:
            elapsed = time.time() - start
            stats.record_failure(contract.contract_id, str(e))
            logger.error(
                f"Exception indexing {i+1}/{total}",
                contract_id=contract.contract_id,
                error=str(e),
            )

    result = stats.to_dict()
    logger.info("Batch indexing complete", **result)
    return result


# CLI entry point for running manually
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Batch pre-index contracts with PageIndex")
    parser.add_argument("--limit", type=int, default=500, help="Max contracts to index")
    parser.add_argument("--min-words", type=int, default=10000, help="Min word count")
    parser.add_argument("--model", type=str, default="gpt-4o-2024-11-20", help="LLM model")
    args = parser.parse_args()

    from unified_api.services.database import get_cortellis_session_factory

    factory = get_cortellis_session_factory()
    result = asyncio.run(
        run_batch_index(
            session_factory=factory,
            limit=args.limit,
            min_words=args.min_words,
            model=args.model,
        )
    )
    print(f"\nResults: {result}")

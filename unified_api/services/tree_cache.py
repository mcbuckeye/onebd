"""
Contract Tree Index Cache Service

Provides a cache layer for PageIndex tree structures. Generating a tree
costs ~$0.50 and takes 30-150 seconds per contract, so we store results
in PostgreSQL and reuse them.

Table: contract_tree_index (created via scripts/init_db.sql)
"""
import json
from typing import Callable, Optional

from sqlalchemy import text
import structlog

logger = structlog.get_logger(__name__)


class TreeCache:
    """Cache service for contract tree index structures.

    Stores and retrieves PageIndex hierarchical tree structures keyed
    by contract_id. Uses a session factory pattern for database access,
    with raw SQLAlchemy text() queries against the contract_tree_index table.

    Args:
        session_factory: Callable that returns a new SQLAlchemy session.
    """

    def __init__(self, session_factory: Callable) -> None:
        """Initialize the cache with a session factory.

        Args:
            session_factory: Callable that returns a SQLAlchemy session.
        """
        self.session_factory = session_factory

    def get_tree(self, contract_id: int) -> Optional[dict]:
        """Retrieve a cached tree by contract_id.

        Args:
            contract_id: The integer ID of the contract.

        Returns:
            The cached tree as a dict, or None if not cached.
        """
        session = self.session_factory()
        try:
            result = session.execute(
                text(
                    "SELECT tree_json FROM contract_tree_index "
                    "WHERE contract_id = :contract_id"
                ),
                {"contract_id": contract_id},
            )
            row = result.fetchone()
            if row is None:
                logger.debug("Tree cache miss", contract_id=contract_id)
                return None
            tree = row._mapping["tree_json"]
            logger.debug("Tree cache hit", contract_id=contract_id)
            return tree
        finally:
            session.close()

    def get_tree_by_deal(self, deal_id: int) -> Optional[dict]:
        """Retrieve the most recent cached tree for a deal.

        Args:
            deal_id: The integer ID of the deal.

        Returns:
            The most recently indexed tree as a dict, or None if not cached.
        """
        session = self.session_factory()
        try:
            result = session.execute(
                text(
                    "SELECT tree_json FROM contract_tree_index "
                    "WHERE deal_id = :deal_id "
                    "ORDER BY indexed_at DESC "
                    "LIMIT 1"
                ),
                {"deal_id": deal_id},
            )
            row = result.fetchone()
            if row is None:
                logger.debug("Tree cache miss by deal", deal_id=deal_id)
                return None
            tree = row._mapping["tree_json"]
            logger.debug("Tree cache hit by deal", deal_id=deal_id)
            return tree
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
        """Store or update a tree in the cache (upsert).

        Uses ON CONFLICT (contract_id) DO UPDATE to replace an existing
        cached tree when a contract is re-indexed.

        Args:
            contract_id: The integer ID of the contract.
            deal_id: The integer ID of the associated deal.
            tree_json: The hierarchical tree structure to cache.
            model: The model name used to generate the tree (e.g. "gpt-4o").
            line_count: Optional number of lines in the source contract text.
        """
        session = self.session_factory()
        try:
            session.execute(
                text(
                    "INSERT INTO contract_tree_index "
                    "(contract_id, deal_id, tree_json, model, line_count, indexed_at) "
                    "VALUES (:contract_id, :deal_id, CAST(:tree_json AS jsonb), :model, :line_count, NOW()) "
                    "ON CONFLICT (contract_id) DO UPDATE SET "
                    "deal_id = EXCLUDED.deal_id, "
                    "tree_json = EXCLUDED.tree_json, "
                    "model = EXCLUDED.model, "
                    "line_count = EXCLUDED.line_count, "
                    "indexed_at = EXCLUDED.indexed_at"
                ),
                {
                    "contract_id": contract_id,
                    "deal_id": deal_id,
                    "tree_json": json.dumps(tree_json),
                    "model": model,
                    "line_count": line_count,
                },
            )
            session.commit()
            logger.info(
                "Tree cached",
                contract_id=contract_id,
                deal_id=deal_id,
                model=model,
                line_count=line_count,
            )
        except Exception:
            session.rollback()
            logger.exception("Failed to store tree", contract_id=contract_id)
            raise
        finally:
            session.close()

    def has_tree(self, contract_id: int) -> bool:
        """Check whether a tree is cached for the given contract.

        Args:
            contract_id: The integer ID of the contract.

        Returns:
            True if a cached tree exists, False otherwise.
        """
        session = self.session_factory()
        try:
            result = session.execute(
                text(
                    "SELECT COUNT(1) FROM contract_tree_index "
                    "WHERE contract_id = :contract_id"
                ),
                {"contract_id": contract_id},
            )
            count = result.scalar()
            exists = bool(count and count > 0)
            logger.debug("Tree cache check", contract_id=contract_id, exists=exists)
            return exists
        finally:
            session.close()

"""Durable catalog-membership exceptions from exhaustive Cortellis audits."""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import text
from sqlalchemy.orm import Session


CATALOG_EXCLUSION_REASON = (
    "Local historical record omitted by a complete numeric-ID retrieval audit"
)


def ensure_catalog_exclusion_schema(session: Session) -> None:
    """Create the small retained-record exception table when needed."""
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS cortellis_catalog_exclusions (
            deal_id INTEGER PRIMARY KEY REFERENCES deals(id) ON DELETE CASCADE,
            reason TEXT NOT NULL,
            first_verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))


def reconcile_catalog_exclusions(
    session: Session,
    *,
    accessible_ids: Collection[int],
    local_only_ids: Collection[int],
) -> dict[str, int]:
    """Persist local-only IDs and retire exceptions that become accessible."""
    ensure_catalog_exclusion_schema(session)
    accessible = {int(deal_id) for deal_id in accessible_ids}
    local_only = {int(deal_id) for deal_id in local_only_ids}
    existing = {
        int(deal_id)
        for deal_id in session.execute(text(
            "SELECT deal_id FROM cortellis_catalog_exclusions"
        )).scalars()
    }
    reappeared = sorted(existing & accessible)
    if reappeared:
        session.execute(text("""
            DELETE FROM cortellis_catalog_exclusions
            WHERE deal_id = ANY(:deal_ids)
        """), {"deal_ids": reappeared})
    for deal_id in sorted(local_only):
        session.execute(text("""
            INSERT INTO cortellis_catalog_exclusions (
                deal_id, reason, first_verified_at, last_verified_at
            ) VALUES (
                :deal_id, :reason, NOW(), NOW()
            )
            ON CONFLICT (deal_id) DO UPDATE SET
                reason = EXCLUDED.reason,
                last_verified_at = NOW()
        """), {
            "deal_id": deal_id,
            "reason": CATALOG_EXCLUSION_REASON,
        })
    return {
        "catalog_exclusions": len(local_only),
        "catalog_exclusions_reactivated": len(reappeared),
    }

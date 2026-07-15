"""Durable results from exhaustive Cortellis catalog audits."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


CATALOG_EXCLUSION_REASON = (
    "Local historical record omitted by a complete numeric-ID retrieval audit"
)


def ensure_catalog_exclusion_schema(session: Session) -> None:
    """Create the small retained-record exception table when needed."""
    from unified_api.services.runtime_schema import runtime_schema_is_pre_migrated

    if runtime_schema_is_pre_migrated():
        return
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS cortellis_catalog_exclusions (
            deal_id INTEGER PRIMARY KEY REFERENCES deals(id) ON DELETE CASCADE,
            reason TEXT NOT NULL,
            first_verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))


def ensure_catalog_proof_schema(session: Session) -> None:
    """Create the singleton exhaustive-membership proof table."""
    from unified_api.services.runtime_schema import runtime_schema_is_pre_migrated

    if runtime_schema_is_pre_migrated():
        return
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS cortellis_catalog_proof (
            id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            retrievable_total INTEGER NOT NULL CHECK (retrievable_total > 0),
            numeric_id_min INTEGER NOT NULL,
            numeric_id_max INTEGER NOT NULL,
            advertised_total INTEGER,
            incremental_retrievable_additions INTEGER NOT NULL DEFAULT 0,
            incremental_verified_at TIMESTAMPTZ,
            verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    session.execute(text("""
        ALTER TABLE cortellis_catalog_proof
        ADD COLUMN IF NOT EXISTS incremental_retrievable_additions
            INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS incremental_verified_at TIMESTAMPTZ
    """))


def record_catalog_proof(
    session: Session,
    *,
    retrievable_total: int,
    numeric_id_min: int,
    numeric_id_max: int,
    advertised_total: int | None,
) -> None:
    """Persist a successful exhaustive numeric-ID membership proof."""
    session.execute(text("""
        INSERT INTO cortellis_catalog_proof (
            id, retrievable_total, numeric_id_min, numeric_id_max,
            advertised_total, verified_at
        ) VALUES (
            1, :retrievable_total, :numeric_id_min, :numeric_id_max,
            :advertised_total, NOW()
        )
        ON CONFLICT (id) DO UPDATE SET
            retrievable_total = EXCLUDED.retrievable_total,
            numeric_id_min = EXCLUDED.numeric_id_min,
            numeric_id_max = EXCLUDED.numeric_id_max,
            advertised_total = EXCLUDED.advertised_total,
            incremental_retrievable_additions = 0,
            incremental_verified_at = NULL,
            verified_at = NOW()
    """), {
        "retrievable_total": int(retrievable_total),
        "numeric_id_min": int(numeric_id_min),
        "numeric_id_max": int(numeric_id_max),
        "advertised_total": (
            int(advertised_total) if advertised_total is not None else None
        ),
    })


def advance_catalog_proof(
    session: Session,
    *,
    newly_retrieved: int,
) -> None:
    """Extend an exhaustive baseline with newly retrieved incremental IDs."""
    if newly_retrieved < 0:
        raise ValueError("newly_retrieved cannot be negative")
    session.execute(text("""
        UPDATE cortellis_catalog_proof
        SET incremental_retrievable_additions =
                incremental_retrievable_additions + :newly_retrieved,
            incremental_verified_at = NOW()
        WHERE id = 1
    """), {"newly_retrieved": int(newly_retrieved)})


def advance_catalog_proof_to_verified_total(
    session: Session,
    *,
    verified_retrievable_total: int,
) -> bool:
    """Reconcile a stale baseline after every eligible ID is reverified.

    The caller must establish complete per-ID API and raw-response coverage for
    ``verified_retrievable_total`` records.  The proof only moves forward and
    retains the original exhaustive baseline as provenance.
    """
    if verified_retrievable_total <= 0:
        raise ValueError("verified_retrievable_total must be positive")
    row = session.execute(text("""
        UPDATE cortellis_catalog_proof
        SET incremental_retrievable_additions =
                :verified_retrievable_total - retrievable_total,
            incremental_verified_at = NOW()
        WHERE id = 1
          AND :verified_retrievable_total >= retrievable_total
          AND :verified_retrievable_total >
              retrievable_total + incremental_retrievable_additions
        RETURNING incremental_retrievable_additions
    """), {
        "verified_retrievable_total": int(verified_retrievable_total),
    }).scalar_one_or_none()
    return row is not None


def read_catalog_proof(session: Session) -> dict[str, Any]:
    """Return the latest durable exhaustive proof, if one exists."""
    row = session.execute(text("""
        SELECT retrievable_total, numeric_id_min, numeric_id_max,
               advertised_total, incremental_retrievable_additions,
               retrievable_total + incremental_retrievable_additions
                   AS effective_retrievable_total,
               incremental_verified_at, verified_at
        FROM cortellis_catalog_proof
        WHERE id = 1
    """)).mappings().first()
    return dict(row) if row else {}


def assess_catalog_cardinality(
    *,
    advertised_total: int,
    local_total: int,
    exclusion_total: int,
    verified_retrievable_total: int | None,
) -> dict[str, Any]:
    """Compare local membership to the strongest available source proof.

    Cortellis search advertises fewer deals than the credential can retrieve,
    so a durable exhaustive proof takes precedence. The advertised count is
    retained as an observation and is only used as a conservative fallback
    before the first exhaustive audit completes.
    """
    eligible_local_total = max(0, int(local_total) - int(exclusion_total))
    if verified_retrievable_total is not None:
        expected_total = int(verified_retrievable_total)
        verification_method = "exhaustive_numeric_id"
    else:
        expected_total = int(advertised_total)
        verification_method = "advertised_search_fallback"
    return {
        "catalog_total": int(advertised_total),
        "local_total": int(local_total),
        "catalog_exclusions": int(exclusion_total),
        "eligible_local_total": eligible_local_total,
        "verified_retrievable_total": (
            int(verified_retrievable_total)
            if verified_retrievable_total is not None else None
        ),
        "catalog_verification_method": verification_method,
        "catalog_gap": expected_total - eligible_local_total,
        "catalog_cardinality_complete": eligible_local_total == expected_total,
    }


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

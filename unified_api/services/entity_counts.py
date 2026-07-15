"""Fast, exact entity counts for the governed Deals API."""

from __future__ import annotations

from datetime import timezone
from typing import Any

from sqlalchemy import text


COUNTS_MAX_AGE_SECONDS = 300


def ensure_entity_counts_schema(session) -> None:
    """Create the durable singleton cache used by REST and MCP counts."""
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS api_entity_counts (
            singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
            deals BIGINT NOT NULL,
            companies BIGINT NOT NULL,
            assets BIGINT NOT NULL,
            deal_linked_assets BIGINT NOT NULL,
            refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))


def _cached_counts(session, max_age_seconds: int) -> dict[str, Any] | None:
    row = session.execute(
        text("""
            SELECT deals, companies, assets, deal_linked_assets, refreshed_at
            FROM api_entity_counts
            WHERE singleton=TRUE
              AND refreshed_at >= NOW() -
                  (:max_age_seconds * INTERVAL '1 second')
        """),
        {"max_age_seconds": max_age_seconds},
    ).mappings().first()
    return dict(row) if row else None


def refresh_entity_counts(session) -> dict[str, Any]:
    """Refresh all four exact counts in one inexpensive database statement."""
    ensure_entity_counts_schema(session)
    session.execute(text("SET LOCAL statement_timeout = 5000"))
    counts = dict(
        session.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM deals) AS deals,
              (SELECT COUNT(*) FROM companies) AS companies,
              (SELECT COUNT(*) FROM drugs) AS assets,
              (SELECT COUNT(DISTINCT drug_id) FROM deal_drugs)
                AS deal_linked_assets
        """)).mappings().one()
    )
    row = session.execute(
        text("""
            INSERT INTO api_entity_counts (
                singleton, deals, companies, assets, deal_linked_assets,
                refreshed_at
            ) VALUES (
                TRUE, :deals, :companies, :assets, :deal_linked_assets, NOW()
            )
            ON CONFLICT (singleton) DO UPDATE SET
                deals=EXCLUDED.deals,
                companies=EXCLUDED.companies,
                assets=EXCLUDED.assets,
                deal_linked_assets=EXCLUDED.deal_linked_assets,
                refreshed_at=EXCLUDED.refreshed_at
            RETURNING deals, companies, assets, deal_linked_assets, refreshed_at
        """),
        counts,
    ).mappings().one()
    return dict(row)


def get_entity_counts(
    session,
    *,
    max_age_seconds: int = COUNTS_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Return a fresh singleton count snapshot, serializing refreshes."""
    ensure_entity_counts_schema(session)
    cached = _cached_counts(session, max_age_seconds)
    cache_hit = cached is not None
    if cached is None:
        session.execute(text("SELECT pg_advisory_xact_lock(61320260715)"))
        cached = _cached_counts(session, max_age_seconds)
        cache_hit = cached is not None
        if cached is None:
            cached = refresh_entity_counts(session)

    refreshed_at = cached["refreshed_at"]
    if refreshed_at.tzinfo is None:
        refreshed_at = refreshed_at.replace(tzinfo=timezone.utc)
    return {
        "deals": int(cached["deals"]),
        "companies": int(cached["companies"]),
        "assets": int(cached["assets"]),
        "deal_linked_assets": int(cached["deal_linked_assets"]),
        "as_of": refreshed_at.astimezone(timezone.utc).isoformat(),
        "cache_hit": cache_hit,
        "root_population": "cortellis_deals",
        "description": (
            "Exact counts of Cortellis deal records and the companies/assets "
            "embedded in or linked from those deal records."
        ),
    }

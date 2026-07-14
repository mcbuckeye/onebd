"""Durable, deduplicated alerts for first-observed indication entrants."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import text

from unified_api.services.company_strategy import (
    company_indication_entrant_snapshot,
)


def ensure_company_entrant_alert_schema(session) -> None:
    """Create and forward-migrate competitor entrant alert storage."""
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS tracked_competitors (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            company_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, company_id)
        );

        ALTER TABLE tracked_competitors
          ADD COLUMN IF NOT EXISTS entrant_alerts_enabled BOOLEAN NOT NULL
              DEFAULT TRUE;
        ALTER TABLE tracked_competitors
          ADD COLUMN IF NOT EXISTS entrant_baselined_at TIMESTAMPTZ;
        ALTER TABLE tracked_competitors
          ADD COLUMN IF NOT EXISTS entrant_last_checked_at TIMESTAMPTZ;

        CREATE TABLE IF NOT EXISTS company_entrant_detections (
            id BIGSERIAL PRIMARY KEY,
            subject_company_id INTEGER NOT NULL
                REFERENCES companies(id) ON DELETE CASCADE,
            entrant_company_id INTEGER NOT NULL
                REFERENCES companies(id) ON DELETE CASCADE,
            indication_id INTEGER NOT NULL
                REFERENCES indications(id) ON DELETE CASCADE,
            first_observed_date DATE NOT NULL,
            observed_deals INTEGER NOT NULL,
            evidence_deal_ids INTEGER[] NOT NULL DEFAULT '{}',
            detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(subject_company_id, entrant_company_id, indication_id)
        );

        CREATE INDEX IF NOT EXISTS ix_company_entrant_detections_subject
          ON company_entrant_detections
             (subject_company_id, first_observed_date DESC);

        CREATE TABLE IF NOT EXISTS company_entrant_alerts (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            tracked_competitor_id INTEGER NOT NULL
                REFERENCES tracked_competitors(id) ON DELETE CASCADE,
            detection_id BIGINT NOT NULL
                REFERENCES company_entrant_detections(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            read_at TIMESTAMPTZ,
            dismissed_at TIMESTAMPTZ,
            UNIQUE(user_id, detection_id)
        );

        CREATE INDEX IF NOT EXISTS ix_company_entrant_alerts_user
          ON company_entrant_alerts
             (user_id, created_at DESC)
          WHERE dismissed_at IS NULL;
    """))


def entrant_alert_content(
    *,
    subject_name: str,
    entrant_name: str,
    indication_name: str,
    first_observed_date: date | str,
    observed_deals: int,
) -> str:
    """Build an evidence-limited alert without overstating market entry."""
    count = int(observed_deals)
    deal_word = "deal" if count == 1 else "deals"
    return (
        f"While tracking {subject_name}, {entrant_name} was first observed in "
        f"{indication_name} on {first_observed_date} in the Cortellis deal "
        f"record ({count} linked {deal_word}). This is first observed in the "
        "available deal data, not proof of first-ever market activity."
    )


def scan_company_entrant_alerts(
    session,
    *,
    years: int = 5,
    entrant_days: int = 365,
) -> dict[str, Any]:
    """Refresh detections and create one alert per user/detection after baseline."""
    ensure_company_entrant_alert_schema(session)
    acquired = bool(session.execute(text("""
        SELECT pg_try_advisory_xact_lock(
            hashtext('onebd_company_entrant_alert_scan')
        )
    """)).scalar())
    if not acquired:
        return {
            "status": "busy",
            "tracked_companies": 0,
            "detections_inserted": 0,
            "alerts_created": 0,
            "trackers_baselined": 0,
        }

    tracking_rows = session.execute(text("""
        SELECT tracked.id, tracked.user_id, tracked.company_id,
               tracked.entrant_baselined_at, company.name AS company_name
        FROM tracked_competitors tracked
        JOIN companies company ON company.id = tracked.company_id
        WHERE tracked.entrant_alerts_enabled = TRUE
        ORDER BY tracked.company_id, tracked.id
    """)).mappings().all()
    by_company: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in tracking_rows:
        by_company[int(row["company_id"])].append(dict(row))

    detections_inserted = 0
    alerts_created = 0
    trackers_baselined = 0
    for company_id, trackers in by_company.items():
        snapshot = company_indication_entrant_snapshot(
            session,
            company_id,
            years=years,
            entrant_days=entrant_days,
            limit=100,
        )
        existing = {
            (int(row["entrant_company_id"]), int(row["indication_id"]))
            for row in session.execute(text("""
                SELECT entrant_company_id, indication_id
                FROM company_entrant_detections
                WHERE subject_company_id = :company_id
            """), {"company_id": company_id}).mappings().all()
        }
        new_detections: list[tuple[int, dict[str, Any]]] = []
        for entrant in snapshot["entrants"]:
            key = (
                int(entrant["company_id"]),
                int(entrant["indication_id"]),
            )
            detection_id = session.execute(text("""
                INSERT INTO company_entrant_detections (
                    subject_company_id, entrant_company_id, indication_id,
                    first_observed_date, observed_deals, evidence_deal_ids
                ) VALUES (
                    :subject_company_id, :entrant_company_id, :indication_id,
                    :first_observed_date, :observed_deals, :evidence_deal_ids
                )
                ON CONFLICT (
                    subject_company_id, entrant_company_id, indication_id
                ) DO UPDATE SET
                    first_observed_date = EXCLUDED.first_observed_date,
                    observed_deals = EXCLUDED.observed_deals,
                    evidence_deal_ids = EXCLUDED.evidence_deal_ids,
                    last_seen_at = NOW()
                RETURNING id
            """), {
                "subject_company_id": company_id,
                "entrant_company_id": key[0],
                "indication_id": key[1],
                "first_observed_date": entrant["first_observed_date"],
                "observed_deals": entrant["observed_deals"],
                "evidence_deal_ids": list(entrant["evidence_deal_ids"] or []),
            }).scalar_one()
            if key not in existing:
                detections_inserted += 1
                new_detections.append((int(detection_id), entrant))

        for tracker in trackers:
            if tracker["entrant_baselined_at"] is None:
                trackers_baselined += 1
            else:
                for detection_id, entrant in new_detections:
                    content = entrant_alert_content(
                        subject_name=tracker["company_name"],
                        entrant_name=entrant["company_name"],
                        indication_name=entrant["indication_name"],
                        first_observed_date=entrant["first_observed_date"],
                        observed_deals=entrant["observed_deals"],
                    )
                    inserted = session.execute(text("""
                        INSERT INTO company_entrant_alerts (
                            user_id, tracked_competitor_id, detection_id, content
                        ) VALUES (
                            :user_id, :tracked_competitor_id, :detection_id,
                            :content
                        )
                        ON CONFLICT (user_id, detection_id) DO NOTHING
                        RETURNING id
                    """), {
                        "user_id": tracker["user_id"],
                        "tracked_competitor_id": tracker["id"],
                        "detection_id": detection_id,
                        "content": content,
                    }).scalar_one_or_none()
                    alerts_created += int(inserted is not None)
            session.execute(text("""
                UPDATE tracked_competitors
                SET entrant_baselined_at = COALESCE(
                        entrant_baselined_at, NOW()
                    ),
                    entrant_last_checked_at = NOW()
                WHERE id = :tracked_competitor_id
            """), {"tracked_competitor_id": tracker["id"]})

    return {
        "status": "completed",
        "tracked_companies": len(by_company),
        "tracking_rows": len(tracking_rows),
        "detections_inserted": detections_inserted,
        "alerts_created": alerts_created,
        "trackers_baselined": trackers_baselined,
        "years": max(1, min(20, int(years))),
        "entrant_days": max(30, min(1825, int(entrant_days))),
    }


def company_entrant_alert_status(session) -> dict[str, Any]:
    """Return release and operational counts for the entrant alert workflow."""
    ensure_company_entrant_alert_schema(session)
    return dict(session.execute(text("""
        SELECT
          (SELECT COUNT(*) FROM tracked_competitors
           WHERE entrant_alerts_enabled = TRUE) AS enabled_tracking_rows,
          (SELECT COUNT(*) FROM tracked_competitors
           WHERE entrant_alerts_enabled = TRUE
             AND entrant_baselined_at IS NOT NULL) AS baselined_tracking_rows,
          (SELECT COUNT(*) FROM company_entrant_detections) AS detections,
          (SELECT COUNT(*) FROM company_entrant_alerts) AS alerts,
          (SELECT COUNT(*) FROM company_entrant_alerts
           WHERE read_at IS NULL AND dismissed_at IS NULL) AS unread_alerts,
          (SELECT MAX(entrant_last_checked_at) FROM tracked_competitors)
              AS last_checked_at
    """)).mappings().one())

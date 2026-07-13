"""Persistence and batch extraction for normalized Cortellis financial terms."""

from __future__ import annotations

import json
import math
from typing import Any

from sqlalchemy import text

from unified_api.services.finance_parser import (
    FINANCE_PARSER_VERSION,
    _extract_payment,
    extract_financial_terms,
)


KNOWN_SOURCE_PAYMENT_TYPES = {
    "Adjusted Milestones",
    "Contingent Equity",
    "Dev/Reg Milestones",
    "Equity",
    "Equity Stake(%)",
    "Loan/Credit",
    "Lump Sum",
    "Milestones",
    "Option Payment",
    "Other",
    "Other Equity",
    "Other Milestones",
    "Profit Split(%)",
    "R&D Funding",
    "Royalty(%)",
    "Royalty Payment",
    "Sales Milestones",
    "Transfer Price(%)",
    "Undisclosed",
    "Upfront Equity",
    "Upfront Payment",
}


def ensure_financial_term_schema(session) -> None:
    """Create provenance-preserving extraction tables and analytics indexes."""
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS deal_financial_terms (
            id BIGSERIAL PRIMARY KEY,
            deal_id INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
            recipient TEXT NOT NULL,
            basis TEXT NOT NULL,
            term_type TEXT NOT NULL,
            source_payment_type TEXT,
            payment_date TIMESTAMPTZ,
            amount_reported_millions DOUBLE PRECISION,
            reported_currency VARCHAR(10),
            reported_unit VARCHAR(20),
            amount_usd_millions DOUBLE PRECISION,
            rate_min_pct DOUBLE PRECISION,
            rate_max_pct DOUBLE PRECISION,
            accuracy TEXT,
            disclosure_status TEXT,
            note TEXT,
            is_breakdown BOOLEAN NOT NULL DEFAULT FALSE,
            confidence DOUBLE PRECISION NOT NULL,
            source_path TEXT NOT NULL,
            source_hash VARCHAR(64) NOT NULL,
            parser_version INTEGER NOT NULL,
            source_payload JSONB NOT NULL,
            extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (deal_id, source_path, parser_version)
        )
    """))
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_deal_financial_terms_analytics
        ON deal_financial_terms (term_type, basis, reported_currency)
        WHERE disclosure_status = 'Known'
    """))
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_deal_financial_terms_deal
        ON deal_financial_terms (deal_id)
    """))
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS deal_financial_term_extractions (
            deal_id INTEGER PRIMARY KEY REFERENCES deals(id) ON DELETE CASCADE,
            source_hash VARCHAR(64) NOT NULL,
            parser_version INTEGER NOT NULL,
            status TEXT NOT NULL,
            terms_extracted INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))


def extract_financial_term_batch(
    session,
    *,
    batch_size: int = 100,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """Extract one resumable batch and return counts plus reviewable samples."""
    lock_acquired = session.execute(text(
        "SELECT pg_try_advisory_xact_lock(hashtext('onebd_financial_term_extraction'))"
    )).scalar()
    if not lock_acquired:
        return {
            "status": "busy",
            "processed": 0,
            "terms_extracted": 0,
            "errors": 0,
            "dry_run": dry_run,
            "parser_version": FINANCE_PARSER_VERSION,
            "sample": [],
        }
    ensure_financial_term_schema(session)
    deals = session.execute(text("""
        SELECT f.deal_id, f.finance_detail_raw,
               md5(f.finance_detail_raw::text) AS source_hash
        FROM deal_finance_summary f
        LEFT JOIN deal_financial_term_extractions e ON e.deal_id = f.deal_id
        WHERE f.finance_detail_raw IS NOT NULL
          AND (
            :force
            OR e.deal_id IS NULL
            OR e.parser_version <> :parser_version
            OR e.source_hash <> md5(f.finance_detail_raw::text)
            OR e.status = 'failed'
        )
        ORDER BY f.deal_id
        LIMIT :batch_size
    """), {
        "force": force,
        "parser_version": FINANCE_PARSER_VERSION,
        "batch_size": batch_size,
    }).mappings().all()

    processed = 0
    terms_extracted = 0
    errors = 0
    samples = []
    for deal in deals:
        deal_id = int(deal["deal_id"])
        payload = deal["finance_detail_raw"]
        source_hash = deal["source_hash"]
        try:
            with session.begin_nested():
                terms = extract_financial_terms(payload, deal_id=deal_id)
                if not dry_run:
                    session.execute(text(
                        "DELETE FROM deal_financial_terms WHERE deal_id = :deal_id"
                    ), {"deal_id": deal_id})
                    for term in terms:
                        session.execute(text("""
                            INSERT INTO deal_financial_terms (
                                deal_id, recipient, basis, term_type, source_payment_type,
                                payment_date, amount_reported_millions, reported_currency,
                                reported_unit, amount_usd_millions, rate_min_pct,
                                rate_max_pct, accuracy, disclosure_status, note,
                                is_breakdown, confidence, source_path, source_hash,
                                parser_version, source_payload
                            ) VALUES (
                                :deal_id, :recipient, :basis, :term_type, :source_payment_type,
                                :payment_date, :amount_reported_millions, :reported_currency,
                                :reported_unit, :amount_usd_millions, :rate_min_pct,
                                :rate_max_pct, :accuracy, :disclosure_status, :note,
                                :is_breakdown, :confidence, :source_path, :source_hash,
                                :parser_version, CAST(:source_payload AS JSONB)
                            )
                        """), {
                            **{
                                key: value
                                for key, value in term.items()
                                if key != "source_payload"
                            },
                            "source_hash": source_hash,
                            "source_payload": json.dumps(term["source_payload"]),
                        })
                    session.execute(text("""
                        INSERT INTO deal_financial_term_extractions (
                            deal_id, source_hash, parser_version, status,
                            terms_extracted, error_message, extracted_at
                        ) VALUES (
                            :deal_id, :source_hash, :parser_version, 'completed',
                            :terms_extracted, NULL, NOW()
                        )
                        ON CONFLICT (deal_id) DO UPDATE SET
                            source_hash = EXCLUDED.source_hash,
                            parser_version = EXCLUDED.parser_version,
                            status = EXCLUDED.status,
                            terms_extracted = EXCLUDED.terms_extracted,
                            error_message = NULL,
                            extracted_at = NOW()
                    """), {
                        "deal_id": deal_id,
                        "source_hash": source_hash,
                        "parser_version": FINANCE_PARSER_VERSION,
                        "terms_extracted": len(terms),
                    })
            processed += 1
            terms_extracted += len(terms)
            if len(samples) < 5:
                samples.append({"deal_id": deal_id, "terms": terms[:5]})
        except Exception as exc:
            errors += 1
            if not dry_run:
                with session.begin_nested():
                    session.execute(text("""
                        INSERT INTO deal_financial_term_extractions (
                            deal_id, source_hash, parser_version, status,
                            terms_extracted, error_message, extracted_at
                        ) VALUES (
                            :deal_id, :source_hash, :parser_version, 'failed', 0, :error, NOW()
                        )
                        ON CONFLICT (deal_id) DO UPDATE SET
                            source_hash = EXCLUDED.source_hash,
                            parser_version = EXCLUDED.parser_version,
                            status = 'failed', terms_extracted = 0,
                            error_message = EXCLUDED.error_message, extracted_at = NOW()
                    """), {
                        "deal_id": deal_id,
                        "source_hash": source_hash,
                        "parser_version": FINANCE_PARSER_VERSION,
                        "error": str(exc)[:1000],
                    })

    return {
        "processed": processed,
        "terms_extracted": terms_extracted,
        "errors": errors,
        "dry_run": dry_run,
        "parser_version": FINANCE_PARSER_VERSION,
        "sample": samples,
    }


def financial_term_status(session) -> dict:
    ensure_financial_term_schema(session)
    row = session.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM deal_finance_summary
             WHERE finance_detail_raw IS NOT NULL) AS deals_with_raw_json,
            (SELECT COUNT(*) FROM deal_financial_term_extractions
             WHERE status = 'completed' AND parser_version = :parser_version) AS deals_parsed,
            (SELECT COUNT(*) FROM deal_financial_term_extractions
             WHERE status = 'failed' AND parser_version = :parser_version) AS deals_failed,
            (SELECT COUNT(*) FROM deal_financial_terms
             WHERE parser_version = :parser_version) AS terms_total,
            (SELECT COUNT(*) FROM deal_financial_terms
             WHERE parser_version = :parser_version
               AND term_type = 'upfront_payment'
               AND amount_usd_millions IS NOT NULL) AS upfront_terms,
            (SELECT COUNT(*) FROM deal_financial_terms
             WHERE parser_version = :parser_version
               AND term_type LIKE '%milestone%'
               AND amount_usd_millions IS NOT NULL) AS milestone_terms,
            (SELECT COUNT(*) FROM deal_financial_terms
             WHERE parser_version = :parser_version
               AND term_type = 'royalty_rate'
               AND (rate_min_pct IS NOT NULL OR rate_max_pct IS NOT NULL)) AS royalty_terms
    """), {"parser_version": FINANCE_PARSER_VERSION}).mappings().one()
    result = dict(row)
    raw = result["deals_with_raw_json"] or 0
    result["parse_coverage_pct"] = round(
        100 * (result["deals_parsed"] or 0) / raw,
        2,
    ) if raw else 0.0
    result["parser_version"] = FINANCE_PARSER_VERSION
    return result


def _values_match(actual: Any, expected: Any) -> bool:
    if isinstance(actual, (int, float)) or isinstance(expected, (int, float)):
        if actual is None or expected is None:
            return actual is expected
        return math.isclose(float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-9)
    return actual == expected


def validate_financial_term_record(record: dict) -> list[dict]:
    """Compare one persisted term with a fresh extraction from its source node."""
    payload = record.get("source_payload")
    if not isinstance(payload, dict):
        return [{"field": "source_payload", "expected": "object", "actual": type(payload).__name__}]
    expected = _extract_payment(
        payload,
        deal_id=record.get("deal_id"),
        recipient=record.get("recipient"),
        basis=record.get("basis"),
        source_path=record.get("source_path"),
        is_breakdown=bool(record.get("is_breakdown")),
    )
    fields = (
        "recipient",
        "basis",
        "term_type",
        "source_payment_type",
        "amount_reported_millions",
        "reported_currency",
        "reported_unit",
        "amount_usd_millions",
        "rate_min_pct",
        "rate_max_pct",
        "accuracy",
        "disclosure_status",
        "note",
        "is_breakdown",
        "confidence",
        "source_path",
    )
    return [
        {"field": field, "expected": expected.get(field), "actual": record.get(field)}
        for field in fields
        if not _values_match(record.get(field), expected.get(field))
    ]


def financial_term_validation_status(session, *, sample_per_type: int = 25) -> dict:
    """Audit extraction coverage, structural fidelity, units, and percentage bounds."""
    sample_per_type = max(1, min(100, sample_per_type))
    status = financial_term_status(session)
    population = dict(session.execute(text("""
        SELECT
            COUNT(*) AS terms_total,
            COUNT(DISTINCT deal_id) AS deals_with_terms,
            COUNT(*) FILTER (
                WHERE disclosure_status = 'Known'
                  AND reported_unit = '%'
                  AND NULLIF(source_payload->'Values'->'ValueReported'->>'@text', '') IS NOT NULL
            ) AS known_percentage_terms,
            COUNT(*) FILTER (
                WHERE disclosure_status = 'Known'
                  AND reported_unit = '%'
                  AND NULLIF(source_payload->'Values'->'ValueReported'->>'@text', '') IS NOT NULL
                  AND (rate_min_pct IS NOT NULL OR rate_max_pct IS NOT NULL)
            ) AS captured_percentage_terms,
            COUNT(*) FILTER (
                WHERE reported_unit NOT IN ('Million', 'B', 'T', '%')
                  AND COALESCE(reported_unit, '') <> ''
            ) AS unrecognized_unit_terms,
            COUNT(*) FILTER (
                WHERE amount_reported_millions < 0 OR amount_usd_millions < 0
            ) AS negative_amount_terms,
            COUNT(*) FILTER (
                WHERE rate_min_pct < 0 OR rate_max_pct < 0
                   OR rate_min_pct > 100 OR rate_max_pct > 100
                   OR (rate_min_pct IS NOT NULL AND rate_max_pct IS NOT NULL
                       AND rate_min_pct > rate_max_pct)
            ) AS invalid_rate_terms,
            COUNT(*) FILTER (
                WHERE source_payment_type IS DISTINCT FROM source_payload->>'Type'
            ) AS source_type_mismatches
        FROM deal_financial_terms
        WHERE parser_version = :parser_version
    """), {"parser_version": FINANCE_PARSER_VERSION}).mappings().one())

    source_types = {
        row[0]
        for row in session.execute(text("""
            SELECT DISTINCT source_payment_type
            FROM deal_financial_terms
            WHERE parser_version = :parser_version
              AND source_payment_type IS NOT NULL
        """), {"parser_version": FINANCE_PARSER_VERSION})
    }
    unknown_source_types = sorted(source_types - KNOWN_SOURCE_PAYMENT_TYPES)

    rows = session.execute(text("""
        WITH sampled AS (
            SELECT t.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY term_type
                       ORDER BY md5(deal_id::text || ':' || source_path)
                   ) AS sample_rank
            FROM deal_financial_terms t
            WHERE parser_version = :parser_version
        )
        SELECT * FROM sampled WHERE sample_rank <= :sample_per_type
        ORDER BY term_type, sample_rank
    """), {
        "parser_version": FINANCE_PARSER_VERSION,
        "sample_per_type": sample_per_type,
    }).mappings().all()

    failures = []
    failed = 0
    for row in rows:
        mismatches = validate_financial_term_record(dict(row))
        if mismatches:
            failed += 1
            if len(failures) < 20:
                failures.append({
                    "term_id": row["id"],
                    "deal_id": row["deal_id"],
                    "term_type": row["term_type"],
                    "source_path": row["source_path"],
                    "mismatches": mismatches,
                })

    sampled = len(rows)
    known_percentage = int(population["known_percentage_terms"] or 0)
    captured_percentage = int(population["captured_percentage_terms"] or 0)
    report = {
        **status,
        **population,
        "known_source_types": len(source_types),
        "unknown_source_types": unknown_source_types,
        "sampled_terms": sampled,
        "sample_failures": failed,
        "sample_field_accuracy_pct": round(100 * (sampled - failed) / sampled, 2)
        if sampled else 0.0,
        "known_percentage_capture_pct": round(
            100 * captured_percentage / known_percentage,
            2,
        ) if known_percentage else 100.0,
        "failure_samples": failures,
    }
    report["governed_release_ready"] = bool(
        report["parse_coverage_pct"] == 100.0
        and report["terms_total"] > 0
        and not report["deals_failed"]
        and not report["unrecognized_unit_terms"]
        and not report["negative_amount_terms"]
        and not report["invalid_rate_terms"]
        and not report["source_type_mismatches"]
        and not unknown_source_types
        and report["sample_field_accuracy_pct"] == 100.0
        and report["known_percentage_capture_pct"] == 100.0
    )
    return report

"""Persistence and batch extraction for normalized Cortellis financial terms."""

from __future__ import annotations

import json

from sqlalchemy import text

from unified_api.services.finance_parser import (
    FINANCE_PARSER_VERSION,
    extract_financial_terms,
)


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
                        **{key: value for key, value in term.items() if key != "source_payload"},
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
               AND rate_min_pct IS NOT NULL) AS royalty_terms
    """), {"parser_version": FINANCE_PARSER_VERSION}).mappings().one()
    result = dict(row)
    raw = result["deals_with_raw_json"] or 0
    result["parse_coverage_pct"] = round(
        100 * (result["deals_parsed"] or 0) / raw,
        2,
    ) if raw else 0.0
    result["parser_version"] = FINANCE_PARSER_VERSION
    return result

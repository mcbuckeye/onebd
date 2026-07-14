"""Deterministic, release-gated financial-term analytics for Chat."""

from __future__ import annotations

import re
from textwrap import dedent
from typing import Optional

from unified_api.services.finance_parser import FINANCE_PARSER_VERSION


FINANCIAL_BASIS = "projected_current"


def _sql(value: str) -> str:
    return " ".join(dedent(value).strip().split())


def _upfront_threshold_usd_millions(question: str) -> Optional[float]:
    match = re.search(
        r"(?:over|above|greater\s+than|>)\s*\$?\s*"
        r"(\d+(?:\.\d+)?)\s*(billion|bn|b|million|mm|m)\b",
        question,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = float(match.group(1))
    if match.group(2).lower() in {"billion", "bn", "b"}:
        value *= 1000
    return value


def build_governed_financial_sql(question: str) -> Optional[str]:
    """Return SQL only for financial questions with an explicit semantic contract."""
    normalized = question.lower()

    if (
        "upfront" in normalized
        and "phase 2" in normalized
        and ("adc" in normalized or "antibody drug conjugate" in normalized)
        and any(word in normalized for word in ("typical", "median", "range"))
    ):
        return _sql(f"""
            WITH eligible_deals AS (
                SELECT DISTINCT deal.id
                FROM deals deal
                JOIN deal_technologies deal_technology
                  ON deal_technology.deal_id = deal.id
                JOIN technologies technology
                  ON technology.id = deal_technology.technology_id
                WHERE deal.phase_highest_start = 'Phase 2 Clinical'
                  AND technology.name = 'Antibody drug conjugate'
                  AND deal.agreement_type ILIKE '%License%'
            ), per_deal AS (
                SELECT term.deal_id,
                       MAX(term.amount_usd_millions) AS upfront_usd_millions
                FROM deal_financial_terms term
                JOIN eligible_deals eligible ON eligible.id = term.deal_id
                WHERE term.parser_version = {FINANCE_PARSER_VERSION}
                  AND term.term_type = 'upfront_payment'
                  AND term.basis = '{FINANCIAL_BASIS}'
                  AND term.disclosure_status = 'Known'
                  AND term.amount_usd_millions IS NOT NULL
                  AND NOT term.is_breakdown
                GROUP BY term.deal_id
            )
            SELECT
                PERCENTILE_CONT(0.25) WITHIN GROUP
                  (ORDER BY upfront_usd_millions) AS p25_upfront_usd_millions,
                PERCENTILE_CONT(0.5) WITHIN GROUP
                  (ORDER BY upfront_usd_millions) AS median_upfront_usd_millions,
                PERCENTILE_CONT(0.75) WITHIN GROUP
                  (ORDER BY upfront_usd_millions) AS p75_upfront_usd_millions,
                AVG(upfront_usd_millions) AS average_upfront_usd_millions,
                COUNT(*)::int AS disclosed_deal_count,
                (SELECT COUNT(*)::int FROM eligible_deals) AS eligible_deal_count,
                'projected_current, one maximum non-breakdown headline per deal'
                  AS metric_definition,
                'Cortellis FinanceDetail / parser v{FINANCE_PARSER_VERSION}' AS source
            FROM per_deal
        """)

    if (
        "milestone" in normalized
        and "phase 3" in normalized
        and "licens" in normalized
        and any(word in normalized for word in ("typical", "median", "range"))
    ):
        return _sql(f"""
            WITH eligible_deals AS (
                SELECT deal.id
                FROM deals deal
                WHERE deal.phase_highest_start = 'Phase 3 Clinical'
                  AND deal.agreement_type ILIKE '%License%'
            ), per_deal AS (
                SELECT term.deal_id,
                       MAX(term.amount_usd_millions) AS milestone_usd_millions
                FROM deal_financial_terms term
                JOIN eligible_deals eligible ON eligible.id = term.deal_id
                WHERE term.parser_version = {FINANCE_PARSER_VERSION}
                  AND term.term_type = 'milestone_total'
                  AND term.basis = '{FINANCIAL_BASIS}'
                  AND term.disclosure_status = 'Known'
                  AND term.amount_usd_millions IS NOT NULL
                  AND NOT term.is_breakdown
                GROUP BY term.deal_id
            )
            SELECT
                PERCENTILE_CONT(0.25) WITHIN GROUP
                  (ORDER BY milestone_usd_millions) AS p25_milestone_usd_millions,
                PERCENTILE_CONT(0.5) WITHIN GROUP
                  (ORDER BY milestone_usd_millions) AS median_milestone_usd_millions,
                PERCENTILE_CONT(0.75) WITHIN GROUP
                  (ORDER BY milestone_usd_millions) AS p75_milestone_usd_millions,
                AVG(milestone_usd_millions) AS average_milestone_usd_millions,
                COUNT(*)::int AS disclosed_deal_count,
                (SELECT COUNT(*)::int FROM eligible_deals) AS eligible_deal_count,
                'projected_current milestone total, one maximum non-breakdown headline per deal'
                  AS metric_definition,
                'Cortellis FinanceDetail / parser v{FINANCE_PARSER_VERSION}' AS source
            FROM per_deal
        """)

    if (
        "royalt" in normalized
        and "oncology" in normalized
        and "bispecific" in normalized
        and any(word in normalized for word in ("typical", "median", "range", "rate"))
    ):
        return _sql(f"""
            WITH eligible_deals AS (
                SELECT DISTINCT deal.id
                FROM deals deal
                JOIN therapy_areas therapy
                  ON therapy.id = deal.therapy_area_id
                JOIN deal_technologies deal_technology
                  ON deal_technology.deal_id = deal.id
                JOIN technologies technology
                  ON technology.id = deal_technology.technology_id
                WHERE therapy.name = 'Cancer'
                  AND technology.name ILIKE 'Bispecific%'
                  AND deal.agreement_type ILIKE '%License%'
            ), per_deal AS (
                SELECT term.deal_id,
                       MIN(COALESCE(term.rate_min_pct, term.rate_max_pct))
                         AS royalty_low_pct,
                       MAX(COALESCE(term.rate_max_pct, term.rate_min_pct))
                         AS royalty_high_pct
                FROM deal_financial_terms term
                JOIN eligible_deals eligible ON eligible.id = term.deal_id
                WHERE term.parser_version = {FINANCE_PARSER_VERSION}
                  AND term.term_type = 'royalty_rate'
                  AND term.basis = '{FINANCIAL_BASIS}'
                  AND term.disclosure_status = 'Known'
                  AND (term.rate_min_pct IS NOT NULL OR term.rate_max_pct IS NOT NULL)
                  AND NOT term.is_breakdown
                GROUP BY term.deal_id
            ), summarized AS (
                SELECT deal_id, royalty_low_pct, royalty_high_pct,
                       (royalty_low_pct + royalty_high_pct) / 2.0
                         AS royalty_midpoint_pct
                FROM per_deal
            )
            SELECT
                PERCENTILE_CONT(0.5) WITHIN GROUP
                  (ORDER BY royalty_low_pct) AS median_royalty_low_pct,
                PERCENTILE_CONT(0.5) WITHIN GROUP
                  (ORDER BY royalty_high_pct) AS median_royalty_high_pct,
                PERCENTILE_CONT(0.25) WITHIN GROUP
                  (ORDER BY royalty_midpoint_pct) AS p25_royalty_midpoint_pct,
                PERCENTILE_CONT(0.5) WITHIN GROUP
                  (ORDER BY royalty_midpoint_pct) AS median_royalty_midpoint_pct,
                PERCENTILE_CONT(0.75) WITHIN GROUP
                  (ORDER BY royalty_midpoint_pct) AS p75_royalty_midpoint_pct,
                COUNT(*)::int AS disclosed_deal_count,
                (SELECT COUNT(*)::int FROM eligible_deals) AS eligible_deal_count,
                'projected_current, per-deal disclosed low/high range'
                  AS metric_definition,
                'Cortellis FinanceDetail / parser v{FINANCE_PARSER_VERSION}' AS source
            FROM summarized
        """)

    threshold = _upfront_threshold_usd_millions(question)
    if "upfront" in normalized and "deal" in normalized and threshold is not None:
        threshold_literal = f"{threshold:.12g}"
        return _sql(f"""
            WITH per_deal AS (
                SELECT term.deal_id,
                       MAX(term.amount_usd_millions) AS upfront_usd_millions,
                       MAX(term.confidence) AS extraction_confidence
                FROM deal_financial_terms term
                WHERE term.parser_version = {FINANCE_PARSER_VERSION}
                  AND term.term_type = 'upfront_payment'
                  AND term.basis = '{FINANCIAL_BASIS}'
                  AND term.disclosure_status = 'Known'
                  AND term.amount_usd_millions IS NOT NULL
                  AND NOT term.is_breakdown
                GROUP BY term.deal_id
            )
            SELECT deal.id AS id, deal.id AS deal_id,
                   deal.title AS deal_title, deal.date_start,
                   deal.agreement_type, deal.phase_highest_start,
                   per_deal.upfront_usd_millions,
                   per_deal.extraction_confidence,
                   'projected_current, maximum non-breakdown headline per deal'
                     AS metric_definition,
                   'Cortellis FinanceDetail / parser v{FINANCE_PARSER_VERSION}' AS source
            FROM per_deal
            JOIN deals deal ON deal.id = per_deal.deal_id
            WHERE per_deal.upfront_usd_millions > {threshold_literal}
            ORDER BY per_deal.upfront_usd_millions DESC, deal.id
            LIMIT 20
        """)

    return None

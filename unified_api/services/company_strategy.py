"""Deterministic company strategy patterns and competitive overlap evidence."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from sqlalchemy import text


def _dict_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _jaccard(left: set[int], right: set[int]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _momentum_label(recent: int, prior: int) -> tuple[str, float | None]:
    if prior == 0:
        return ("newly active" if recent else "no recent activity"), None
    change = round(100 * (recent - prior) / prior, 1)
    if change >= 25:
        return "accelerating", change
    if change <= -25:
        return "slowing", change
    return "steady", change


def _focus_rows(session, company_id: int, years: int) -> dict[str, list[dict]]:
    params = {"company_id": company_id, "years": years}
    indications = _dict_rows(session.execute(text("""
        SELECT indication.id, indication.name,
               COUNT(DISTINCT deal.id) AS deal_count,
               (array_agg(DISTINCT deal.id ORDER BY deal.id DESC))[1:5]
                   AS evidence_deal_ids
        FROM deal_companies company_deal
        JOIN deals deal ON deal.id = company_deal.deal_id
        JOIN deal_indications link ON link.deal_id = deal.id
        JOIN indications indication ON indication.id = link.indication_id
        WHERE company_deal.company_id = :company_id
          AND deal.date_start >= CURRENT_DATE - (:years * INTERVAL '1 year')
        GROUP BY indication.id, indication.name
        ORDER BY deal_count DESC, indication.name
        LIMIT 10
    """), params).mappings().all())
    technologies = _dict_rows(session.execute(text("""
        SELECT technology.id, technology.name,
               COUNT(DISTINCT deal.id) AS deal_count,
               (array_agg(DISTINCT deal.id ORDER BY deal.id DESC))[1:5]
                   AS evidence_deal_ids
        FROM deal_companies company_deal
        JOIN deals deal ON deal.id = company_deal.deal_id
        JOIN deal_technologies link ON link.deal_id = deal.id
        JOIN technologies technology ON technology.id = link.technology_id
        WHERE company_deal.company_id = :company_id
          AND deal.date_start >= CURRENT_DATE - (:years * INTERVAL '1 year')
        GROUP BY technology.id, technology.name
        ORDER BY deal_count DESC, technology.name
        LIMIT 10
    """), params).mappings().all())
    agreement_types = _dict_rows(session.execute(text("""
        SELECT deal.agreement_type AS name,
               COUNT(DISTINCT deal.id) AS deal_count,
               (array_agg(DISTINCT deal.id ORDER BY deal.id DESC))[1:5]
                   AS evidence_deal_ids
        FROM deal_companies company_deal
        JOIN deals deal ON deal.id = company_deal.deal_id
        WHERE company_deal.company_id = :company_id
          AND deal.date_start >= CURRENT_DATE - (:years * INTERVAL '1 year')
          AND NULLIF(BTRIM(deal.agreement_type), '') IS NOT NULL
        GROUP BY deal.agreement_type
        ORDER BY deal_count DESC, deal.agreement_type
        LIMIT 10
    """), params).mappings().all())
    assets = _dict_rows(session.execute(text("""
        SELECT drug.id, drug.name_display AS name, drug.phase_highest_now,
               COUNT(DISTINCT deal.id) AS deal_count,
               (array_agg(DISTINCT deal.id ORDER BY deal.id DESC))[1:5]
                   AS evidence_deal_ids
        FROM deal_companies company_deal
        JOIN deals deal ON deal.id = company_deal.deal_id
        JOIN deal_drugs link ON link.deal_id = deal.id
        JOIN drugs drug ON drug.id = link.drug_id
        WHERE company_deal.company_id = :company_id
          AND deal.date_start >= CURRENT_DATE - (:years * INTERVAL '1 year')
        GROUP BY drug.id, drug.name_display, drug.phase_highest_now
        ORDER BY deal_count DESC, drug.name_display
        LIMIT 20
    """), params).mappings().all())
    partners = _dict_rows(session.execute(text("""
        SELECT partner.id, partner.name,
               COUNT(DISTINCT company_deal.deal_id) AS deal_count,
               (array_agg(DISTINCT company_deal.deal_id
                          ORDER BY company_deal.deal_id DESC))[1:5]
                   AS evidence_deal_ids
        FROM deal_companies company_deal
        JOIN deals deal ON deal.id = company_deal.deal_id
        JOIN deal_companies partner_link
          ON partner_link.deal_id = company_deal.deal_id
         AND partner_link.company_id <> company_deal.company_id
        JOIN companies partner ON partner.id = partner_link.company_id
        WHERE company_deal.company_id = :company_id
          AND deal.date_start >= CURRENT_DATE - (:years * INTERVAL '1 year')
        GROUP BY partner.id, partner.name
        ORDER BY deal_count DESC, partner.name
        LIMIT 10
    """), params).mappings().all())
    return {
        "indications": indications,
        "technologies": technologies,
        "agreement_types": agreement_types,
        "assets": assets,
        "partners": partners,
    }


def _competitive_peers(
    session,
    *,
    company_id: int,
    years: int,
    focus: Mapping[str, list[dict]],
    limit: int,
) -> list[dict[str, Any]]:
    indication_ids = [int(row["id"]) for row in focus["indications"]]
    technology_ids = [int(row["id"]) for row in focus["technologies"]]
    drug_ids = [int(row["id"]) for row in focus["assets"]]
    target_sets = {
        "indications": set(indication_ids),
        "technologies": set(technology_ids),
        "assets": set(drug_ids),
    }
    active_dimensions = [name for name, values in target_sets.items() if values]
    if not active_dimensions:
        return []

    hit_queries = []
    params: dict[str, Any] = {
        "company_id": company_id,
        "years": years,
    }
    if indication_ids:
        hit_queries.append("""
            SELECT company_deal.company_id, 'indication' AS dimension,
                   link.indication_id AS entity_id, deal.id AS deal_id
            FROM deal_companies company_deal
            JOIN deals deal ON deal.id = company_deal.deal_id
            JOIN deal_indications link ON link.deal_id = deal.id
            WHERE company_deal.company_id <> :company_id
              AND deal.date_start >= CURRENT_DATE - (:years * INTERVAL '1 year')
              AND link.indication_id = ANY(:indication_ids)
        """)
        params["indication_ids"] = indication_ids
    if technology_ids:
        hit_queries.append("""
            SELECT company_deal.company_id, 'technology' AS dimension,
                   link.technology_id AS entity_id, deal.id AS deal_id
            FROM deal_companies company_deal
            JOIN deals deal ON deal.id = company_deal.deal_id
            JOIN deal_technologies link ON link.deal_id = deal.id
            WHERE company_deal.company_id <> :company_id
              AND deal.date_start >= CURRENT_DATE - (:years * INTERVAL '1 year')
              AND link.technology_id = ANY(:technology_ids)
        """)
        params["technology_ids"] = technology_ids
    if drug_ids:
        hit_queries.append("""
            SELECT company_deal.company_id, 'asset' AS dimension,
                   link.drug_id AS entity_id, deal.id AS deal_id
            FROM deal_companies company_deal
            JOIN deals deal ON deal.id = company_deal.deal_id
            JOIN deal_drugs link ON link.deal_id = deal.id
            WHERE company_deal.company_id <> :company_id
              AND deal.date_start >= CURRENT_DATE - (:years * INTERVAL '1 year')
              AND link.drug_id = ANY(:drug_ids)
        """)
        params["drug_ids"] = drug_ids

    hits_sql = " UNION ALL ".join(hit_queries)
    rows = session.execute(text(f"""
        WITH raw_hits AS ({hits_sql}),
        ranked AS (
            SELECT company_id,
                   COUNT(DISTINCT (dimension, entity_id)) AS shared_entities,
                   (array_agg(DISTINCT deal_id ORDER BY deal_id DESC))[1:10]
                       AS overlap_deal_ids
            FROM raw_hits
            GROUP BY company_id
            ORDER BY shared_entities DESC, company_id
            LIMIT 200
        ),
        candidate_indications AS (
            SELECT ranked.company_id,
                   array_agg(DISTINCT link.indication_id) AS ids
            FROM ranked
            JOIN deal_companies company_deal
              ON company_deal.company_id = ranked.company_id
            JOIN deals deal ON deal.id = company_deal.deal_id
            JOIN deal_indications link ON link.deal_id = deal.id
            WHERE deal.date_start >= CURRENT_DATE - (:years * INTERVAL '1 year')
            GROUP BY ranked.company_id
        ),
        candidate_technologies AS (
            SELECT ranked.company_id,
                   array_agg(DISTINCT link.technology_id) AS ids
            FROM ranked
            JOIN deal_companies company_deal
              ON company_deal.company_id = ranked.company_id
            JOIN deals deal ON deal.id = company_deal.deal_id
            JOIN deal_technologies link ON link.deal_id = deal.id
            WHERE deal.date_start >= CURRENT_DATE - (:years * INTERVAL '1 year')
            GROUP BY ranked.company_id
        ),
        candidate_assets AS (
            SELECT ranked.company_id, array_agg(DISTINCT link.drug_id) AS ids
            FROM ranked
            JOIN deal_companies company_deal
              ON company_deal.company_id = ranked.company_id
            JOIN deals deal ON deal.id = company_deal.deal_id
            JOIN deal_drugs link ON link.deal_id = deal.id
            WHERE deal.date_start >= CURRENT_DATE - (:years * INTERVAL '1 year')
            GROUP BY ranked.company_id
        )
        SELECT company.id, company.name, company.company_type,
               ranked.shared_entities, ranked.overlap_deal_ids,
               COALESCE(candidate_indications.ids, ARRAY[]::INTEGER[])
                   AS indication_ids,
               COALESCE(candidate_technologies.ids, ARRAY[]::INTEGER[])
                   AS technology_ids,
               COALESCE(candidate_assets.ids, ARRAY[]::INTEGER[]) AS asset_ids,
               (SELECT COUNT(DISTINCT own.deal_id)
                FROM deal_companies own
                JOIN deal_companies peer ON peer.deal_id = own.deal_id
                WHERE own.company_id = :company_id
                  AND peer.company_id = company.id) AS direct_partner_deals
        FROM ranked
        JOIN companies company ON company.id = ranked.company_id
        LEFT JOIN candidate_indications
          ON candidate_indications.company_id = ranked.company_id
        LEFT JOIN candidate_technologies
          ON candidate_technologies.company_id = ranked.company_id
        LEFT JOIN candidate_assets
          ON candidate_assets.company_id = ranked.company_id
    """), params).mappings().all()

    indication_names = {
        int(row["id"]): row["name"] for row in focus["indications"]
    }
    technology_names = {
        int(row["id"]): row["name"] for row in focus["technologies"]
    }
    asset_names = {int(row["id"]): row["name"] for row in focus["assets"]}
    dimension_weight = 1 / len(active_dimensions)
    peers = []
    for row in rows:
        candidate_sets = {
            "indications": set(row["indication_ids"] or []),
            "technologies": set(row["technology_ids"] or []),
            "assets": set(row["asset_ids"] or []),
        }
        dimension_scores = {
            name: _jaccard(target_sets[name], candidate_sets[name])
            for name in active_dimensions
        }
        score = round(
            100 * sum(value * dimension_weight
                      for value in dimension_scores.values()),
            2,
        )
        peers.append({
            "company_id": int(row["id"]),
            "company_name": row["name"],
            "company_type": row["company_type"],
            "overlap_score": score,
            "dimension_scores": {
                key: round(100 * value, 2)
                for key, value in dimension_scores.items()
            },
            "shared_indications": [
                {"id": entity_id, "name": indication_names[entity_id]}
                for entity_id in sorted(
                    target_sets["indications"] & candidate_sets["indications"]
                )
                if entity_id in indication_names
            ],
            "shared_technologies": [
                {"id": entity_id, "name": technology_names[entity_id]}
                for entity_id in sorted(
                    target_sets["technologies"] & candidate_sets["technologies"]
                )
                if entity_id in technology_names
            ],
            "shared_assets": [
                {"id": entity_id, "name": asset_names[entity_id]}
                for entity_id in sorted(
                    target_sets["assets"] & candidate_sets["assets"]
                )
                if entity_id in asset_names
            ],
            "direct_partner_deals": int(row["direct_partner_deals"] or 0),
            "evidence_deal_ids": list(row["overlap_deal_ids"] or []),
        })
    peers.sort(key=lambda item: (-item["overlap_score"], item["company_name"]))
    return peers[:limit]


def _new_indication_entrants(
    session,
    *,
    company_id: int,
    indication_rows: list[dict],
    entrant_days: int,
    limit: int = 20,
) -> list[dict[str, Any]]:
    indication_ids = [int(row["id"]) for row in indication_rows[:3]]
    if not indication_ids:
        return []
    names = {int(row["id"]): row["name"] for row in indication_rows}
    rows = session.execute(text("""
        WITH first_observed AS (
            SELECT company_deal.company_id, link.indication_id,
                   MIN(deal.date_start::date) AS first_observed_date
            FROM deal_companies company_deal
            JOIN deals deal ON deal.id = company_deal.deal_id
            JOIN deal_indications link ON link.deal_id = deal.id
            WHERE link.indication_id = ANY(:indication_ids)
              AND deal.date_start IS NOT NULL
            GROUP BY company_deal.company_id, link.indication_id
        )
        SELECT first_observed.company_id, company.name AS company_name,
               company.company_type, first_observed.indication_id,
               first_observed.first_observed_date,
               COUNT(DISTINCT deal.id) AS observed_deals,
               (array_agg(DISTINCT deal.id ORDER BY deal.id DESC))[1:5]
                   AS evidence_deal_ids
        FROM first_observed
        JOIN companies company ON company.id = first_observed.company_id
        JOIN deal_companies company_deal
          ON company_deal.company_id = first_observed.company_id
        JOIN deals deal ON deal.id = company_deal.deal_id
        JOIN deal_indications link
          ON link.deal_id = deal.id
         AND link.indication_id = first_observed.indication_id
        WHERE first_observed.company_id <> :company_id
          AND first_observed.first_observed_date
              >= CURRENT_DATE - (:entrant_days * INTERVAL '1 day')
        GROUP BY first_observed.company_id, company.name, company.company_type,
                 first_observed.indication_id,
                 first_observed.first_observed_date
        ORDER BY first_observed.first_observed_date DESC,
                 observed_deals DESC, company.name
        LIMIT :limit
    """), {
        "company_id": company_id,
        "indication_ids": indication_ids,
        "entrant_days": entrant_days,
        "limit": limit,
    }).mappings().all()
    return [{
        **dict(row),
        "indication_name": names.get(int(row["indication_id"]), "Unknown"),
    } for row in rows]


def company_strategy_intelligence(
    session,
    company_id: int,
    *,
    years: int = 5,
    peer_limit: int = 10,
    entrant_days: int = 365,
) -> dict[str, Any] | None:
    """Return grounded deal-pattern strategy, overlap peers, and entrants."""
    years = max(1, min(20, int(years)))
    peer_limit = max(1, min(25, int(peer_limit)))
    entrant_days = max(30, min(1825, int(entrant_days)))
    company = session.execute(text("""
        SELECT id, name, company_type, hq_location, ticker
        FROM companies WHERE id = :company_id
    """), {"company_id": company_id}).mappings().one_or_none()
    if company is None:
        return None

    activity = dict(session.execute(text("""
        SELECT COUNT(DISTINCT deal.id) AS deal_count,
               COUNT(DISTINCT deal.id) FILTER (
                   WHERE company_deal.role = 'Principal'
               ) AS principal_deals,
               COUNT(DISTINCT deal.id) FILTER (
                   WHERE company_deal.role = 'Partner'
               ) AS partner_deals,
               COUNT(DISTINCT deal.id) FILTER (
                   WHERE deal.date_start >= CURRENT_DATE - INTERVAL '1 year'
               ) AS recent_12_month_deals,
               COUNT(DISTINCT deal.id) FILTER (
                   WHERE deal.date_start < CURRENT_DATE - INTERVAL '1 year'
                     AND deal.date_start >= CURRENT_DATE - INTERVAL '2 years'
               ) AS prior_12_month_deals,
               COUNT(finance.total_projected_current_amount)
                   AS disclosed_value_deals,
               AVG(finance.total_projected_current_amount) AS average_deal_value,
               MIN(deal.date_start::date) AS window_first_deal_date,
               MAX(deal.date_start::date) AS window_last_deal_date
        FROM deal_companies company_deal
        JOIN deals deal ON deal.id = company_deal.deal_id
        LEFT JOIN deal_finance_summary finance ON finance.deal_id = deal.id
        WHERE company_deal.company_id = :company_id
          AND deal.date_start >= CURRENT_DATE - (:years * INTERVAL '1 year')
    """), {"company_id": company_id, "years": years}).mappings().one())
    focus = _focus_rows(session, company_id, years)
    recent = int(activity["recent_12_month_deals"] or 0)
    prior = int(activity["prior_12_month_deals"] or 0)
    momentum, momentum_change = _momentum_label(recent, prior)
    deal_count = int(activity["deal_count"] or 0)

    statements = [{
        "claim": (
            f"{company['name']} has {deal_count} dated Cortellis deals in the "
            f"last {years} years; recent activity is {momentum} "
            f"({recent} in the latest 12 months versus {prior} previously)."
        ),
        "evidence_type": "deal_count_window",
    }]
    if focus["indications"]:
        top = focus["indications"][0]
        statements.append({
            "claim": (
                f"The most frequently linked indication is {top['name']} "
                f"({top['deal_count']} deals; deals may carry multiple indications)."
            ),
            "evidence_type": "deal_indication_links",
            "evidence_deal_ids": top["evidence_deal_ids"],
        })
    if focus["agreement_types"]:
        top = focus["agreement_types"][0]
        statements.append({
            "claim": (
                f"The most common recorded agreement type is {top['name']} "
                f"({top['deal_count']} deals)."
            ),
            "evidence_type": "deal_agreement_type",
            "evidence_deal_ids": top["evidence_deal_ids"],
        })
    if focus["partners"]:
        top = focus["partners"][0]
        statements.append({
            "claim": (
                f"The most frequent recorded counterparty is {top['name']} "
                f"({top['deal_count']} shared deals)."
            ),
            "evidence_type": "deal_company_links",
            "evidence_deal_ids": top["evidence_deal_ids"],
        })

    peers = _competitive_peers(
        session,
        company_id=company_id,
        years=years,
        focus=focus,
        limit=peer_limit,
    )
    entrants = _new_indication_entrants(
        session,
        company_id=company_id,
        indication_rows=focus["indications"],
        entrant_days=entrant_days,
    )
    return {
        "company": dict(company),
        "window": {
            "years": years,
            "first_deal_date": activity.pop("window_first_deal_date"),
            "last_deal_date": activity.pop("window_last_deal_date"),
        },
        "activity": {
            **activity,
            "momentum": momentum,
            "momentum_change_pct": momentum_change,
        },
        "strategy_statements": statements,
        "focus": focus,
        "competitive_map": peers,
        "new_indication_entrants": entrants,
        "methodology": {
            "strategy_scope": (
                "Observed Cortellis deal patterns only; statements do not infer "
                "management intent or unrecorded internal strategy."
            ),
            "competitive_map": (
                "Jaccard overlap across the subject's top recent indications, "
                "technologies, and assets. Peers may also be partners."
            ),
            "new_entrant": (
                "First observed dated Cortellis deal for a company in one of the "
                "subject's top three recent indications; not company founding or "
                "proof of first-ever market activity."
            ),
            "source": "cortellis_deals_api",
        },
    }

"""Evidence-bounded company asset, rights, and manufacturing intelligence."""

from __future__ import annotations

import html
import re
from typing import Any, Iterable, Mapping

from sqlalchemy import text


ONCOLOGY_TERMS = (
    "cancer",
    "oncolog",
    "tumor",
    "tumour",
    "carcinoma",
    "leukemia",
    "leukaemia",
    "lymphoma",
    "myeloma",
    "melanoma",
    "sarcoma",
    "neoplasm",
)

BIOLOGIC_TERMS = (
    "antibody",
    "biologic",
    "bispecific",
    "multispecific",
    "protein",
    "peptide",
    "vaccine",
    "cell therapy",
    "gene therapy",
    "viral",
    "oligonucleotide",
    "rna",
    "dna",
    "fusion",
    "conjugate",
)

LICENSE_TERMS = (
    "license",
    "licence",
    "licensing",
    "licencing",
    "out-license",
    "out-licence",
    "outlicens",
)

MANUFACTURING_TERMS = (
    "manufactur",
    "cdmo",
    "contract development",
    "supply",
)

MAX_COMPANY_DEALS = 5_000


def _list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in (value or [])]


def _joined_text(deal: Mapping[str, Any]) -> str:
    values = [
        deal.get("title"),
        deal.get("summary"),
        deal.get("deal_type"),
        deal.get("agreement_type"),
        deal.get("transaction_type"),
        deal.get("asset_type"),
        deal.get("therapy_area"),
    ]
    values.extend(item.get("name") for item in _list(deal.get("indications")))
    values.extend(item.get("name") for item in _list(deal.get("technologies")))
    return " | ".join(str(value) for value in values if value).casefold()


def _contains_any(value: str, terms: Iterable[str]) -> bool:
    return any(term in value for term in terms)


def _is_oncology(deal: Mapping[str, Any]) -> bool:
    therapy_and_indications = " | ".join(
        [str(deal.get("therapy_area") or "")]
        + [
            str(item.get("name") or "")
            for item in _list(deal.get("indications"))
        ]
    ).casefold()
    return _contains_any(therapy_and_indications, ONCOLOGY_TERMS)


def _is_biologic(deal: Mapping[str, Any]) -> bool:
    modality_text = " | ".join(
        [str(deal.get("asset_type") or "")]
        + [
            str(item.get("name") or "")
            for item in _list(deal.get("technologies"))
        ]
    ).casefold()
    return _contains_any(modality_text, BIOLOGIC_TERMS)


def _asset_biologic_assessment(
    drug: Mapping[str, Any], deal: Mapping[str, Any]
) -> tuple[bool, str]:
    molecule_types = [
        str(value).strip() for value in (drug.get("public_molecule_types") or [])
        if str(value).strip()
    ]
    normalized_types = " | ".join(molecule_types).casefold()
    public_biologic = _contains_any(normalized_types, BIOLOGIC_TERMS)
    if "small molecule" in normalized_types and not public_biologic:
        return False, "excluded_by_public_small_molecule_classification"
    if public_biologic:
        return True, "public_molecule_type_supported"
    if _is_biologic(deal):
        return True, "deal_level_biologic_tag_only"
    return False, "no_biologic_evidence"


def _source_citations(deal: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "source_id": source.get("source_id"),
            "source_type": source.get("source_type"),
        }
        for source in _list(deal.get("sources"))
    ]


def _plain_text(value: Any) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(html.unescape(without_tags).split())


def _deal_evidence(deal: Mapping[str, Any]) -> dict[str, Any]:
    summary = _plain_text(deal.get("summary"))
    return {
        "deal_id": int(deal["id"]),
        "title": deal.get("title"),
        "summary_excerpt": summary[:500] or None,
        "company_role": deal.get("company_role"),
        "deal_status": deal.get("status"),
        "agreement_type": deal.get("agreement_type"),
        "transaction_type": deal.get("transaction_type"),
        "date_start": deal.get("date_start"),
        "date_change_last": deal.get("date_change_last"),
        "source_citations": _source_citations(deal),
    }


def _territory_assessment(deal: Mapping[str, Any]) -> dict[str, Any]:
    territories = _list(deal.get("territories"))
    included = [
        item for item in territories
        if str(item.get("territory_type") or "").casefold() == "included"
    ]
    excluded = [
        item for item in territories
        if str(item.get("territory_type") or "").casefold() == "excluded"
    ]

    def is_us(item: Mapping[str, Any]) -> bool:
        identifier = str(item.get("id") or "").upper()
        name = str(item.get("name") or "").casefold()
        return identifier == "US" or name in {
            "united states",
            "united states of america",
            "usa",
        }

    def is_world(item: Mapping[str, Any]) -> bool:
        identifier = str(item.get("id") or "").upper()
        name = str(item.get("name") or "").casefold()
        return identifier in {"WO", "WW"} or any(
            token in name for token in ("world", "global")
        )

    world_included = any(is_world(item) for item in included)
    us_included = any(is_us(item) for item in included)
    us_excluded = any(is_us(item) for item in excluded)
    if us_excluded:
        us_scope = "explicitly_excluded"
    elif us_included:
        us_scope = "explicitly_included"
    elif world_included:
        us_scope = "included_via_worldwide_scope"
    else:
        us_scope = "not_observed"
    return {
        "included": included,
        "excluded": excluded,
        "us_scope_observed": us_scope,
        "global_scope_observed": (
            "worldwide_included" if world_included else "not_observed"
        ),
    }


def _portfolio(
    company: Mapping[str, Any], deals: list[Mapping[str, Any]]
) -> dict[str, Any]:
    assets: dict[int, dict[str, Any]] = {}
    for deal in deals:
        if not _is_oncology(deal):
            continue
        modalities = _list(deal.get("technologies"))
        indications = _list(deal.get("indications"))
        for drug in _list(deal.get("drugs")):
            is_biologic, biologic_basis = _asset_biologic_assessment(drug, deal)
            if not is_biologic:
                continue
            drug_id = int(drug["id"])
            asset = assets.setdefault(drug_id, {
                "drug_id": drug_id,
                "asset_name": drug.get("name_display"),
                "phase_highest_start": drug.get("phase_highest_start"),
                "phase_highest_now": drug.get("phase_highest_now"),
                "company_association_status": (
                    "deal_referenced_not_ownership_verified"
                ),
                "ownership_or_control_established": False,
                "biologic_classification_basis": biologic_basis,
                "public_molecule_types": list(
                    drug.get("public_molecule_types") or []
                ),
                "_modalities": {},
                "_indications": {},
                "evidence": [],
            })
            for modality in modalities:
                name = str(modality.get("name") or "").strip()
                if name:
                    asset["_modalities"].setdefault(name, set()).add(int(deal["id"]))
            for indication in indications:
                name = str(indication.get("name") or "").strip()
                if name:
                    asset["_indications"].setdefault(name, set()).add(int(deal["id"]))
            asset["evidence"].append(_deal_evidence(deal))

    result_assets = []
    for asset in sorted(assets.values(), key=lambda item: (
        str(item["asset_name"] or "").casefold(), item["drug_id"]
    )):
        asset["modalities"] = [
            {
                "name": name,
                "evidence_deal_ids": sorted(deal_ids),
                "attribution": "deal_level_tag",
            }
            for name, deal_ids in sorted(asset.pop("_modalities").items())
        ]
        asset["disease_indications"] = [
            {"name": name, "evidence_deal_ids": sorted(deal_ids)}
            for name, deal_ids in sorted(asset.pop("_indications").items())
        ]
        asset["evidence"].sort(key=lambda item: item["deal_id"])
        asset["deal_reference_count"] = len(asset["evidence"])
        result_assets.append(asset)
    return {
        "company": dict(company),
        "answer_scope": "oncology biologics referenced by this company's deals",
        "is_complete_standalone_company_pipeline": False,
        "asset_count": len(result_assets),
        "assets": result_assets,
        "limitations": [
            "This is a deal-referenced portfolio, not the separately licensed "
            "Cortellis Drugs or Companies product.",
            "A deal-to-asset link establishes relevance to the company-linked "
            "transaction, not ownership or control by that company.",
            "Modalities and indications are attached to the cited deal and may "
            "describe a multi-asset program rather than a uniquely asserted drug fact.",
            "A public small-molecule classification excludes that asset; otherwise "
            "biologic status can be limited to deal-level modality evidence.",
        ],
    }


def _rights(
    company: Mapping[str, Any],
    deals: list[Mapping[str, Any]],
    portfolio: Mapping[str, Any],
) -> dict[str, Any]:
    asset_results = {
        int(asset["drug_id"]): {
            "drug_id": int(asset["drug_id"]),
            "asset_name": asset.get("asset_name"),
            "license_or_option_event_observed": False,
            "out_license_observed": False,
            "us_or_global_scope_observed": False,
            "current_commercial_rights_loss_established": False,
            "rights_events": [],
        }
        for asset in portfolio["assets"]
    }
    program_events = []
    for deal in deals:
        combined = _joined_text(deal)
        if not _contains_any(combined, LICENSE_TERMS):
            continue
        role = str(deal.get("company_role") or "").casefold()
        direction = (
            "company_is_principal_in_license_deal"
            if role == "principal"
            else "company_is_partner_in_license_deal"
        )
        territory = _territory_assessment(deal)
        option_language = bool(deal.get("is_optional")) or "option" in combined
        exclusive_language = "exclusive" in combined
        explicit_out_license = any(
            term in combined
            for term in ("out-license", "out-licence", "outlicens")
        )
        if explicit_out_license:
            out_license_status = "explicitly_observed_in_deal_text"
        elif option_language:
            out_license_status = "option_or_license_scope_not_exercise_verified"
        elif role == "principal":
            out_license_status = "principal_license_event_direction_not_explicit"
        else:
            out_license_status = "not_observed"
        event = {
            "deal_id": int(deal["id"]),
            "observed_direction": direction,
            "license_or_option_event_observed": True,
            "out_license_observed": explicit_out_license,
            "out_license_status": out_license_status,
            "exclusive_scope_observed": exclusive_language,
            "option_or_contingent_scope_observed": option_language,
            "territory_scope": territory,
            "commercial_scope_constraint_observed": bool(
                role == "principal" and (exclusive_language or territory["included"])
            ),
            "current_commercial_rights_loss_established": False,
            "rights_conclusion": (
                "A license scope is observed in deal metadata; current legal "
                "ownership, option exercise, amendments, reversions, and loss of "
                "rights require current contract or legal verification."
            ),
            "partners": [
                participant for participant in _list(deal.get("participants"))
                if int(participant.get("id") or 0) != int(company["id"])
            ],
            "evidence": _deal_evidence(deal),
        }
        drugs = _list(deal.get("drugs"))
        attributed = False
        for drug in drugs:
            drug_id = int(drug["id"])
            asset = asset_results.get(drug_id)
            if asset is None:
                continue
            asset["rights_events"].append(event)
            asset["license_or_option_event_observed"] = True
            asset["out_license_observed"] |= event["out_license_observed"]
            asset["us_or_global_scope_observed"] |= (
                territory["us_scope_observed"] != "not_observed"
                or territory["global_scope_observed"] != "not_observed"
            )
            attributed = True
        if not attributed:
            program_events.append({
                **event,
                "attribution": "program_or_technology_level_no_named_portfolio_asset",
            })

    assets = sorted(asset_results.values(), key=lambda item: (
        str(item["asset_name"] or "").casefold(), item["drug_id"]
    ))
    return {
        "company": dict(company),
        "answer_scope": "license and territory events observed in company-linked deals",
        "assets": assets,
        "program_level_rights_events": program_events,
        "interpretation_rule": (
            "Included territory describes recorded deal scope; it is not treated "
            "as proof of present ownership or loss of commercial rights."
        ),
    }


def _manufacturing(
    company: Mapping[str, Any], deals: list[Mapping[str, Any]]
) -> dict[str, Any]:
    relationships = []
    explicit_us_pattern = re.compile(
        r"\b(?:manufactur(?:e|ed|ing)|production)\b.{0,100}"
        r"\b(?:in|at)\b.{0,60}\b(?:united states|u\.s\.)\b",
        re.IGNORECASE | re.DOTALL,
    )
    for deal in deals:
        combined = _joined_text(deal)
        if not _contains_any(combined, MANUFACTURING_TERMS):
            continue
        source_text = " | ".join(
            str(deal.get(field) or "") for field in ("title", "summary")
        )
        assets = [
            {
                "drug_id": int(drug["id"]),
                "asset_name": drug.get("name_display"),
            }
            for drug in _list(deal.get("drugs"))
        ]
        relationships.append({
            "deal_id": int(deal["id"]),
            "relationship_scope": "named_asset" if assets else "program_level",
            "assets": assets,
            "partners": [
                participant for participant in _list(deal.get("participants"))
                if int(participant.get("id") or 0) != int(company["id"])
            ],
            "us_manufacturing_status": (
                "explicitly_observed_in_source_text"
                if explicit_us_pattern.search(source_text)
                else "not_established"
            ),
            "location_interpretation": (
                "A partner name or deal territory is not treated as a manufacturing "
                "site. US status requires explicit source text identifying US work."
            ),
            "evidence": _deal_evidence(deal),
        })
    relationships.sort(key=lambda item: item["deal_id"])
    return {
        "company": dict(company),
        "answer_scope": "manufacturing, supply, CDMO, and development relationships",
        "relationship_count": len(relationships),
        "relationships": relationships,
    }


def build_company_asset_intelligence(
    company: Mapping[str, Any], deals: list[Mapping[str, Any]]
) -> dict[str, Any]:
    """Build all three colleague answers from source-backed deal rows."""
    normalized_company = dict(company)
    portfolio = _portfolio(normalized_company, deals)
    return {
        "company": normalized_company,
        "deal_records_considered": len(deals),
        "oncology_assets": portfolio,
        "asset_rights": _rights(normalized_company, deals, portfolio),
        "manufacturing_relationships": _manufacturing(normalized_company, deals),
    }


def company_asset_intelligence(session, company_id: int) -> dict[str, Any] | None:
    """Load bounded company deal evidence and assemble the governed answers."""
    company = session.execute(text("""
        SELECT id, name, company_type, hq_location
        FROM companies WHERE id = :company_id
    """), {"company_id": company_id}).mappings().one_or_none()
    if company is None:
        return None
    rows = session.execute(text("""
        SELECT deal.id, deal.title, deal.summary, deal.deal_type, deal.status,
               deal.is_optional, deal.agreement_type, deal.asset_type,
               deal.transaction_type, deal.phase_highest_start,
               deal.phase_highest_now, deal.date_start, deal.date_end,
               deal.date_change_last, company_deal.role AS company_role,
               therapy_area.name AS therapy_area,
               COALESCE((
                   SELECT jsonb_agg(jsonb_build_object(
                       'id', participant.id,
                       'name', participant.name,
                       'role', participant_link.role
                   ) ORDER BY participant_link.role, participant.name)
                   FROM deal_companies participant_link
                   JOIN companies participant
                     ON participant.id = participant_link.company_id
                   WHERE participant_link.deal_id = deal.id
               ), '[]'::jsonb) AS participants,
               COALESCE((
                   SELECT jsonb_agg(jsonb_build_object(
                       'id', drug.id,
                       'name_display', drug.name_display,
                       'phase_highest_start', drug.phase_highest_start,
                       'phase_highest_now', drug.phase_highest_now,
                       'public_molecule_types', ARRAY(
                           SELECT DISTINCT molecule_type
                           FROM (
                               SELECT chembl.molecule_type::text AS molecule_type
                               FROM drug_chembl_records chembl
                               WHERE chembl.drug_id = drug.id
                                 AND NULLIF(BTRIM(chembl.molecule_type), '')
                                     IS NOT NULL
                               UNION
                               SELECT profile.drug_type::text AS molecule_type
                               FROM public_drug_profiles profile
                               WHERE profile.drug_id = drug.id
                                 AND NULLIF(BTRIM(profile.drug_type), '')
                                     IS NOT NULL
                           ) public_types
                           ORDER BY molecule_type
                       )
                   ) ORDER BY drug.name_display, drug.id)
                   FROM deal_drugs drug_link
                   JOIN drugs drug ON drug.id = drug_link.drug_id
                   WHERE drug_link.deal_id = deal.id
               ), '[]'::jsonb) AS drugs,
               COALESCE((
                   SELECT jsonb_agg(jsonb_build_object(
                       'id', indication.id,
                       'name', indication.name,
                       'is_principal', indication_link.is_principal
                   ) ORDER BY indication_link.is_principal DESC, indication.name)
                   FROM deal_indications indication_link
                   JOIN indications indication
                     ON indication.id = indication_link.indication_id
                   WHERE indication_link.deal_id = deal.id
               ), '[]'::jsonb) AS indications,
               COALESCE((
                   SELECT jsonb_agg(jsonb_build_object(
                       'id', technology.id,
                       'name', technology.name,
                       'is_principal', technology_link.is_principal
                   ) ORDER BY technology_link.is_principal DESC, technology.name)
                   FROM deal_technologies technology_link
                   JOIN technologies technology
                     ON technology.id = technology_link.technology_id
                   WHERE technology_link.deal_id = deal.id
               ), '[]'::jsonb) AS technologies,
               COALESCE((
                   SELECT jsonb_agg(jsonb_build_object(
                       'id', territory.id,
                       'name', territory.name,
                       'territory_type', territory_link.territory_type
                   ) ORDER BY territory_link.territory_type, territory.name)
                   FROM deal_territories territory_link
                   JOIN territories territory
                     ON territory.id = territory_link.territory_id
                   WHERE territory_link.deal_id = deal.id
               ), '[]'::jsonb) AS territories,
               COALESCE((
                   SELECT jsonb_agg(jsonb_build_object(
                       'source_id', source.source_id,
                       'source_type', source.source_type
                   ) ORDER BY source.source_type, source.source_id)
                   FROM cortellis_deal_sources source
                   WHERE source.deal_id = deal.id AND source.is_current = TRUE
               ), '[]'::jsonb) AS sources
        FROM deal_companies company_deal
        JOIN deals deal ON deal.id = company_deal.deal_id
        LEFT JOIN therapy_areas therapy_area ON therapy_area.id = deal.therapy_area_id
        WHERE company_deal.company_id = :company_id
        ORDER BY deal.date_start DESC NULLS LAST, deal.id DESC
        LIMIT :limit
    """), {
        "company_id": company_id,
        "limit": MAX_COMPANY_DEALS + 1,
    }).mappings().all()
    truncated = len(rows) > MAX_COMPANY_DEALS
    deals = [dict(row) for row in rows[:MAX_COMPANY_DEALS]]
    result = build_company_asset_intelligence(dict(company), deals)
    result["scope_truncated"] = truncated
    result["deal_record_limit"] = MAX_COMPANY_DEALS
    return result

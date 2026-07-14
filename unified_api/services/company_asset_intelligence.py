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
MAX_PUBLIC_PIPELINE_TRIALS = 250
MAX_PUBLIC_INTERVENTION_CANDIDATES = 250
MAX_CONTRACT_ASSERTION_MATCHES_PER_TYPE = 3

CONTRACT_ASSERTION_PATTERNS = {
    "option_grant": {
        "regex": (
            r"option[[:space:]]+to[[:space:]]+"
            r"(obtain|acquire|receive).{0,100}(license|rights)|"
            r"grant(s|ed|ing)?.{0,60}option.{0,120}(license|rights)"
        ),
        "tsquery": "option & (acquire | license | rights)",
    },
    "option_exercise": {
        "regex": (
            r"(has|had)?[[:space:]]*exercised[[:space:]]+"
            r"(its[[:space:]]+|the[[:space:]]+|an[[:space:]]+)?option|"
            r"option.{0,40}(was|has been|had been)"
            r"[[:space:]]+exercised"
        ),
        "tsquery": "option & exercise",
    },
    "termination": {
        "regex": (
            r"(agreement|collaboration|deal).{0,80}"
            r"(was|has been|had been)[[:space:]]+terminated|"
            r"(party|company|licensor|licensee).{0,80}"
            r"terminated[[:space:]]+(the|this)[[:space:]]+agreement"
        ),
        "tsquery": "terminate & (agreement | collaboration | deal)",
    },
    "rights_reversion": {
        "regex": (
            r"(rights.{0,40}(were|have been)[[:space:]]+returned|"
            r"regained.{0,60}rights|rights.{0,40}reverted)"
        ),
        "tsquery": "rights & (return | regain | revert)",
    },
    "retained_rights": {
        "regex": (
            r"retained[[:space:]]+rights|"
            r"retain(ed|s|ing)?[[:space:]]+"
            r"(all|any|exclusive|commercialization|development)"
            r".{0,50}rights"
        ),
        "tsquery": "rights & retain",
    },
}


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


def _rights_evidence_checks(deal: Mapping[str, Any]) -> dict[str, Any]:
    """Report explicit rights assertions and honest local evidence coverage."""
    timeline = _list(deal.get("timeline"))
    contracts = _list(deal.get("contracts"))
    contract_assertions = _list(deal.get("contract_assertions"))
    patterns = {
        "option_grant": re.compile(
            r"\boption\b.{0,120}\b(?:acquire|license|rights)\b|"
            r"\bcollaboration and option agreement\b",
            re.IGNORECASE | re.DOTALL,
        ),
        "option_exercise": re.compile(
            r"\b(?:has|had)?\s*exercised\s+(?:its\s+|the\s+|an\s+)?option\b|"
            r"\boption\b.{0,40}\b(?:was|has been|had been) exercised\b|"
            r"\bexercise of (?:its\s+|the\s+|an\s+)?option\b",
            re.IGNORECASE | re.DOTALL,
        ),
        "amendment": re.compile(
            r"\b(?:amendment|amended|restated)\b",
            re.IGNORECASE,
        ),
        "termination": re.compile(
            r"\b(?:terminated|discontinued|cancelled|canceled)\b.{0,60}"
            r"\b(?:agreement|collaboration|deal|development|program|study)\b|"
            r"\b(?:agreement|collaboration|deal|development|program|study)\b"
            r".{0,60}\b(?:was |were )?(?:terminated|discontinued|cancelled|canceled)\b",
            re.IGNORECASE | re.DOTALL,
        ),
        "rights_reversion": re.compile(
            r"\b(?:revert(?:ed|s|ing)?|reversion|reacquir(?:e|ed|ing)|"
            r"regain(?:ed|s|ing)?|"
            r"rights (?:were )?returned|returned rights)\b",
            re.IGNORECASE,
        ),
        "retained_rights": re.compile(
            r"\b(?:retain(?:ed|s|ing)?|kept)\b.{0,80}\bright(?:s)?\b|"
            r"\brights\b.{0,80}\boutside the licensed region",
            re.IGNORECASE | re.DOTALL,
        ),
    }
    matches: list[dict[str, Any]] = []
    observed = {name: False for name in patterns}
    contract_language_observed = {name: False for name in patterns}
    for event in timeline:
        event_text = _plain_text(" ".join(str(event.get(field) or "") for field in (
            "event_type", "stage_notes", "summary"
        )))
        assertions = [
            name for name, pattern in patterns.items()
            if pattern.search(event_text)
        ]
        event_type = str(event.get("event_type") or "").casefold()
        if "option exercised" in event_type and "option_exercise" not in assertions:
            assertions.append("option_exercise")
        if (
            any(term in event_type for term in ("deal terminated", "termination"))
            and "termination" not in assertions
        ):
            assertions.append("termination")
        if not assertions:
            continue
        for assertion in assertions:
            observed[assertion] = True
        matches.append({
            "source": "cortellis_timeline",
            "timeline_event_id": event.get("id"),
            "event_date": event.get("event_date"),
            "event_type": event.get("event_type"),
            "assertions": assertions,
            "evidence_excerpt": event_text[:1000] or None,
        })

    for contract in contracts:
        contract_type = str(contract.get("contract_types") or "")
        metadata_assertions = []
        if re.search(r"\b(?:amendment|amended|restated)\b", contract_type, re.I):
            metadata_assertions.append("amendment")
        if re.search(r"\btermination agreement\b", contract_type, re.I):
            metadata_assertions.append("termination")
        if not metadata_assertions:
            continue
        for assertion in metadata_assertions:
            observed[assertion] = True
        matches.append({
            "source": "contract_metadata",
            "contract_id": contract.get("id"),
            "contract_types": contract.get("contract_types"),
            "contract_date": (
                contract.get("date_contract") or contract.get("date_filing")
            ),
            "assertions": metadata_assertions,
            "evidence_excerpt": None,
        })

    for assertion_match in contract_assertions:
        assertion = str(assertion_match.get("assertion") or "")
        if assertion not in contract_language_observed:
            continue
        contract_language_observed[assertion] = True
        matches.append({
            "source": "indexed_contract_candidate_text",
            "contract_content_id": assertion_match.get("contract_content_id"),
            "contract_id": assertion_match.get("contract_id"),
            "contract_types": assertion_match.get("contract_types"),
            "contract_date": (
                assertion_match.get("date_contract")
                or assertion_match.get("date_filing")
            ),
            "assertions": [assertion],
            "evidence_excerpt": _plain_text(
                assertion_match.get("evidence_excerpt")
            )[:1000] or None,
            "interpretation": (
                "Candidate clause language only; the affected party, asset, "
                "effective event, and current legal status require review."
            ),
        })

    indexed_contracts = sum(
        1 for contract in contracts if contract.get("has_indexed_content")
    )
    dates = [
        str(value)
        for value in [
            deal.get("date_change_last"),
            *(event.get("event_date") for event in timeline),
            *(
                contract.get("date_contract") or contract.get("date_filing")
                for contract in contracts
            ),
        ]
        if value
    ]
    latest_date = max(dates, default=None)
    follow_up_events = [
        event for event in timeline
        if str(event.get("event_type") or "").casefold() != "original deal"
    ]
    if observed["option_exercise"]:
        option_status = "explicitly_observed_in_available_timeline"
    elif contract_language_observed["option_exercise"]:
        option_status = "candidate_indexed_contract_language_requires_review"
    elif observed["option_grant"]:
        option_status = "not_observed_after_grant_in_available_local_records"
    elif contract_language_observed["option_grant"]:
        option_status = (
            "candidate_option_grant_language_no_exercise_event_observed"
        )
    else:
        option_status = "no_option_grant_observed"
    if indexed_contracts:
        verification_status = "partial_indexed_contract_and_timeline_evidence"
    elif contracts:
        verification_status = "partial_contract_metadata_without_indexed_text"
    elif timeline:
        verification_status = "timeline_only_no_contract_or_source_document_text"
    else:
        verification_status = "no_local_timeline_or_contract_evidence"
    return {
        "evidence_coverage": {
            "source_citation_count": len(_source_citations(deal)),
            "source_document_text_archived": False,
            "timeline_event_count": len(timeline),
            "follow_up_timeline_event_count": len(follow_up_events),
            "contract_metadata_count": len(contracts),
            "indexed_contract_text_count": indexed_contracts,
            "indexed_contract_assertion_match_count": len(contract_assertions),
            "contract_assertion_matches_per_type_limit": (
                MAX_CONTRACT_ASSERTION_MATCHES_PER_TYPE
            ),
            "latest_local_evidence_date": latest_date,
            "verification_status": verification_status,
        },
        "option_grant_observed": observed["option_grant"],
        "option_exercise_observed": observed["option_exercise"],
        "option_exercise_status": option_status,
        "amendment_observed": observed["amendment"],
        "termination_observed": observed["termination"],
        "rights_reversion_observed": observed["rights_reversion"],
        "retained_rights_observed": observed["retained_rights"],
        "indexed_contract_candidate_language_observed": (
            contract_language_observed
        ),
        "evidence_matches": matches,
        "current_legal_status_established": False,
        "methodology": (
            "Event assertions require explicit timeline evidence or unambiguous "
            "contract metadata. Indexed-contract text matches are candidate "
            "clauses for review and do not independently establish an effective "
            "event. Absence means not observed in available local evidence, not "
            "that an exercise, amendment, termination, or reversion never occurred."
        ),
    }


def _load_contract_assertions(
    session,
    deals: list[dict[str, Any]],
) -> None:
    """Attach bounded candidate clauses found in indexed contract text."""
    deal_ids = [
        int(deal["id"])
        for deal in deals
        if _contains_any(_joined_text(deal), LICENSE_TERMS)
        and any(
            contract.get("has_indexed_content")
            for contract in _list(deal.get("contracts"))
        )
    ]
    for deal in deals:
        deal["contract_assertions"] = []
    if not deal_ids:
        return

    values = []
    parameters: dict[str, Any] = {
        "deal_ids": deal_ids,
        "per_type_limit": MAX_CONTRACT_ASSERTION_MATCHES_PER_TYPE,
    }
    for index, (assertion, definition) in enumerate(
        CONTRACT_ASSERTION_PATTERNS.items()
    ):
        values.append(
            f"(:assertion_{index}, :regex_{index}, :tsquery_{index})"
        )
        parameters[f"assertion_{index}"] = assertion
        parameters[f"regex_{index}"] = definition["regex"]
        parameters[f"tsquery_{index}"] = definition["tsquery"]

    assertion_rows = session.execute(text(f"""
        WITH assertion_patterns(assertion, regex_pattern, tsquery_text) AS (
            VALUES {", ".join(values)}
        ), candidate_matches AS (
            SELECT content.id AS contract_content_id,
                   content.contract_id, content.deal_id,
                   contract.contract_types, contract.date_filing,
                   contract.date_contract, pattern.assertion,
                   regexp_instr(
                       content.content, pattern.regex_pattern, 1, 1, 0, 'i'
                   ) AS match_position,
                   content.content
            FROM contract_content content
            JOIN deal_contracts contract ON contract.id = content.contract_id
            CROSS JOIN assertion_patterns pattern
            WHERE content.deal_id = ANY(CAST(:deal_ids AS INTEGER[]))
              AND (
                  content.content_tsvector IS NULL
                  OR content.content_tsvector
                     @@ to_tsquery('english', pattern.tsquery_text)
              )
        ), ranked_matches AS (
            SELECT contract_content_id, contract_id, deal_id, contract_types,
                   date_filing, date_contract, assertion, match_position,
                   SUBSTRING(
                       content FROM GREATEST(match_position - 250, 1) FOR 1000
                   ) AS evidence_excerpt,
                   ROW_NUMBER() OVER (
                       PARTITION BY deal_id, assertion
                       ORDER BY date_contract DESC NULLS LAST,
                                date_filing DESC NULLS LAST,
                                contract_id
                   ) AS assertion_rank
            FROM candidate_matches
            WHERE match_position > 0
        )
        SELECT contract_content_id, contract_id, deal_id, contract_types,
               date_filing, date_contract, assertion, evidence_excerpt
        FROM ranked_matches
        WHERE assertion_rank <= :per_type_limit
        ORDER BY deal_id, assertion, assertion_rank
    """), parameters).mappings().all()
    by_deal = {int(deal["id"]): deal for deal in deals}
    for row in assertion_rows:
        by_deal[int(row["deal_id"])]["contract_assertions"].append(dict(row))


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


def _normalized_candidate_name(value: Any) -> str:
    return "".join(character for character in str(value or "").casefold()
                   if character.isalnum())


def _public_pipeline_observations(
    trials: list[Mapping[str, Any]],
    portfolio: Mapping[str, Any],
    *,
    total_linked_oncology_trials: int,
    trials_truncated: bool,
) -> dict[str, Any]:
    """Group source-backed trial interventions without asserting ownership."""
    deal_assets = {
        _normalized_candidate_name(asset.get("asset_name")): asset
        for asset in portfolio["assets"]
        if _normalized_candidate_name(asset.get("asset_name"))
    }
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    accepted_types = {"DRUG", "BIOLOGICAL", "GENETIC", "COMBINATION_PRODUCT"}
    for trial in trials:
        evidence = {
            "nct_id": trial.get("nct_id"),
            "brief_title": trial.get("brief_title"),
            "overall_status": trial.get("overall_status"),
            "phases": trial.get("phases") or [],
            "conditions": trial.get("conditions") or [],
            "lead_sponsor_name": trial.get("lead_sponsor_name"),
            "last_update_posted": trial.get("last_update_posted"),
            "source_url": trial.get("source_url"),
            "company_relationships": _list(trial.get("company_relationships")),
        }
        for intervention in _list(trial.get("interventions")):
            name = str(intervention.get("name") or "").strip()
            intervention_type = str(intervention.get("type") or "").upper()
            normalized = _normalized_candidate_name(name)
            if not name or not normalized or intervention_type not in accepted_types:
                continue
            key = (normalized, intervention_type)
            matched_asset = deal_assets.get(normalized)
            candidate = candidates.setdefault(key, {
                "intervention_name": name,
                "intervention_type": intervention_type,
                "company_association_status": (
                    "trial_referenced_not_ownership_verified"
                ),
                "ownership_or_control_established": False,
                "matches_deal_referenced_asset": matched_asset is not None,
                "matched_drug_id": (
                    matched_asset.get("drug_id") if matched_asset else None
                ),
                "trial_evidence": [],
            })
            if not any(
                item["nct_id"] == evidence["nct_id"]
                for item in candidate["trial_evidence"]
            ):
                candidate["trial_evidence"].append(evidence)

    all_candidates = sorted(candidates.values(), key=lambda item: (
        item["intervention_name"].casefold(), item["intervention_type"]
    ))
    for candidate in all_candidates:
        candidate["trial_evidence"].sort(
            key=lambda item: str(item["nct_id"] or "")
        )
        candidate["linked_trial_count"] = len(candidate["trial_evidence"])
    returned = all_candidates[:MAX_PUBLIC_INTERVENTION_CANDIDATES]
    return {
        "source": "clinicaltrials_gov",
        "relationship_basis": (
            "normalized-exact company alias in a structured sponsor or "
            "collaborator field"
        ),
        "is_complete_standalone_company_pipeline": False,
        "linked_oncology_trial_count": total_linked_oncology_trials,
        "returned_trial_count": len(trials),
        "trials_truncated": trials_truncated,
        "intervention_candidate_count_in_returned_trials": len(all_candidates),
        "returned_intervention_candidate_count": len(returned),
        "intervention_candidates_truncated": len(returned) < len(all_candidates),
        "intervention_candidates": returned,
        "limitations": [
            "Trial interventions include combinations and comparators and are not "
            "asserted to be company-owned pipeline assets.",
            "Only exact structured company links and oncology-condition trials are "
            "included; absence is not proof that the company has no other pipeline.",
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
            for term in ("out-licens", "out-licenc", "outlicens")
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
            "document_checks": _rights_evidence_checks(deal),
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
    company: Mapping[str, Any],
    deals: list[Mapping[str, Any]],
    *,
    public_trials: list[Mapping[str, Any]] | None = None,
    total_linked_oncology_trials: int = 0,
    public_trials_truncated: bool = False,
) -> dict[str, Any]:
    """Build all three colleague answers from source-backed deal rows."""
    normalized_company = dict(company)
    portfolio = _portfolio(normalized_company, deals)
    public_pipeline = _public_pipeline_observations(
        public_trials or [],
        portfolio,
        total_linked_oncology_trials=total_linked_oncology_trials,
        trials_truncated=public_trials_truncated,
    )
    public_pipeline["detail_endpoint_hint"] = (
        f"/api/v1/clinical-trials?company_id={normalized_company['id']}&limit=100"
    )
    portfolio["public_pipeline_observations"] = public_pipeline
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
               ), '[]'::jsonb) AS sources,
               COALESCE((
                   SELECT jsonb_agg(jsonb_build_object(
                       'id', event.id,
                       'event_date', event.event_date,
                       'event_type', event.event_type,
                       'stage', event.stage,
                       'stage_notes', event.stage_notes,
                       'summary', event.summary
                   ) ORDER BY event.event_date, event.id)
                   FROM deal_timeline_events event
                   WHERE event.deal_id = deal.id
               ), '[]'::jsonb) AS timeline,
               COALESCE((
                   SELECT jsonb_agg(jsonb_build_object(
                       'id', contract.id,
                       'contract_types', contract.contract_types,
                       'date_filing', contract.date_filing,
                       'date_contract', contract.date_contract,
                       'has_pdf', contract.has_pdf,
                       'has_text', contract.has_text,
                       'is_redacted', contract.is_redacted,
                       'has_indexed_content', EXISTS (
                           SELECT 1 FROM contract_content content
                           WHERE content.contract_id = contract.id
                       )
                   ) ORDER BY contract.date_contract, contract.id)
                   FROM deal_contracts contract
                   WHERE contract.deal_id = deal.id
               ), '[]'::jsonb) AS contracts
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
    _load_contract_assertions(session, deals)
    oncology_pattern = "|".join(ONCOLOGY_TERMS)
    trial_rows = session.execute(text("""
        SELECT trial.nct_id, trial.brief_title, trial.overall_status,
               trial.phases, trial.conditions, trial.interventions,
               trial.lead_sponsor_name, trial.last_update_posted,
               trial.source_url,
               COUNT(*) OVER () AS linked_oncology_trial_total,
               COALESCE((
                   SELECT jsonb_agg(jsonb_build_object(
                       'organization_name', company_link.organization_name,
                       'organization_role', company_link.organization_role,
                       'matched_alias', company_link.matched_alias,
                       'match_method', company_link.match_method,
                       'confidence', company_link.confidence,
                       'source', company_link.source
                   ) ORDER BY company_link.organization_role,
                              company_link.organization_name)
                   FROM clinical_trial_companies company_link
                   WHERE company_link.nct_id = trial.nct_id
                     AND company_link.company_id = :company_id
               ), '[]'::jsonb) AS company_relationships
        FROM clinical_trials trial
        WHERE EXISTS (
            SELECT 1 FROM clinical_trial_companies company_link
            WHERE company_link.nct_id = trial.nct_id
              AND company_link.company_id = :company_id
        )
          AND LOWER(trial.conditions::text) ~ :oncology_pattern
        ORDER BY trial.last_update_posted DESC NULLS LAST, trial.nct_id
        LIMIT :trial_limit
    """), {
        "company_id": company_id,
        "oncology_pattern": oncology_pattern,
        "trial_limit": MAX_PUBLIC_PIPELINE_TRIALS + 1,
    }).mappings().all()
    total_linked_trials = int(
        trial_rows[0]["linked_oncology_trial_total"] if trial_rows else 0
    )
    public_trials_truncated = len(trial_rows) > MAX_PUBLIC_PIPELINE_TRIALS
    public_trials = [
        dict(row) for row in trial_rows[:MAX_PUBLIC_PIPELINE_TRIALS]
    ]
    result = build_company_asset_intelligence(
        dict(company),
        deals,
        public_trials=public_trials,
        total_linked_oncology_trials=total_linked_trials,
        public_trials_truncated=public_trials_truncated,
    )
    result["scope_truncated"] = truncated
    result["deal_record_limit"] = MAX_COMPANY_DEALS
    return result

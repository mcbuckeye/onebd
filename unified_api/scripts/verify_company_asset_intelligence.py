"""Deterministic production acceptance checks for company asset intelligence."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from sqlalchemy import text

from unified_api.services.company_asset_intelligence import (
    company_asset_intelligence,
)
from unified_api.services.database import get_cortellis_session


HANCHOR_BIO_ID = 1_319_537
DOTBIO_ID = 1_186_341
SANOFI_ID = 1_009_547
DOTBIO_CS_2012_ID = 200_067


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _named(items: Iterable[Mapping[str, Any]], field: str, name: str) -> dict:
    for item in items:
        if str(item.get(field) or "").casefold() == name.casefold():
            return dict(item)
    raise RuntimeError(f"Expected {field}={name!r} was not returned")


def verify_company_asset_intelligence(session) -> dict[str, Any]:
    """Return a compact proof summary or raise on a semantic regression."""
    hanchor = company_asset_intelligence(session, HANCHOR_BIO_ID)
    dotbio = company_asset_intelligence(session, DOTBIO_ID)
    sanofi = company_asset_intelligence(session, SANOFI_ID)
    _require(hanchor is not None, "Hanchor Bio company record is missing")
    _require(dotbio is not None, "DotBio company record is missing")
    _require(sanofi is not None, "Sanofi company record is missing")

    hcb = _named(hanchor["asset_rights"]["assets"], "asset_name", "HCB-101")
    hcb_event = hcb["rights_events"][0]
    hcb_checks = hcb_event["document_checks"]
    _require(hcb_event["out_license_observed"], "HCB-101 out-license not observed")
    _require(
        hcb_checks["retained_rights_observed"],
        "HCB-101 retained-rights statement not observed",
    )
    _require(
        not hcb_checks["option_exercise_observed"],
        "HCB-101 incorrectly reports option exercise",
    )
    wuxi = _named(
        hanchor["manufacturing_relationships"]["relationships"],
        "deal_id",
        "483450",
    )
    _require(
        wuxi["us_manufacturing_status"] == "not_established",
        "WuXi relationship incorrectly establishes a US manufacturing site",
    )

    cs_2012 = _named(
        dotbio["asset_rights"]["assets"], "asset_name", "CS-2012"
    )
    cs_event = cs_2012["rights_events"][0]
    cs_checks = cs_event["document_checks"]
    _require(cs_checks["option_grant_observed"], "CS-2012 option grant is missing")
    _require(
        not cs_checks["option_exercise_observed"],
        "CS-2012 incorrectly reports option exercise",
    )
    _require(
        not cs_event["out_license_observed"],
        "CS-2012 option is incorrectly reported as an exercised out-license",
    )
    db_007_relationship = next(
        (
            relationship
            for relationship in dotbio["manufacturing_relationships"][
                "relationships"
            ]
            if any(
                asset.get("asset_name") == "DB-007"
                for asset in relationship["assets"]
            )
        ),
        None,
    )
    _require(db_007_relationship is not None, "DB-007 manufacturing record is missing")
    _require(
        db_007_relationship["us_manufacturing_status"] == "not_established",
        "DB-007 relationship incorrectly establishes a US manufacturing site",
    )

    public_pipeline = sanofi["oncology_assets"]["public_pipeline_observations"]
    _require(
        public_pipeline["linked_oncology_trial_count"] > 0,
        "Sanofi has no linked public oncology trials",
    )
    _require(
        public_pipeline["returned_intervention_candidate_count"] > 0,
        "Sanofi has no public oncology intervention candidates",
    )
    _require(
        all(
            not candidate["ownership_or_control_established"]
            for candidate in public_pipeline["intervention_candidates"]
        ),
        "A trial intervention was incorrectly presented as ownership evidence",
    )

    collision_guard = dict(session.execute(text("""
        SELECT
            (SELECT status FROM drug_public_enrichment_state
             WHERE drug_id = :drug_id AND source = 'pubchem') AS pubchem_status,
            (SELECT COUNT(*) FROM drug_identifiers
             WHERE drug_id = :drug_id AND source = 'pubchem') AS identifiers,
            (SELECT COUNT(*) FROM public_drug_profiles
             WHERE drug_id = :drug_id) AS profiles,
            (SELECT COUNT(*) FROM public_drug_target_links
             WHERE drug_id = :drug_id) AS target_links,
            (SELECT COUNT(*) FROM public_drug_disease_links
             WHERE drug_id = :drug_id) AS disease_links,
            (SELECT COUNT(*) FROM public_drug_source_state
             WHERE drug_id = :drug_id) AS public_source_states
    """), {"drug_id": DOTBIO_CS_2012_ID}).mappings().one())
    _require(
        collision_guard["pubchem_status"] == "context_conflict",
        "CS-2012 PubChem collision is not quarantined",
    )
    for field in (
        "identifiers",
        "profiles",
        "target_links",
        "disease_links",
        "public_source_states",
    ):
        _require(
            int(collision_guard[field]) == 0,
            f"CS-2012 retains unexpected public enrichment data: {field}",
        )

    return {
        "status": "passed",
        "hanchor_bio": {
            "company_id": HANCHOR_BIO_ID,
            "asset": "HCB-101",
            "out_license_observed": True,
            "retained_rights_observed": True,
            "wuxi_us_manufacturing_status": wuxi["us_manufacturing_status"],
        },
        "dotbio": {
            "company_id": DOTBIO_ID,
            "asset": "CS-2012",
            "option_grant_observed": True,
            "option_exercise_observed": False,
            "db_007_us_manufacturing_status": db_007_relationship[
                "us_manufacturing_status"
            ],
            "pubchem_collision_guard": collision_guard,
        },
        "public_pipeline": {
            "company_id": SANOFI_ID,
            "linked_oncology_trial_count": public_pipeline[
                "linked_oncology_trial_count"
            ],
            "returned_intervention_candidate_count": public_pipeline[
                "returned_intervention_candidate_count"
            ],
            "ownership_claims": 0,
        },
    }


def main() -> int:
    with get_cortellis_session() as session:
        result = verify_company_asset_intelligence(session)
    print(json.dumps(result, indent=2, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

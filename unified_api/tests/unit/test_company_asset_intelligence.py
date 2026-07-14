"""Business-user acceptance cases for company asset intelligence."""

from unified_api.services.company_asset_intelligence import (
    build_company_asset_intelligence,
)


def _deal(**overrides):
    deal = {
        "id": 1,
        "title": "Example deal",
        "summary": None,
        "deal_type": None,
        "status": "Active",
        "is_optional": False,
        "agreement_type": None,
        "asset_type": None,
        "transaction_type": None,
        "date_start": "2026-01-01",
        "date_change_last": "2026-01-01",
        "company_role": "Principal",
        "therapy_area": "Cancer",
        "participants": [],
        "drugs": [],
        "indications": [{"id": 1, "name": "Cancer"}],
        "technologies": [{"id": 1, "name": "Antibody"}],
        "territories": [],
        "sources": [{"source_id": "100", "source_type": "Press Release"}],
        "timeline": [],
        "contracts": [],
        "contract_assertions": [],
    }
    deal.update(overrides)
    return deal


def test_hanchor_portfolio_rights_and_program_manufacturing_are_evidence_bounded():
    company = {"id": 1319537, "name": "HanchorBio Inc"}
    deals = [
        _deal(
            id=438561,
            title=(
                "HanchorBio signed an exclusive out-licensing agreement for "
                "HCB-101 with Henlius"
            ),
            agreement_type="Development/Commercialization License",
            transaction_type="Out-licensing",
            participants=[
                {"id": 1319537, "name": "HanchorBio Inc", "role": "Principal"},
                {"id": 22, "name": "Shanghai Henlius", "role": "Partner"},
            ],
            drugs=[{
                "id": 190001,
                "name_display": "HCB-101",
                "phase_highest_start": "Preclinical",
                "phase_highest_now": "Phase I",
            }],
            technologies=[
                {"id": 1, "name": "Biological"},
                {"id": 2, "name": "Protein fusion"},
            ],
            territories=[{
                "id": "CN",
                "name": "China",
                "territory_type": "Included",
            }],
            timeline=[{
                "id": 1,
                "event_date": "2025-07-01",
                "event_type": "Original Deal",
                "stage_notes": None,
                "summary": (
                    "<para>HanchorBio would retain all rights outside the "
                    "licensed regions.</para>"
                ),
            }],
        ),
        _deal(
            id=483450,
            title="WuXi Biologics provides integrated manufacturing services",
            agreement_type="Manufacturing/Supply",
            participants=[
                {"id": 1319537, "name": "HanchorBio Inc", "role": "Principal"},
                {"id": 23, "name": "WuXi Biologics", "role": "Partner"},
            ],
            drugs=[],
            indications=[],
            technologies=[],
            therapy_area=None,
        ),
    ]

    result = build_company_asset_intelligence(company, deals)
    portfolio = result["oncology_assets"]
    rights = result["asset_rights"]["assets"][0]
    manufacturing = result["manufacturing_relationships"]["relationships"][0]

    assert [asset["asset_name"] for asset in portfolio["assets"]] == ["HCB-101"]
    assert {item["name"] for item in portfolio["assets"][0]["modalities"]} == {
        "Biological",
        "Protein fusion",
    }
    assert portfolio["assets"][0]["ownership_or_control_established"] is False
    assert portfolio["assets"][0]["company_association_status"] == (
        "deal_referenced_not_ownership_verified"
    )
    assert rights["out_license_observed"] is True
    assert rights["rights_events"][0]["territory_scope"]["us_scope_observed"] == (
        "not_observed"
    )
    assert rights["current_commercial_rights_loss_established"] is False
    checks = rights["rights_events"][0]["document_checks"]
    assert checks["retained_rights_observed"] is True
    assert checks["option_exercise_observed"] is False
    assert checks["evidence_coverage"]["verification_status"] == (
        "timeline_only_no_contract_or_source_document_text"
    )
    assert manufacturing["relationship_scope"] == "program_level"
    assert manufacturing["partners"][0]["name"] == "WuXi Biologics"
    assert manufacturing["us_manufacturing_status"] == "not_established"


def test_dotbio_worldwide_option_and_usa_named_partner_do_not_overstate_rights_or_site():
    company = {"id": 1186341, "name": "DotBio Pte Ltd"}
    deals = [
        _deal(
            id=306435,
            title="DotBio and CStone collaborate with option and license",
            agreement_type="Development/Commercialization License",
            transaction_type="Collaboration (Shared responsibilities)",
            is_optional=True,
            participants=[
                {"id": 1186341, "name": "DotBio Pte Ltd", "role": "Principal"},
                {"id": 30, "name": "CStone", "role": "Partner"},
            ],
            drugs=[{
                "id": 200067,
                "name_display": "CS-2012",
                "phase_highest_start": "Preclinical",
                "phase_highest_now": "Preclinical",
            }],
            technologies=[
                {"id": 1, "name": "Antibody"},
                {"id": 2, "name": "Multispecific"},
            ],
            territories=[{
                "id": "WO",
                "name": "World",
                "territory_type": "Included",
            }],
            timeline=[{
                "id": 2,
                "event_date": "2021-11-09",
                "event_type": "Original Deal",
                "stage_notes": None,
                "summary": (
                    "CStone entered a collaboration and option agreement and "
                    "has an option to acquire worldwide rights to the molecules."
                ),
            }],
        ),
        _deal(
            id=478283,
            title="Bora Biologics / Tanvex BioPharma USA manufactures DB-007",
            agreement_type="Manufacturing/Supply",
            participants=[
                {"id": 1186341, "name": "DotBio Pte Ltd", "role": "Principal"},
                {"id": 31, "name": "Tanvex BioPharma USA", "role": "Partner"},
            ],
            drugs=[{
                "id": 200068,
                "name_display": "DB-007",
                "phase_highest_start": "Preclinical",
                "phase_highest_now": "Preclinical",
            }],
            technologies=[
                {"id": 1, "name": "Antibody"},
                {"id": 3, "name": "Trispecific"},
            ],
        ),
    ]

    result = build_company_asset_intelligence(company, deals)
    assets = {
        item["asset_name"]: item for item in result["asset_rights"]["assets"]
    }
    cs_event = assets["CS-2012"]["rights_events"][0]
    manufacturing = result["manufacturing_relationships"]["relationships"][0]

    assert cs_event["territory_scope"]["global_scope_observed"] == (
        "worldwide_included"
    )
    assert cs_event["territory_scope"]["us_scope_observed"] == (
        "included_via_worldwide_scope"
    )
    assert cs_event["option_or_contingent_scope_observed"] is True
    assert cs_event["out_license_observed"] is False
    assert cs_event["out_license_status"] == (
        "option_or_license_scope_not_exercise_verified"
    )
    assert cs_event["current_commercial_rights_loss_established"] is False
    checks = cs_event["document_checks"]
    assert checks["option_grant_observed"] is True
    assert checks["option_exercise_observed"] is False
    assert checks["option_exercise_status"] == (
        "not_observed_after_grant_in_available_local_records"
    )
    assert manufacturing["assets"][0]["asset_name"] == "DB-007"
    assert manufacturing["partners"][0]["name"] == "Tanvex BioPharma USA"
    assert manufacturing["us_manufacturing_status"] == "not_established"


def test_non_oncology_asset_is_not_presented_as_oncology_portfolio():
    company = {"id": 1, "name": "Example"}
    deal = _deal(
        therapy_area="Ophthalmology",
        indications=[{"id": 2, "name": "Retinal disease"}],
        drugs=[{"id": 2, "name_display": "RET-1"}],
    )

    result = build_company_asset_intelligence(company, [deal])

    assert result["oncology_assets"]["assets"] == []


def test_public_small_molecule_type_overrides_multi_asset_deal_biologic_tag():
    company = {"id": 1, "name": "Example"}
    deal = _deal(
        drugs=[
            {
                "id": 1,
                "name_display": "BIO-1",
                "public_molecule_types": [],
            },
            {
                "id": 2,
                "name_display": "SM-2",
                "public_molecule_types": ["Small molecule"],
            },
        ],
        technologies=[{"id": 1, "name": "Antibody"}],
    )

    result = build_company_asset_intelligence(company, [deal])

    assert [
        asset["asset_name"] for asset in result["oncology_assets"]["assets"]
    ] == ["BIO-1"]
    assert result["oncology_assets"]["assets"][0][
        "biologic_classification_basis"
    ] == "deal_level_biologic_tag_only"


def test_follow_up_timeline_explicitly_reports_option_exercise_and_amendment():
    company = {"id": 1, "name": "Example"}
    deal = _deal(
        agreement_type="Development/Commercialization License",
        is_optional=True,
        title="Example option and license",
        drugs=[{"id": 7, "name_display": "BIO-7"}],
        timeline=[
            {
                "id": 1,
                "event_date": "2020-01-01",
                "event_type": "Original Deal",
                "summary": "Partner received an option to acquire global rights.",
            },
            {
                "id": 2,
                "event_date": "2022-01-01",
                "event_type": "Amendment",
                "summary": "Partner exercised the option under the amended agreement.",
            },
        ],
        contracts=[{"id": 10, "has_indexed_content": True}],
    )

    result = build_company_asset_intelligence(company, [deal])
    checks = result["asset_rights"]["assets"][0]["rights_events"][0][
        "document_checks"
    ]

    assert checks["option_exercise_observed"] is True
    assert checks["option_exercise_status"] == (
        "explicitly_observed_in_available_timeline"
    )
    assert checks["amendment_observed"] is True
    assert checks["evidence_coverage"]["follow_up_timeline_event_count"] == 1
    assert checks["evidence_coverage"]["indexed_contract_text_count"] == 1


def test_public_trial_interventions_expand_portfolio_without_claiming_ownership():
    company = {"id": 1, "name": "Example"}
    deal = _deal(drugs=[{"id": 1, "name_display": "BIO-1"}])
    trials = [{
        "nct_id": "NCT00000001",
        "brief_title": "Oncology combination study",
        "overall_status": "RECRUITING",
        "phases": ["PHASE1"],
        "conditions": ["Solid Tumor"],
        "interventions": [
            {"name": "BIO-1", "type": "DRUG"},
            {"name": "NOVEL-2", "type": "BIOLOGICAL"},
            {"name": "Tumor biopsy", "type": "PROCEDURE"},
        ],
        "lead_sponsor_name": "Example",
        "last_update_posted": "2026-01-01",
        "source_url": "https://clinicaltrials.gov/study/NCT00000001",
        "company_relationships": [{
            "organization_name": "Example",
            "organization_role": "LEAD_SPONSOR",
            "match_method": "normalized_exact",
            "confidence": 1.0,
        }],
    }]

    result = build_company_asset_intelligence(
        company,
        [deal],
        public_trials=trials,
        total_linked_oncology_trials=1,
    )
    public = result["oncology_assets"]["public_pipeline_observations"]
    candidates = {
        item["intervention_name"]: item
        for item in public["intervention_candidates"]
    }

    assert public["source"] == "clinicaltrials_gov"
    assert public["linked_oncology_trial_count"] == 1
    assert public["intervention_candidate_count_in_returned_trials"] == 2
    assert set(candidates) == {"BIO-1", "NOVEL-2"}
    assert candidates["BIO-1"]["matches_deal_referenced_asset"] is True
    assert candidates["BIO-1"]["matched_drug_id"] == 1
    assert candidates["NOVEL-2"]["matches_deal_referenced_asset"] is False
    assert candidates["NOVEL-2"]["ownership_or_control_established"] is False
    assert public["detail_endpoint_hint"].endswith("company_id=1&limit=100")


def test_conditional_option_language_is_not_exercise_and_reversion_is_explicit():
    company = {"id": 1, "name": "Example"}
    deal = _deal(
        agreement_type="License",
        title="Example license with option",
        drugs=[{"id": 8, "name_display": "BIO-8"}],
        timeline=[
            {
                "id": 1,
                "event_date": "2020-01-01",
                "event_type": "Original Deal",
                "summary": (
                    "Partner would pay a fee if it does not exercise its option "
                    "to acquire worldwide rights."
                ),
            },
            {
                "id": 2,
                "event_date": "2024-01-01",
                "event_type": "Deal Terminated",
                "summary": (
                    "The collaboration was terminated and Licensor regained "
                    "worldwide rights."
                ),
            },
        ],
    )

    result = build_company_asset_intelligence(company, [deal])
    checks = result["asset_rights"]["assets"][0]["rights_events"][0][
        "document_checks"
    ]

    assert checks["option_exercise_observed"] is False
    assert checks["termination_observed"] is True
    assert checks["rights_reversion_observed"] is True


def test_indexed_contract_assertion_is_attributed_without_claiming_current_status():
    company = {"id": 1, "name": "Example"}
    deal = _deal(
        agreement_type="License",
        title="Example license with option",
        drugs=[{"id": 9, "name_display": "BIO-9"}],
        contracts=[{
            "id": 11,
            "contract_types": "License Agreement",
            "date_contract": "2020-01-01",
            "has_indexed_content": True,
        }],
        contract_assertions=[{
            "assertion": "option_exercise",
            "contract_content_id": 101,
            "contract_id": 11,
            "contract_types": "License Agreement",
            "date_contract": "2020-01-01",
            "evidence_excerpt": (
                "The licensee has exercised its option for the licensed product."
            ),
        }],
    )

    result = build_company_asset_intelligence(company, [deal])
    checks = result["asset_rights"]["assets"][0]["rights_events"][0][
        "document_checks"
    ]

    assert checks["option_exercise_observed"] is False
    assert checks["option_exercise_status"] == (
        "candidate_indexed_contract_language_requires_review"
    )
    assert checks["current_legal_status_established"] is False
    assert checks["evidence_coverage"][
        "indexed_contract_assertion_match_count"
    ] == 1
    assert any(
        match["source"] == "indexed_contract_candidate_text"
        for match in checks["evidence_matches"]
    )

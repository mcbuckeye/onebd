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
    }
    deal.update(overrides)
    return deal


def test_hanchor_portfolio_rights_and_program_manufacturing_are_evidence_bounded():
    company = {"id": 1319537, "name": "HanchorBio Inc"}
    deals = [
        _deal(
            id=438561,
            title="HanchorBio exclusively out-licenses HCB-101 to Henlius",
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
            transaction_type="Out-licensing",
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

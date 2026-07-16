"""Deal-phase derivation and archived-response repair tests."""

from unittest.mock import Mock

from src.deal_phases import (
    derive_deal_phases,
    derive_deal_phases_from_xml,
    derive_drug_phases,
    derive_drug_phases_from_xml,
    select_highest_phase,
)
from src.models import Drug
from src.sync import DealTransformer


def test_select_highest_development_phase_across_assets():
    assert select_highest_phase([
        ("Preclinical", "PC"),
        ("Phase 2 Clinical", "C2"),
        ("Phase 1 Clinical", "C1"),
    ]) == "Phase 2 Clinical"


def test_active_phase_sorts_above_terminal_status_but_terminal_is_preserved():
    assert select_highest_phase([
        ("Discontinued", "DX"),
        ("Phase 1 Clinical", "C1"),
    ]) == "Phase 1 Clinical"
    assert select_highest_phase([("Discontinued", "DX")]) == "Discontinued"


def test_derive_deal_phases_from_parsed_expanded_record():
    parsed = {
        "Drugs": {
            "Drug": [
                {
                    "PhaseHighestStart": {
                        "@attributes": {"id": "C1"},
                        "@text": "Phase 1 Clinical",
                    },
                    "PhaseHighestNow": {
                        "@attributes": {"id": "C2"},
                        "@text": "Phase 2 Clinical",
                    },
                },
                {
                    "PhaseHighestStart": {
                        "@attributes": {"id": "PC"},
                        "@text": "Preclinical",
                    },
                    "PhaseHighestNow": {
                        "@attributes": {"id": "C3"},
                        "@text": "Phase 3 Clinical",
                    },
                },
            ]
        }
    }

    assert derive_deal_phases(parsed) == (
        "Phase 1 Clinical",
        "Phase 3 Clinical",
    )


def test_derive_deal_phases_from_archived_xml_with_namespace():
    xml = """
    <Deal xmlns="urn:cortellis" id="42">
      <Drugs>
        <Drug id="1">
          <PhaseHighestStart id="C2">Phase 2 Clinical</PhaseHighestStart>
          <PhaseHighestNow id="C3">Phase 3 Clinical</PhaseHighestNow>
        </Drug>
      </Drugs>
    </Deal>
    """

    assert derive_deal_phases_from_xml(xml) == (
        "Phase 2 Clinical",
        "Phase 3 Clinical",
    )


def test_per_drug_phase_derivation_preserves_no_development_reported():
    parsed = {
        "Drugs": {"Drug": [{
            "@attributes": {"id": "120606"},
            "DrugNameDisplay": "DB-002",
            "PhaseHighestStart": {
                "@attributes": {"id": "PC"},
                "@text": "Preclinical",
            },
            "PhaseHighestNow": {
                "@attributes": {"id": "NDR"},
                "@text": "No Development Reported",
            },
        }]},
    }

    assert derive_drug_phases(parsed) == [{
        "drug_id": 120606,
        "name": "DB-002",
        "phase_highest_start": "Preclinical",
        "phase_highest_start_id": "PC",
        "phase_highest_now": "No Development Reported",
        "phase_highest_now_id": "NDR",
    }]


def test_per_drug_phase_derivation_from_archive_xml():
    xml = """
    <Deal id="264960"><Drugs><Drug id="120606">
      <DrugNameDisplay>DB-002</DrugNameDisplay>
      <PhaseHighestStart id="PC">Preclinical</PhaseHighestStart>
      <PhaseHighestNow id="NDR">No Development Reported</PhaseHighestNow>
    </Drug></Drugs></Deal>
    """

    assert derive_drug_phases_from_xml(xml)[0]["phase_highest_now"] == (
        "No Development Reported"
    )


def test_existing_drug_is_refreshed_from_later_expanded_response():
    transformer = DealTransformer.__new__(DealTransformer)
    drug = Drug(
        id=120606,
        name_display="DB-002",
        phase_highest_start="Preclinical",
        phase_highest_now="Preclinical",
    )
    transformer.session = Mock()
    transformer._drug_cache = {drug.id: drug}

    refreshed = transformer.get_or_create_drug(
        drug.id,
        "DB-002",
        phase_start="Preclinical",
        phase_now="No Development Reported",
    )

    assert refreshed is drug
    assert refreshed.phase_highest_now == "No Development Reported"

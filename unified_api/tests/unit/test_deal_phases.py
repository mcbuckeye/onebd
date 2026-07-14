"""Deal-phase derivation and archived-response repair tests."""

from src.deal_phases import (
    derive_deal_phases,
    derive_deal_phases_from_xml,
    select_highest_phase,
)


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

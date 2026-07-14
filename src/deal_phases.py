"""Deterministic phase-at-deal derivation from Cortellis expanded records."""

from __future__ import annotations

from typing import Any, Iterable, Optional
from xml.etree import ElementTree as ET


# Cortellis development-stage IDs observed in the expanded-deal API. Terminal
# statuses deliberately sort below active development stages: when a deal has
# several assets, "highest" should describe the furthest active asset. If every
# asset is terminal, the first terminal status is retained rather than erased.
PHASE_RANK_BY_ID = {
    "NDR": 0,
    "DR": 10,
    "PC": 20,
    "CU": 25,
    "C1": 30,
    "C2": 40,
    "C3": 50,
    "PR": 60,
    "R": 70,
    "L": 80,
    "DX": -10,
    "S": -10,
    "W": -10,
}

PHASE_RANK_BY_NAME = {
    "no development reported": 0,
    "discovery": 10,
    "preclinical": 20,
    "clinical": 25,
    "phase 1 clinical": 30,
    "phase 2 clinical": 40,
    "phase 3 clinical": 50,
    "pre-registration": 60,
    "registered": 70,
    "launched": 80,
    "discontinued": -10,
    "suspended": -10,
    "withdrawn": -10,
}


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("@text") or "").strip()
    return ""


def _phase_id(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    attributes = value.get("@attributes")
    if not isinstance(attributes, dict):
        return ""
    return str(attributes.get("id") or "").strip().upper()


def select_highest_phase(
    phases: Iterable[tuple[str, Optional[str]]],
) -> Optional[str]:
    """Return the furthest development phase with stable terminal fallback."""
    candidates = [
        (str(name).strip(), str(phase_id or "").strip().upper())
        for name, phase_id in phases
        if str(name or "").strip()
    ]
    if not candidates:
        return None

    def rank(candidate: tuple[str, str]) -> tuple[int, str]:
        name, phase_id = candidate
        value = PHASE_RANK_BY_ID.get(
            phase_id,
            PHASE_RANK_BY_NAME.get(name.lower(), -20),
        )
        return value, name.lower()

    return max(candidates, key=rank)[0]


def derive_deal_phases(parsed_data: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Aggregate per-drug Cortellis fields into deal-level highest phases."""
    drugs_container = parsed_data.get("Drugs")
    if not isinstance(drugs_container, dict):
        return None, None
    drugs = drugs_container.get("Drug") or []
    if isinstance(drugs, dict):
        drugs = [drugs]
    if not isinstance(drugs, list):
        return None, None

    starts: list[tuple[str, Optional[str]]] = []
    currents: list[tuple[str, Optional[str]]] = []
    for drug in drugs:
        if not isinstance(drug, dict):
            continue
        start = drug.get("PhaseHighestStart")
        current = drug.get("PhaseHighestNow")
        if _text(start):
            starts.append((_text(start), _phase_id(start)))
        if _text(current):
            currents.append((_text(current), _phase_id(current)))
    return select_highest_phase(starts), select_highest_phase(currents)


def derive_deal_phases_from_xml(
    response_body: str,
) -> tuple[Optional[str], Optional[str]]:
    """Read phase fields directly from an archived expanded-deal XML body."""
    root = ET.fromstring(response_body)
    starts: list[tuple[str, Optional[str]]] = []
    currents: list[tuple[str, Optional[str]]] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        value = (element.text or "").strip()
        if not value:
            continue
        phase = (value, element.attrib.get("id"))
        if tag == "PhaseHighestStart":
            starts.append(phase)
        elif tag == "PhaseHighestNow":
            currents.append(phase)
    return select_highest_phase(starts), select_highest_phase(currents)

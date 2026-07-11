"""Tests for the executable question-evaluation harness."""

from unified_api.scripts.evaluate_questions import evaluate_assertion, get_path


def test_get_path_handles_nested_lists():
    payload = {"data": [{"deal_count": 23}]}

    assert get_path(payload, "data.0.deal_count") == 23
    assert get_path([{"doc_type": "8-K"}], "$root")[0]["doc_type"] == "8-K"


def test_collection_assertions():
    payload = {"deals": [
        {"modality": "Bispecific antibody"},
        {"modality": "Bispecific T-cell engager antibody"},
    ]}

    passed, _ = evaluate_assertion(payload, {
        "type": "all_contains",
        "path": "deals",
        "field": "modality",
        "value": "bispecific",
    })
    assert passed


def test_excludes_detects_unsupported_claims():
    passed, _ = evaluate_assertion(
        {"answer": "No supporting records were found."},
        {"type": "excludes", "path": "answer", "value": "Historically"},
    )

    assert passed

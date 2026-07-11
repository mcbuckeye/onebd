"""Tests for the versioned question and database-truth evaluator."""

from decimal import Decimal

from unified_api.scripts.evaluate_questions import (
    _validate_read_only_query,
    evaluate_truth_assertion,
    validate_suite,
)


def test_truth_rows_compare_only_declared_fields():
    passed, _ = evaluate_truth_assertion(
        {"data": [{"id": 1, "count": 2, "narrative": "ignored"}]},
        {"rows": [{"id": 1, "count": Decimal("2")}]},
        {
            "type": "rows_equal",
            "response_path": "data",
            "truth_path": "rows",
            "fields": ["id", "count"],
        },
    )

    assert passed


def test_truth_query_validation_rejects_mutation_and_multiple_statements():
    assert _validate_read_only_query("SELECT COUNT(*) FROM deals")
    assert _validate_read_only_query("WITH counts AS (SELECT 1) SELECT * FROM counts")
    assert not _validate_read_only_query("DELETE FROM deals")
    assert not _validate_read_only_query("SELECT 1; DROP TABLE deals")


def test_strong_case_requires_database_truth():
    suite = {
        "cases": [
            {
                "id": case_id,
                "tier": "regression" if case_id <= 5 else "catalog",
                "rating": "strong" if case_id == 1 else "partial",
                "question": f"Question {case_id}",
                "request": {"method": "GET", "path": "/api/health"},
                "assertions": [{"type": "equals", "path": "status", "value": "ok"}],
            }
            for case_id in range(1, 66)
        ]
    }

    assert "case #1: strong cases require database truth assertions" in validate_suite(suite)

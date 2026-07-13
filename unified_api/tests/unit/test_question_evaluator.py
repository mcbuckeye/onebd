"""Tests for the versioned question and database-truth evaluator."""

from decimal import Decimal

from unified_api.scripts.evaluate_questions import (
    _validate_read_only_query,
    evaluate_rubric,
    evaluate_truth_assertion,
    truth_values_equal,
    validate_suite,
)


def test_truth_numeric_comparison_tolerates_json_transport_encoding():
    assert truth_values_equal(204.4571580327864, Decimal("204.45715803278648"))
    assert truth_values_equal("55.76", Decimal("55.76"))
    assert not truth_values_equal("55.76", Decimal("55.77"))


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


def test_evidence_rubric_accepts_grounded_traceable_response():
    payload = {
        "answer": "The answer is supported by Cortellis record [C1].",
        "data": [{"id": 42, "value": 10}],
        "citations": [{"id": "C1", "record_id": 42}],
        "confidence": {"evidence_status": "grounded", "sample_size": 1},
        "sql_query": "SELECT id, value FROM deals WHERE id = 42",
    }
    rubric = {
        "minimum_score": 10,
        "checks": [
            {"type": "answer_quality", "weight": 2},
            {"type": "evidence_alignment", "weight": 3},
            {"type": "citation_traceability", "weight": 2},
            {"type": "sample_size_consistency", "weight": 1},
            {"type": "sql_read_only", "weight": 2},
        ],
    }

    passed, detail = evaluate_rubric(payload, rubric)

    assert passed
    assert "10/10" in detail


def test_evidence_rubric_rejects_untraceable_grounded_claim():
    payload = {
        "answer": "This answer makes a claim without its citation marker.",
        "data": [{"id": 42}],
        "citations": [{"id": "C1", "record_id": 99}],
        "confidence": {"evidence_status": "grounded", "sample_size": 2},
        "sql_query": "DELETE FROM deals",
    }
    rubric = {
        "minimum_score": 8,
        "checks": [
            {"type": "answer_quality", "weight": 2},
            {"type": "evidence_alignment", "weight": 3},
            {"type": "citation_traceability", "weight": 2},
            {"type": "sample_size_consistency", "weight": 1},
            {"type": "sql_read_only", "weight": 2},
        ],
    }

    passed, detail = evaluate_rubric(payload, rubric)

    assert not passed
    assert "citation traceability" in detail
    assert "unsafe" in detail


def test_non_truth_case_requires_scored_rubric():
    suite = {
        "cases": [
            {
                "id": case_id,
                "tier": "regression" if case_id <= 5 else "catalog",
                "rating": "partial",
                "question": f"Question {case_id}",
                "request": {"method": "GET", "path": "/api/health"},
                "assertions": [{"type": "equals", "path": "status", "value": "ok"}],
                "rubric": {
                    "minimum_score": 1,
                    "checks": [
                        {
                            "type": "assertion",
                            "assertion": {
                                "type": "equals",
                                "path": "status",
                                "value": "ok",
                            },
                        }
                    ],
                },
            }
            for case_id in range(1, 66)
        ]
    }
    suite["cases"][5].pop("rubric")

    assert "case #6: requires database truth or a scored rubric" in validate_suite(suite)

"""Run versioned question-evaluation fixtures against a deployed OneBD API."""

from __future__ import annotations

import argparse
from datetime import date, datetime
from decimal import Decimal
import math
from pathlib import Path
import re
from typing import Any

import httpx
import yaml


DEFAULT_CASES = Path(__file__).parents[1] / "evals" / "question_cases.yaml"
VALID_TIERS = {"regression", "catalog"}
VALID_RATINGS = {"strong", "partial", "needs_work", "cannot"}
VALID_TRUTH_SOURCES = {"cortellis", "edgar"}
VALID_RUBRIC_CHECKS = {
    "assertion",
    "answer_quality",
    "citation_traceability",
    "evidence_alignment",
    "sample_size_consistency",
    "sql_read_only",
}


def get_path(payload: Any, path: str) -> Any:
    """Resolve a simple dotted path with numeric list indexes."""
    if path == "$root":
        return payload
    current = payload
    for part in path.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return current


def evaluate_assertion(payload: Any, assertion: dict) -> tuple[bool, str]:
    """Evaluate one declarative assertion and return a useful failure message."""
    actual = get_path(payload, assertion["path"])
    expected = assertion.get("value")
    kind = assertion["type"]

    if kind == "equals":
        passed = actual == expected
    elif kind == "contains":
        passed = str(expected).lower() in str(actual).lower()
    elif kind == "excludes":
        passed = str(expected).lower() not in str(actual).lower()
    elif kind == "min_length":
        passed = len(actual) >= int(expected)
    elif kind in {"all_equal", "all_contains"}:
        field = assertion["field"]
        if kind == "all_equal":
            passed = bool(actual) and all(item.get(field) == expected for item in actual)
        else:
            passed = bool(actual) and all(
                str(expected).lower() in str(item.get(field) or "").lower()
                for item in actual
            )
    else:
        raise ValueError(f"Unknown assertion type: {kind}")

    return passed, f"{assertion['path']} {kind} {expected!r}; actual={actual!r}"


def _json_value(value: Any) -> Any:
    """Normalize database values to the representation returned by FastAPI."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _comparison_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    if isinstance(value, str) and re.fullmatch(
        r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?",
        value,
    ):
        return float(value)
    return None


def truth_values_equal(actual: Any, expected: Any) -> bool:
    """Compare JSON/SQL values while tolerating transport numeric encoding."""
    actual_number = _comparison_number(actual)
    expected_number = _comparison_number(expected)
    if actual_number is not None and expected_number is not None:
        return math.isclose(actual_number, expected_number, rel_tol=1e-12, abs_tol=1e-9)
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            truth_values_equal(left, right)
            for left, right in zip(actual, expected)
        )
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            truth_values_equal(actual[key], expected[key]) for key in actual
        )
    return actual == expected


def evaluate_truth_assertion(
    payload: Any,
    truth_payload: dict,
    assertion: dict,
) -> tuple[bool, str]:
    """Compare an API response value with independently queried database truth."""
    actual = _json_value(get_path(payload, assertion["response_path"]))
    expected = _json_value(get_path(truth_payload, assertion["truth_path"]))
    kind = assertion["type"]

    if kind == "equals":
        passed = truth_values_equal(actual, expected)
    elif kind == "rows_equal":
        fields = assertion["fields"]
        actual = [{field: row.get(field) for field in fields} for row in actual]
        expected = [{field: row.get(field) for field in fields} for row in expected]
        passed = truth_values_equal(actual, expected)
    else:
        raise ValueError(f"Unknown truth assertion type: {kind}")

    return passed, f"database truth {kind}; expected={expected!r}; actual={actual!r}"


def _answer_quality(payload: dict, check: dict) -> tuple[bool, str]:
    answer = str(payload.get("answer") or "").strip()
    minimum = int(check.get("minimum_characters", 40))
    forbidden = [
        phrase.lower()
        for phrase in check.get(
            "forbidden_phrases",
            ["encountered an error", "traceback", "internal server error"],
        )
    ]
    passed = len(answer) >= minimum and not any(
        phrase in answer.lower() for phrase in forbidden
    )
    return passed, (
        f"answer quality: length={len(answer)}, minimum={minimum}, "
        f"forbidden_matches={[p for p in forbidden if p in answer.lower()]}"
    )


def _evidence_alignment(payload: dict, _check: dict) -> tuple[bool, str]:
    data = payload.get("data") or []
    citations = payload.get("citations") or []
    confidence = payload.get("confidence") or {}
    status = confidence.get("evidence_status")
    if data:
        passed = status == "grounded" and bool(citations)
    else:
        passed = status in {"insufficient", "unsupported"} and not citations
    return passed, (
        f"evidence alignment: data={len(data)}, citations={len(citations)}, "
        f"status={status!r}"
    )


def _citation_traceability(payload: dict, _check: dict) -> tuple[bool, str]:
    answer = str(payload.get("answer") or "")
    citations = payload.get("citations") or []
    data = payload.get("data") or []
    data_ids = {
        str(row.get("id"))
        for row in data
        if isinstance(row, dict) and row.get("id") is not None
    }
    failures = []
    for citation in citations:
        citation_id = str(citation.get("id") or "")
        record_id = citation.get("record_id") or citation.get("deal_id")
        if citation_id and f"[{citation_id}]" not in answer:
            failures.append(f"{citation_id} absent from answer")
        if record_id is not None and data_ids and str(record_id) not in data_ids:
            failures.append(f"record {record_id} absent from returned data")
    return not failures, f"citation traceability: {failures or 'ok'}"


def _sample_size_consistency(payload: dict, _check: dict) -> tuple[bool, str]:
    data = payload.get("data") or []
    sample_size = (payload.get("confidence") or {}).get("sample_size")
    passed = sample_size == len(data)
    return passed, f"sample size: declared={sample_size!r}, returned={len(data)}"


def _sql_read_only(payload: dict, _check: dict) -> tuple[bool, str]:
    query = payload.get("sql_query")
    passed = query is None or _validate_read_only_query(query)
    return passed, f"SQL is {'absent/read-only' if passed else 'unsafe'}"


def evaluate_rubric(payload: Any, rubric: dict) -> tuple[bool, str]:
    """Score a deterministic evidence rubric for narrative/API responses."""
    score = 0
    possible = 0
    failed_checks = []
    for check in rubric.get("checks") or []:
        weight = int(check.get("weight", 1))
        possible += weight
        kind = check["type"]
        if kind == "assertion":
            passed, detail = evaluate_assertion(payload, check["assertion"])
        elif kind == "answer_quality":
            passed, detail = _answer_quality(payload, check)
        elif kind == "evidence_alignment":
            passed, detail = _evidence_alignment(payload, check)
        elif kind == "citation_traceability":
            passed, detail = _citation_traceability(payload, check)
        elif kind == "sample_size_consistency":
            passed, detail = _sample_size_consistency(payload, check)
        elif kind == "sql_read_only":
            passed, detail = _sql_read_only(payload, check)
        else:
            raise ValueError(f"Unknown rubric check type: {kind}")
        if passed:
            score += weight
        else:
            failed_checks.append(f"{check.get('name', kind)}: {detail}")

    minimum = int(rubric["minimum_score"])
    passed = score >= minimum
    detail = f"rubric score {score}/{possible} (minimum {minimum})"
    if failed_checks:
        detail += "; " + "; ".join(failed_checks)
    return passed, detail


def run_case(client: httpx.Client, case: dict, *, with_truth: bool = False) -> list[str]:
    """Execute a case and return assertion failure messages."""
    request = case["request"]
    try:
        response = client.request(
            request["method"],
            request["path"],
            params=request.get("params"),
            json=request.get("json"),
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.RequestError as exc:
        return [f"transport error: {type(exc).__name__}: {exc}"]
    except httpx.HTTPStatusError as exc:
        return [f"HTTP error: {exc.response.status_code}: {exc}"]
    except ValueError as exc:
        return [f"response JSON error: {exc}"]
    failures = []
    for assertion in case.get("assertions", []):
        try:
            passed, detail = evaluate_assertion(payload, assertion)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            failures.append(f"assertion error: {exc}")
            continue
        if not passed:
            failures.append(detail)

    if case.get("rubric"):
        try:
            passed, detail = evaluate_rubric(payload, case["rubric"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            failures.append(f"rubric error: {exc}")
        else:
            if not passed:
                failures.append(detail)

    if with_truth and case.get("truth"):
        truth = case["truth"]
        from sqlalchemy import text
        from unified_api.services.database import (
            get_cortellis_session,
            get_edgar_source_session,
        )

        session_context = (
            get_cortellis_session
            if truth["source"] == "cortellis"
            else get_edgar_source_session
        )
        with session_context() as session:
            rows = session.execute(
                text(truth["query"]),
                truth.get("params") or {},
            ).mappings().all()
        truth_payload = {"rows": [dict(row) for row in rows]}
        for assertion in truth["assertions"]:
            try:
                passed, detail = evaluate_truth_assertion(
                    payload,
                    truth_payload,
                    assertion,
                )
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                failures.append(f"truth assertion error: {exc}")
                continue
            if not passed:
                failures.append(detail)
    return failures


def _validate_read_only_query(query: str) -> bool:
    """Allow one SELECT/CTE statement and reject data-changing SQL."""
    normalized = query.strip().rstrip(";").strip()
    if not re.match(r"^(SELECT|WITH)\b", normalized, flags=re.IGNORECASE):
        return False
    if ";" in normalized:
        return False
    return not re.search(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|CALL|COPY)\b",
        normalized,
        flags=re.IGNORECASE,
    )


def validate_suite(suite: dict) -> list[str]:
    """Validate that the versioned catalog covers every evaluation question."""
    errors = []
    cases = suite.get("cases") or []
    ids = [case.get("id") for case in cases]
    expected_ids = list(range(1, 66))
    if sorted(ids) != expected_ids:
        errors.append(f"case IDs must be exactly 1..65; got {sorted(ids)}")

    for case in cases:
        label = f"case #{case.get('id')}"
        if case.get("tier") not in VALID_TIERS:
            errors.append(f"{label}: tier must be one of {sorted(VALID_TIERS)}")
        if case.get("rating") not in VALID_RATINGS:
            errors.append(f"{label}: rating must be one of {sorted(VALID_RATINGS)}")
        if not case.get("question"):
            errors.append(f"{label}: question is required")
        request = case.get("request") or {}
        if request.get("method") not in {"GET", "POST"} or not request.get("path"):
            errors.append(f"{label}: executable request method/path is required")
        if not case.get("assertions"):
            errors.append(f"{label}: at least one assertion is required")
        truth = case.get("truth")
        rubric = case.get("rubric")
        if case.get("rating") == "strong" and not truth:
            errors.append(f"{label}: strong cases require database truth assertions")
        if not truth and not rubric:
            errors.append(f"{label}: requires database truth or a scored rubric")
        if truth:
            if truth.get("source") not in VALID_TRUTH_SOURCES:
                errors.append(
                    f"{label}: truth source must be one of {sorted(VALID_TRUTH_SOURCES)}"
                )
            if not _validate_read_only_query(truth.get("query") or ""):
                errors.append(f"{label}: truth query must be one read-only SELECT/CTE")
            if not truth.get("assertions"):
                errors.append(f"{label}: truth assertions are required")
            for assertion in truth.get("assertions") or []:
                if assertion.get("type") not in {"equals", "rows_equal"}:
                    errors.append(f"{label}: invalid truth assertion type")
                if not assertion.get("response_path") or not assertion.get("truth_path"):
                    errors.append(f"{label}: truth response_path/truth_path are required")
                if assertion.get("type") == "rows_equal" and not assertion.get("fields"):
                    errors.append(f"{label}: rows_equal requires fields")
        if rubric:
            checks = rubric.get("checks") or []
            if not checks:
                errors.append(f"{label}: rubric checks are required")
            possible = 0
            for check in checks:
                check_type = check.get("type")
                if check_type not in VALID_RUBRIC_CHECKS:
                    errors.append(f"{label}: invalid rubric check type {check_type!r}")
                weight = check.get("weight", 1)
                if not isinstance(weight, int) or weight <= 0:
                    errors.append(f"{label}: rubric weights must be positive integers")
                else:
                    possible += weight
                if check_type == "assertion" and not check.get("assertion"):
                    errors.append(f"{label}: assertion rubric check requires assertion")
            minimum = rubric.get("minimum_score")
            if not isinstance(minimum, int) or minimum <= 0 or minimum > possible:
                errors.append(
                    f"{label}: rubric minimum_score must be between 1 and {possible}"
                )

    regression_count = sum(case.get("tier") == "regression" for case in cases)
    if regression_count < 5:
        errors.append("at least five deterministic regression cases are required")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://onebd.pchomelab.com")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--request-retries",
        type=int,
        default=0,
        help="Retry only transport-level request failures this many times",
    )
    parser.add_argument(
        "--tier",
        choices=["regression", "catalog", "all"],
        default="regression",
    )
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--with-truth",
        action="store_true",
        help="Execute direct read-only database truth comparisons for selected cases",
    )
    args = parser.parse_args()
    if args.request_retries < 0:
        parser.error("--request-retries must be zero or greater")

    suite = yaml.safe_load(args.cases.read_text())
    validation_errors = validate_suite(suite)
    if validation_errors:
        for error in validation_errors:
            print(f"INVALID {error}")
        return 2
    if args.validate_only:
        print(f"VALID {len(suite['cases'])} executable cases")
        return 0

    selected = [
        case for case in suite["cases"]
        if args.tier == "all" or case["tier"] == args.tier
    ]
    failed = 0
    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        for case in selected:
            label = f"#{case['id']} {case['question']}"
            for attempt in range(args.request_retries + 1):
                failures = run_case(client, case, with_truth=args.with_truth)
                transport_failure = (
                    failures and all(
                        failure.startswith("transport error:") for failure in failures
                    )
                )
                if transport_failure and attempt < args.request_retries:
                    print(
                        f"RETRY {label} after {failures[0]} "
                        f"({attempt + 1}/{args.request_retries})",
                        flush=True,
                    )
                    continue
                break
            if failures:
                failed += 1
                print(f"FAIL {label}", flush=True)
                for failure in failures:
                    print(f"  - {failure}", flush=True)
            else:
                print(f"PASS {label}", flush=True)

    total = len(selected)
    print(f"\n{total - failed}/{total} cases passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

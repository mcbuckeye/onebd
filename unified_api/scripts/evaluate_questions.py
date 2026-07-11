"""Run versioned question-evaluation fixtures against a deployed OneBD API."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import httpx
import yaml


DEFAULT_CASES = Path(__file__).parents[1] / "evals" / "question_cases.yaml"


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


def run_case(client: httpx.Client, case: dict) -> list[str]:
    """Execute a case and return assertion failure messages."""
    request = case["request"]
    response = client.request(
        request["method"],
        request["path"],
        params=request.get("params"),
        json=request.get("json"),
    )
    response.raise_for_status()
    payload = response.json()
    failures = []
    for assertion in case.get("assertions", []):
        try:
            passed, detail = evaluate_assertion(payload, assertion)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            failures.append(f"assertion error: {exc}")
            continue
        if not passed:
            failures.append(detail)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://onebd.pchomelab.com")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    suite = yaml.safe_load(args.cases.read_text())
    failed = 0
    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        for case in suite["cases"]:
            failures = run_case(client, case)
            label = f"#{case['id']} {case['question']}"
            if failures:
                failed += 1
                print(f"FAIL {label}")
                for failure in failures:
                    print(f"  - {failure}")
            else:
                print(f"PASS {label}")

    total = len(suite["cases"])
    print(f"\n{total - failed}/{total} cases passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

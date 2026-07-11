"""Run reproducible latency smoke budgets against a deployed EDGAR search API."""

from __future__ import annotations

import argparse
import time

import httpx


CASES = [
    ("common filtered full-text", {"query": "agreement", "mode": "fulltext", "doc_type": "8-K", "limit": 5}, 2.0),
    ("specific full-text", {"query": "bispecific antibody", "mode": "fulltext", "limit": 5}, 2.0),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://onebd.pchomelab.com")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    failed = 0
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        for name, params, budget in CASES:
            durations = []
            result_count = 0
            for _ in range(max(1, args.runs)):
                started = time.perf_counter()
                response = client.get("/api/edgar/search", params=params)
                response.raise_for_status()
                durations.append(time.perf_counter() - started)
                result_count = len(response.json())
            worst = max(durations)
            passed = result_count > 0 and worst <= budget
            failed += not passed
            print(
                f"{'PASS' if passed else 'FAIL'} {name}: "
                f"worst={worst:.3f}s budget={budget:.1f}s results={result_count}"
            )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

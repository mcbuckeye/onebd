"""Run reproducible latency smoke budgets against deployed search APIs."""

from __future__ import annotations

import argparse
import time

import httpx


CASES = [
    (
        "common filtered EDGAR full-text",
        "/api/edgar/search",
        {"query": "agreement", "mode": "fulltext", "doc_type": "8-K", "limit": 5},
        2.0,
        1,
        None,
    ),
    (
        "specific EDGAR full-text",
        "/api/edgar/search",
        {"query": "bispecific antibody", "mode": "fulltext", "limit": 5},
        2.0,
        1,
        None,
    ),
    (
        "broad unified cross-source full-text",
        "/api/search/unified",
        {"query": "agreement", "mode": "fulltext", "sources": "both", "limit": 20},
        5.0,
        2,
        1,
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://onebd.pchomelab.com")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    failed = 0
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        for name, path, params, budget, minimum_sources, maximum_imbalance in CASES:
            durations = []
            result_count = 0
            source_count = 0
            source_counts: dict[str, int] = {}
            for _ in range(max(1, args.runs)):
                started = time.perf_counter()
                response = client.get(path, params=params)
                response.raise_for_status()
                durations.append(time.perf_counter() - started)
                payload = response.json()
                results = payload.get("results", []) if isinstance(payload, dict) else payload
                result_count = len(results)
                source_counts = {}
                for item in results:
                    if isinstance(item, dict):
                        source = item.get("source", "edgar")
                        source_counts[source] = source_counts.get(source, 0) + 1
                source_count = len(source_counts)
            worst = max(durations)
            imbalance = (
                max(source_counts.values()) - min(source_counts.values())
                if source_counts else 0
            )
            passed = (
                result_count > 0
                and source_count >= minimum_sources
                and worst <= budget
                and (
                    maximum_imbalance is None
                    or imbalance <= maximum_imbalance
                )
            )
            failed += not passed
            print(
                f"{'PASS' if passed else 'FAIL'} {name}: "
                f"worst={worst:.3f}s budget={budget:.1f}s "
                f"results={result_count} sources={source_counts}"
            )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

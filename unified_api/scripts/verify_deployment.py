"""Verify that production serves an expected immutable image commit.

The command also tells GitHub Actions whether an automatic application
rollback is safe.  A response from the origin proves that the deployment path
is reachable; transport failures such as Cloudflare Tunnel error 530 do not.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any, Callable
import urllib.error
import urllib.request


CLOUDFLARE_TUNNEL_UNAVAILABLE = 530


@dataclass(frozen=True)
class DeploymentVerification:
    verified: bool
    rollback_safe: bool
    attempts: int
    last_response: dict[str, Any] | None


def wait_for_expected_commit(
    url: str,
    expected_sha: str,
    *,
    attempts: int = 90,
    delay_seconds: float = 10,
    timeout_seconds: float = 15,
    open_url: Callable[..., Any] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> DeploymentVerification:
    """Poll ``url`` and classify whether a failed check is safe to roll back."""
    saw_origin_response = False
    last: dict[str, Any] | None = None

    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "OneBD-Deployment-Verifier/1.0 admin@pchomelab.com",
                    "Accept": "application/json",
                },
            )
            with open_url(request, timeout=timeout_seconds) as response:
                payload = json.load(response)
            saw_origin_response = True
            last = payload if isinstance(payload, dict) else {"payload": payload}
            if last.get("status") == "healthy" and last.get("commit") == expected_sha:
                print(f"Dokploy is serving {expected_sha}")
                return DeploymentVerification(True, True, attempt, last)
        except urllib.error.HTTPError as exc:
            # Cloudflare returns 530 when no tunnel connector is available.
            # Changing application code cannot repair that external path.
            origin_reached = exc.code != CLOUDFLARE_TUNNEL_UNAVAILABLE
            saw_origin_response = saw_origin_response or origin_reached
            last = {
                "error": f"HTTP {exc.code}",
                "origin_reached": origin_reached,
            }
        except Exception as exc:  # noqa: BLE001 - transport diagnostics are data
            last = {"error": str(exc), "origin_reached": False}

        print(f"Waiting for deployment ({attempt}/{attempts}): {last}")
        if attempt < attempts:
            sleep(delay_seconds)

    return DeploymentVerification(False, saw_origin_response, attempts, last)


def _write_github_output(path: str | None, rollback_safe: bool) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as output:
        output.write(f"rollback_safe={'true' if rollback_safe else 'false'}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--github-output")
    parser.add_argument("--attempts", type=int, default=90)
    parser.add_argument("--delay-seconds", type=float, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=15)
    args = parser.parse_args()

    result = wait_for_expected_commit(
        args.base_url.rstrip("/") + "/api/health",
        args.expected_sha,
        attempts=args.attempts,
        delay_seconds=args.delay_seconds,
        timeout_seconds=args.timeout_seconds,
    )
    _write_github_output(args.github_output, result.rollback_safe)
    if result.verified:
        return 0

    print(
        f"Dokploy did not serve healthy commit {args.expected_sha}; "
        f"last response={result.last_response}"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

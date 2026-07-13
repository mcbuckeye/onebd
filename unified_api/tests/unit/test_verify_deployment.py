import io
import json
import urllib.error

from unified_api.scripts.verify_deployment import wait_for_expected_commit


class _JsonResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _response(payload):
    return _JsonResponse(json.dumps(payload).encode())


def test_expected_commit_is_verified_and_safe_to_roll_back():
    result = wait_for_expected_commit(
        "https://example.test/api/health",
        "a" * 40,
        attempts=1,
        open_url=lambda *_args, **_kwargs: _response(
            {"status": "healthy", "commit": "a" * 40}
        ),
    )

    assert result.verified is True
    assert result.rollback_safe is True
    assert result.attempts == 1


def test_cloudflare_tunnel_530_does_not_authorize_rollback():
    def unavailable(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://example.test/api/health",
            530,
            "tunnel unavailable",
            {},
            None,
        )

    result = wait_for_expected_commit(
        "https://example.test/api/health",
        "a" * 40,
        attempts=2,
        delay_seconds=0,
        open_url=unavailable,
        sleep=lambda _seconds: None,
    )

    assert result.verified is False
    assert result.rollback_safe is False
    assert result.last_response == {"error": "HTTP 530", "origin_reached": False}


def test_reachable_origin_with_wrong_commit_authorizes_rollback():
    result = wait_for_expected_commit(
        "https://example.test/api/health",
        "a" * 40,
        attempts=1,
        open_url=lambda *_args, **_kwargs: _response(
            {"status": "healthy", "commit": "b" * 40}
        ),
    )

    assert result.verified is False
    assert result.rollback_safe is True


def test_origin_http_error_authorizes_rollback():
    def server_error(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://example.test/api/health",
            500,
            "application failure",
            {},
            None,
        )

    result = wait_for_expected_commit(
        "https://example.test/api/health",
        "a" * 40,
        attempts=1,
        open_url=server_error,
    )

    assert result.verified is False
    assert result.rollback_safe is True

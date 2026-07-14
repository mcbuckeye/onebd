"""Tests for reusable public-source HTTP policy and provenance primitives."""

from io import BytesIO
import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

import pytest

from unified_api.services.public_source_http import (
    PublicSourceHttpClient,
    RetryPolicy,
)


class Response(BytesIO):
    status = 200

    def __init__(self, payload, *, url="https://example.test/final", headers=None):
        super().__init__(json.dumps(payload).encode())
        self._url = url
        self.headers = headers or {}

    def geturl(self):
        return self._url


def test_response_retains_source_and_http_provenance():
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return Response(
            {"records": [1]},
            headers={
                "ETag": '"abc"',
                "Last-Modified": "Mon, 13 Jul 2026 13:00:05 GMT",
                "Date": "Tue, 14 Jul 2026 03:00:00 GMT",
            },
        )

    client = PublicSourceHttpClient(
        source="example_api",
        base_url="https://example.test/api/",
        user_agent="OneBD test@example.test",
        timeout=12,
        opener=opener,
    )
    response = client.get_json("records", {"query": "lung cancer", "empty": None})

    assert response.source == "example_api"
    assert response.payload == {"records": [1]}
    assert response.etag == '"abc"'
    assert response.last_modified == "Mon, 13 Jul 2026 13:00:05 GMT"
    assert response.source_date == "Tue, 14 Jul 2026 03:00:00 GMT"
    assert response.attempts == 1
    assert response.cache_hit is False
    assert captured["timeout"] == 12
    assert parse_qs(urlparse(captured["url"]).query) == {"query": ["lung cancer"]}


def test_retry_after_and_transient_network_errors_share_one_policy():
    calls = []
    sleeps = []
    transient = HTTPError(
        "https://example.test/api/records",
        503,
        "busy",
        {"Retry-After": "2.5"},
        None,
    )

    def opener(_request, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            raise transient
        if len(calls) == 2:
            raise URLError("temporary DNS failure")
        return Response({"ok": True})

    client = PublicSourceHttpClient(
        source="example_api",
        base_url="https://example.test/api",
        user_agent="OneBD",
        opener=opener,
        sleep=sleeps.append,
        retry_policy=RetryPolicy(max_retries=2, backoff_seconds=1),
    )
    response = client.get_json("records")

    assert response.payload == {"ok": True}
    assert response.attempts == 3
    assert calls == [30, 30, 30]
    assert sleeps == [2.5, 2]


def test_minimum_request_interval_is_enforced_across_calls():
    sleeps = []
    ticks = iter([0.0, 0.0, 0.25, 0.25, 1.0])
    client = PublicSourceHttpClient(
        source="example_api",
        base_url="https://example.test",
        user_agent="OneBD",
        opener=lambda *_args, **_kwargs: Response({"ok": True}),
        sleep=sleeps.append,
        monotonic=lambda: next(ticks),
        min_interval_seconds=1,
    )

    client.get_json("/first")
    client.get_json("/second")

    assert sleeps == [0.75]


def test_post_json_sends_canonical_body_and_uses_body_aware_cache():
    requests = []
    ticks = iter([0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 2.0])

    def opener(request, timeout):
        requests.append((request.method, request.data, request.headers, timeout))
        return Response({"data": {"ok": True}})

    client = PublicSourceHttpClient(
        source="graphql",
        base_url="https://example.test/graphql",
        user_agent="OneBD",
        opener=opener,
        monotonic=lambda: next(ticks),
        cache_ttl_seconds=60,
    )
    first = client.post_json("", {"variables": {"id": 1}, "query": "query"}, use_cache=True)
    cached = client.post_json("", {"query": "query", "variables": {"id": 1}}, use_cache=True)
    different = client.post_json("", {"query": "different"}, use_cache=True)

    assert first.cache_hit is False
    assert cached.cache_hit is True
    assert different.cache_hit is False
    assert len(requests) == 2
    assert requests[0][0] == "POST"
    assert requests[0][1] == b'{"query":"query","variables":{"id":1}}'
    assert requests[0][2]["Content-type"] == "application/json"


def test_optional_ttl_cache_returns_provenance_marked_cache_hit():
    calls = []
    ticks = iter([0.0, 0.0, 0.0, 1.0])

    def opener(_request, timeout):
        calls.append(timeout)
        return Response({"version": 1})

    client = PublicSourceHttpClient(
        source="example_api",
        base_url="https://example.test",
        user_agent="OneBD",
        opener=opener,
        monotonic=lambda: next(ticks),
        cache_ttl_seconds=60,
    )

    first = client.get_json("/version", use_cache=True)
    second = client.get_json("/version", use_cache=True)

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.fetched_at == first.fetched_at
    assert calls == [30]


def test_not_found_can_be_a_typed_empty_result():
    error = HTTPError("https://example.test/missing", 404, "missing", {}, None)
    client = PublicSourceHttpClient(
        source="example_api",
        base_url="https://example.test",
        user_agent="OneBD",
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    assert client.get_json("/missing", not_found_is_none=True) is None
    with pytest.raises(HTTPError):
        client.get_json("/missing")


def test_non_object_json_is_rejected_before_adapter_parsing():
    client = PublicSourceHttpClient(
        source="example_api",
        base_url="https://example.test",
        user_agent="OneBD",
        opener=lambda *_args, **_kwargs: Response([1, 2, 3]),
    )
    with pytest.raises(ValueError, match="non-object"):
        client.get_json("/records")

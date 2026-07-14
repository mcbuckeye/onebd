"""Reusable, provenance-bearing HTTP primitives for public-data adapters."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class PublicSourceResponse:
    """A decoded response plus enough metadata to retain its provenance."""

    source: str
    request_url: str
    payload: dict[str, Any]
    fetched_at: datetime
    status_code: int
    attempts: int
    etag: str | None = None
    last_modified: str | None = None
    source_date: str | None = None
    cache_hit: bool = False


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 3
    retry_statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504})
    backoff_seconds: float = 1.0


class PublicSourceHttpClient:
    """Synchronous JSON client with shared throttling, retry, cache, and provenance."""

    def __init__(
        self,
        *,
        source: str,
        base_url: str,
        user_agent: str,
        timeout: float = 30,
        min_interval_seconds: float = 0,
        retry_policy: RetryPolicy | None = None,
        cache_ttl_seconds: float = 0,
        opener: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
    ):
        self.source = source
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout = timeout
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self.retry_policy = retry_policy or RetryPolicy()
        self.cache_ttl_seconds = max(0.0, cache_ttl_seconds)
        self._opener = opener or urlopen
        self._sleep = sleep or time.sleep
        self._monotonic = monotonic or time.monotonic
        self._last_request_started: float | None = None
        self._cache: dict[str, tuple[float, PublicSourceResponse]] = {}

    def _url(self, path: str, params: Mapping[str, Any] | None) -> str:
        query = urlencode({
            key: value
            for key, value in (params or {}).items()
            if value is not None
        })
        normalized_path = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{normalized_path}"
        return f"{url}?{query}" if query else url

    def _wait_for_rate_slot(self) -> None:
        now = self._monotonic()
        if self._last_request_started is not None:
            remaining = self.min_interval_seconds - (
                now - self._last_request_started
            )
            if remaining > 0:
                self._sleep(remaining)
                now = self._monotonic()
        self._last_request_started = now

    @staticmethod
    def _headers(response_or_error: Any) -> Mapping[str, Any]:
        return getattr(response_or_error, "headers", None) or {}

    @staticmethod
    def _retry_after(headers: Mapping[str, Any], *, fallback: float) -> float:
        raw = headers.get("Retry-After")
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            pass
        if raw:
            try:
                retry_at = parsedate_to_datetime(str(raw))
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(
                    0.0,
                    (retry_at - datetime.now(timezone.utc)).total_seconds(),
                )
            except (TypeError, ValueError, OverflowError):
                pass
        return fallback

    def get_json(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        not_found_is_none: bool = False,
        use_cache: bool = False,
    ) -> PublicSourceResponse | None:
        return self._request_json(
            "GET",
            path,
            params,
            not_found_is_none=not_found_is_none,
            use_cache=use_cache,
        )

    def post_json(
        self,
        path: str,
        payload: Mapping[str, Any],
        params: Mapping[str, Any] | None = None,
        *,
        not_found_is_none: bool = False,
        use_cache: bool = False,
    ) -> PublicSourceResponse | None:
        """POST a JSON object using the same policy and body-aware cache."""
        return self._request_json(
            "POST",
            path,
            params,
            json_body=payload,
            not_found_is_none=not_found_is_none,
            use_cache=use_cache,
        )

    def _request_json(
        self,
        method: str,
        path: str,
        params: Mapping[str, Any] | None,
        *,
        json_body: Mapping[str, Any] | None = None,
        not_found_is_none: bool,
        use_cache: bool,
    ) -> PublicSourceResponse | None:
        url = self._url(path, params)
        body = (
            json.dumps(json_body, sort_keys=True, separators=(",", ":")).encode()
            if json_body is not None else None
        )
        cache_key = url
        if body is not None:
            cache_key = f"{url}#{hashlib.sha256(body).hexdigest()}"
        now = self._monotonic()
        cached = self._cache.get(cache_key) if use_cache else None
        if cached and now - cached[0] <= self.cache_ttl_seconds:
            return replace(cached[1], cache_hit=True)

        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            url,
            data=body,
            headers=headers,
            method=method,
        )
        policy = self.retry_policy
        for attempt in range(policy.max_retries + 1):
            self._wait_for_rate_slot()
            try:
                with self._opener(request, timeout=self.timeout) as response:
                    payload = json.load(response)
                    if not isinstance(payload, dict):
                        raise ValueError(
                            f"{self.source} returned a non-object JSON payload"
                        )
                    headers = self._headers(response)
                    result = PublicSourceResponse(
                        source=self.source,
                        request_url=(
                            response.geturl()
                            if hasattr(response, "geturl") else url
                        ),
                        payload=payload,
                        fetched_at=datetime.now(timezone.utc),
                        status_code=int(getattr(response, "status", 200) or 200),
                        attempts=attempt + 1,
                        etag=headers.get("ETag"),
                        last_modified=headers.get("Last-Modified"),
                        source_date=headers.get("Date"),
                    )
                    if use_cache and self.cache_ttl_seconds > 0:
                        self._cache[cache_key] = (self._monotonic(), result)
                    return result
            except HTTPError as exc:
                if exc.code == 404 and not_found_is_none:
                    return None
                if exc.code not in policy.retry_statuses or attempt >= policy.max_retries:
                    raise
                fallback = policy.backoff_seconds * (2 ** attempt)
                self._sleep(self._retry_after(self._headers(exc), fallback=fallback))
            except URLError:
                if attempt >= policy.max_retries:
                    raise
                self._sleep(policy.backoff_seconds * (2 ** attempt))
        raise RuntimeError(f"{self.source} retry loop exhausted")

    def clear_cache(self) -> None:
        self._cache.clear()

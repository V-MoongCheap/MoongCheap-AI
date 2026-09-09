"""Shared transport and primitive validation for Backend plan contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any


def aware_datetime(value: object, context: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{context} must be an ISO-8601 date-time") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{context} must include a timezone offset")
    return parsed


def positive_int(value: object, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{context} must be a positive integer")
    return value


def nonnegative_int(value: object, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{context} must be a nonnegative integer")
    return value


def exact_fields(
    value: Mapping[str, Any],
    expected: set[str],
    context: str,
) -> None:
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing or extra:
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("extra=" + ",".join(extra))
        raise ValueError(f"{context} fields are invalid: " + "; ".join(details))


def required_fields(
    value: Mapping[str, Any],
    required: set[str],
    context: str,
) -> None:
    missing = sorted(required - set(value))
    if missing:
        raise ValueError(f"{context} is missing required fields: " + ",".join(missing))


def post_plan_json(
    backend_base_url: str,
    internal_key: str,
    plan: Mapping[str, Any],
    *,
    endpoint: str,
    timeout_seconds: int,
    http_post: Callable[..., Any],
    context: str,
) -> dict[str, Any]:
    """Send once using the injected internal key; never retry a mutation."""

    base_url = backend_base_url.strip().rstrip("/")
    if not base_url:
        raise ValueError("backend_base_url must not be empty")
    key = internal_key.strip()
    if not key:
        raise ValueError("internal_key must not be empty")
    if not isinstance(endpoint, str) or not endpoint.startswith("/"):
        raise ValueError("endpoint must be an absolute HTTP path")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    response = http_post(
        base_url + endpoint,
        headers={
            "X-Internal-Key": key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=dict(plan),
        timeout=timeout_seconds,
        allow_redirects=False,
    )
    if not response.ok or 300 <= response.status_code < 400:
        detail = response.text.replace(key, "[REDACTED]")[:500]
        raise RuntimeError(
            f"{context} failed with HTTP {response.status_code}: {detail}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"{context} response must be a JSON object")
    return payload

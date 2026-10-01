"""Provisional Backend contract for labeled Demand results."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

import requests

SCHEMA_VERSION = "demand-label-result.v0.1"


def _identifier(value: object) -> int | str:
    text = str(value).strip()
    if not text.isdigit():
        raise ValueError("Backend demand and catalog IDs must be positive integers")
    identifier = int(text)
    if identifier <= 0 or identifier > 9_223_372_036_854_775_807:
        raise ValueError("Backend ID is outside the positive BIGINT range")
    return identifier


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def build_label_result_payload(labeled: Any, *, processed_at: str) -> dict[str, Any]:
    if not isinstance(processed_at, str) or not processed_at.strip():
        raise ValueError("processed_at must be a timezone-aware ISO-8601 timestamp")
    try:
        parsed_processed_at = datetime.fromisoformat(processed_at.strip())
    except ValueError as error:
        raise ValueError(
            "processed_at must be a timezone-aware ISO-8601 timestamp"
        ) from error
    if parsed_processed_at.tzinfo is None or parsed_processed_at.utcoffset() is None:
        raise ValueError("processed_at must be a timezone-aware ISO-8601 timestamp")
    required = {
        "demand_id",
        "catalog_id",
        "category_id",
        "label",
        "facet_values",
        "label_status",
    }
    missing = sorted(required - set(labeled.columns))
    if missing:
        raise ValueError("labeled result missing columns: " + ", ".join(missing))
    rows = []
    seen_demand_ids: set[tuple[type, str]] = set()
    for item in labeled.fillna("").to_dict(orient="records"):
        # Completed product-baseline labels are writable even when consumer
        # text remains diagnostically REVIEW. Valid positive interpretations
        # may override that baseline; invalid category rows remain non-writable.
        if str(item.get("label_status", "")).strip() != "LABELED":
            continue
        demand_id = str(item.get("demand_id", "")).strip()
        catalog_id = str(item.get("catalog_id", "")).strip()
        category_id = str(item.get("category_id", "")).strip()
        label = str(item.get("label", "")).strip()
        missing_identifiers = {"", "nan", "none", "null", "<na>"}
        if (
            demand_id.casefold() in missing_identifiers
            or catalog_id.casefold() in missing_identifiers
            or category_id.casefold() in missing_identifiers
        ):
            raise ValueError("completed label is missing a required Backend identifier")
        normalized_demand_id = _identifier(demand_id)
        demand_key = (type(normalized_demand_id), str(normalized_demand_id))
        if demand_key in seen_demand_ids:
            raise ValueError(f"duplicate demand_id in Backend label payload: {demand_id}")
        seen_demand_ids.add(demand_key)
        if not re.fullmatch(r"\d+(?:-\d+)*", label):
            raise ValueError(f"completed label is not a numeric Facet vector: {demand_id}")
        try:
            facet_values = json.loads(
                str(item.get("facet_values", "")),
                object_pairs_hook=_unique_json_object,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"completed label has invalid facet_values JSON: {demand_id}") from error
        if not isinstance(facet_values, dict) or not facet_values:
            raise ValueError(f"completed label has no product Facet values: {demand_id}")
        try:
            codes = []
            for value in facet_values.values():
                if not isinstance(value, Mapping):
                    raise TypeError("Facet value must be an object")
                raw_code = value["code"]
                if isinstance(raw_code, bool) or not isinstance(raw_code, (str, int)):
                    raise TypeError("Facet code must be an integer")
                code_text = str(raw_code).strip()
                if not re.fullmatch(r"\d+", code_text):
                    raise ValueError("Facet code must be a non-negative integer")
                codes.append(int(code_text))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"completed label has invalid Facet codes: {demand_id}") from error
        if len(codes) != len(facet_values) or "-".join(map(str, codes)) != label:
            raise ValueError(f"label and facet_values disagree: {demand_id}")
        rows.append(
            {
                "demandId": _identifier(demand_id),
                "catalogId": _identifier(catalog_id),
                "categoryId": category_id,
                "label": label,
                "facetValues": json.dumps(facet_values, ensure_ascii=False, separators=(",", ":")),
                "labelStatus": str(item["label_status"]),
                "warnings": str(item.get("label_warnings", "")),
            }
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "processedAt": processed_at.strip(),
        "results": rows,
    }


def validate_backend_response(payload: Mapping[str, Any], expected_count: int) -> None:
    if payload.get("schemaVersion") not in {SCHEMA_VERSION, None}:
        raise ValueError("unsupported Backend label response schema")
    if payload.get("status") not in {"ACCEPTED", "APPLIED"}:
        raise ValueError("Backend label response status is not accepted")
    if "acceptedCount" in payload and int(payload["acceptedCount"]) != expected_count:
        raise ValueError("Backend acceptedCount does not match submitted results")


def post_label_results(
    base_url: str,
    internal_key: str,
    endpoint: str,
    payload: Mapping[str, Any],
    *,
    timeout_seconds: int = 15,
    http_post: Callable[..., Any] = requests.post,
) -> Mapping[str, Any]:
    if not base_url.strip() or not internal_key.strip() or not endpoint.startswith("/"):
        raise ValueError(
            "Backend URL, internal key, and absolute endpoint are required"
        )
    response = http_post(
        base_url.rstrip("/") + endpoint,
        headers={
            "X-Internal-Api-Key": internal_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=dict(payload),
        timeout=timeout_seconds,
        allow_redirects=False,
    )
    if not response.ok or 300 <= response.status_code < 400:
        detail = str(response.text).replace(internal_key, "[REDACTED]")[:500]
        raise RuntimeError(
            f"Backend label request failed with HTTP {response.status_code}: {detail}"
        )
    result = response.json()
    if not isinstance(result, Mapping):
        raise TypeError("Backend label response must be an object")
    validate_backend_response(result, len(payload.get("results", [])))
    return result

"""Provisional Backend contract for labeled Demand results."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from typing import Any

import requests

SCHEMA_VERSION = "demand-label-result.v0.1"


def _identifier(value: object) -> int | str:
    text = str(value).strip()
    return int(text) if text.isdigit() else text


def build_label_result_payload(labeled: Any, *, processed_at: str) -> dict[str, Any]:
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
        if not demand_id or not catalog_id or not category_id:
            raise ValueError("completed label is missing a required Backend identifier")
        if not re.fullmatch(r"\d+(?:-\d+)*", label):
            raise ValueError(f"completed label is not a numeric Facet vector: {demand_id}")
        try:
            facet_values = json.loads(str(item.get("facet_values", "")))
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError(f"completed label has invalid facet_values JSON: {demand_id}") from error
        if not isinstance(facet_values, dict) or not facet_values:
            raise ValueError(f"completed label has no product Facet values: {demand_id}")
        try:
            codes = [
                int(value["code"])
                for value in facet_values.values()
                if isinstance(value, Mapping)
            ]
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
        "processedAt": processed_at,
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

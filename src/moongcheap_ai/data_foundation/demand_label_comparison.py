"""Compare Rule, local LLM, and Hybrid Demand facet labeling."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

import pandas as pd

from .labeling import TaxonomyLoader


class LLMLabelingError(RuntimeError):
    pass


def _allowed(loader: TaxonomyLoader, category_id: str) -> dict[str, list[dict[str, Any]]]:
    category = loader.category(category_id)
    return {str(facet["name"]): facet["values"] for facet in (category or {}).get("facets", [])}


def _prompt(rows: list[dict[str, Any]], loader: TaxonomyLoader) -> str:
    categories = {}
    for row in rows:
        category_id = str(row["category_id"])
        categories[category_id] = _allowed(loader, category_id)
    facet_order = {}
    for category_id, facet_values in categories.items():
        facet_order[category_id] = list(facet_values)
    return (
        "You classify Korean consumer demand into the provided taxonomy. Return JSON only. "
        "Return exactly one result for every input demand_id, with no omitted or invented IDs. "
        "For every demand return demand_id and facet_values, mapping the exact facet names listed below to an integer code. "
        "Use product_defaults unless extra_requirement explicitly conflicts; then extra_requirement wins. "
        "Never use numeric facet names, shortened names, or invent a facet or code. Code 0 means ALL.\n"
        f"Facet names by category, in order: {json.dumps(facet_order, ensure_ascii=False)}\n"
        f"Taxonomy: {json.dumps(categories, ensure_ascii=False)}\n"
        f"Demands: {json.dumps(rows, ensure_ascii=False)}\n"
        'Schema: {"results":[{"demand_id":"...","facet_values":{"facet_name":0}}]}'
    )


def _normalise_model_facet_values(raw: Any) -> dict[str, Any]:
    """Accept the two common local-model shapes without weakening taxonomy checks."""
    if isinstance(raw, list):
        converted: dict[str, Any] = {}
        for item in raw:
            if isinstance(item, dict) and "facet_name" in item:
                facet_name = str(item["facet_name"])
                converted[facet_name] = {key: item[key] for key in ("code", "value") if key in item}
        return converted
    if not isinstance(raw, dict):
        return {}
    if "facet_name" in raw and "value" in raw:
        facet_name = str(raw["facet_name"])
        return {facet_name: {"value": raw["value"]}}
    return {str(name): value for name, value in raw.items()}


class OllamaDemandLabeler:
    provider = "ollama"

    def __init__(self, model: str, endpoint: str = "http://localhost:11434", timeout: int = 300) -> None:
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.call_count = 0
        self.runtime_seconds = 0.0

    def classify(self, rows: list[dict[str, Any]], loader: TaxonomyLoader) -> dict[str, dict[str, Any]]:
        started = time.perf_counter()
        self.call_count += 1
        schema = {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "demand_id": {"type": "string"},
                            "facet_values": {"type": "object"},
                        },
                        "required": ["demand_id", "facet_values"],
                    },
                }
            },
            "required": ["results"],
        }
        body = json.dumps({"model": self.model, "prompt": _prompt(rows, loader), "format": schema, "options": {"temperature": 0}, "stream": False, "think": False}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(f"{self.endpoint}/api/generate", data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            parsed = json.loads(payload.get("response", ""))
            results = parsed if isinstance(parsed, list) else parsed.get("results")
            if not isinstance(results, list):
                raise ValueError("results is not a list")
            expected_ids = {str(row["demand_id"]) for row in rows}
            output = {}
            for item in results:
                if not isinstance(item, dict) or "demand_id" not in item or not isinstance(item.get("facet_values"), dict):
                    continue
                demand_id = str(item["demand_id"])
                if demand_id in expected_ids:
                    output[demand_id] = _normalise_model_facet_values(item["facet_values"])
        except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise LLMLabelingError(str(exc)) from exc
        finally:
            self.runtime_seconds += time.perf_counter() - started
        return output


def _rule_result(demands: pd.DataFrame, loader: TaxonomyLoader, product_facet_map: dict[str, list[dict[str, Any]]]) -> pd.DataFrame:
    from .labeling import label_demands

    return label_demands(demands, loader, product_facet_map=product_facet_map)


def _apply_model_result(row: pd.Series, model_values: dict[str, Any], loader: TaxonomyLoader, product_rows: list[dict[str, Any]] | None = None) -> tuple[dict[str, dict[str, Any]], list[str]]:
    defaults, warnings = loader.product_defaults(row["category_id"], product_rows or [])
    allowed = _allowed(loader, row["category_id"])
    ordered_facets = list(allowed)
    for facet_name, raw_code in model_values.items():
        facet_key = str(facet_name).strip()
        if ":" in facet_key:
            facet_key = facet_key.rsplit(":", 1)[-1]
        numeric_match = re.fullmatch(r"(?:facet[_ -]?)?(\d+)(?:\.0)?", facet_key, flags=re.IGNORECASE)
        if numeric_match and int(numeric_match.group(1)) < len(ordered_facets):
            facet_name = ordered_facets[int(numeric_match.group(1))]
        else:
            facet_name = next((name for name in ordered_facets if name.casefold() == facet_key.casefold()), facet_key)
        if raw_code is None:
            continue
        code = raw_code.get("code") if isinstance(raw_code, dict) else raw_code
        if isinstance(raw_code, dict) and code is None and raw_code.get("value") is None:
            continue
        matched = [value for value in allowed.get(facet_name, []) if str(value.get("code", "")) == str(code)]
        if not matched:
            text = str(raw_code.get("value", "") if isinstance(raw_code, dict) else raw_code).strip()
            matched = [value for value in allowed.get(facet_name, []) if text.casefold() in {str(value.get("value", "")).casefold(), *(str(alias).casefold() for alias in value.get("aliases", []))}]
        values = matched
        if not values:
            warnings.append(f"LLM code not found in taxonomy: {facet_name}={code}")
            continue
        value = values[0]
        defaults[facet_name] = {"code": int(value["code"]), "value": value.get("value", ""), "matched_alias": "LLM"}
    return defaults, warnings


def compare_labeling_methods(demands: pd.DataFrame, loader: TaxonomyLoader, product_facet_map: dict[str, list[dict[str, Any]]], llm: OllamaDemandLabeler, batch_size: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    rule = _rule_result(demands.fillna(""), loader, product_facet_map)
    model_values: dict[str, dict[str, int]] = {}
    model_errors: dict[str, str] = {}
    for start in range(0, len(demands), batch_size):
        batch = demands.iloc[start:start + batch_size]
        payload = []
        for _, row in batch.iterrows():
            defaults, _ = loader.product_defaults(row["category_id"], product_facet_map.get(str(row["catalog_id"]), []))
            payload.append({"demand_id": row["demand_id"], "category_id": row["category_id"], "extra_requirement": row["extra_requirement"], "product_defaults": defaults})
        try:
            model_values.update(llm.classify(payload, loader))
        except LLMLabelingError as exc:
            for demand_id in batch["demand_id"]:
                model_errors[str(demand_id)] = str(exc)
    rows: list[dict[str, Any]] = []
    for position, (_, source) in enumerate(demands.fillna("").iterrows()):
        rule_row = rule.iloc[position]
        base = {"demand_id": source["demand_id"], "catalog_id": source["catalog_id"], "category_id": source["category_id"], "is_substitutable": source["is_substitutable"], "rule_label": rule_row["label"], "rule_status": rule_row["label_status"], "rule_facet_values": rule_row["facet_values"]}
        model = model_values.get(str(source["demand_id"]))
        if model is not None:
            values, warnings = _apply_model_result(source, model, loader, product_facet_map.get(str(source["catalog_id"]), []))
            model_label = loader.encode(values)
            model_status = "LABELED" if not warnings else "LABELED_WITH_REVIEW"
        else:
            model_label, model_status, warnings = "", "MODEL_FAILURE", [model_errors.get(str(source["demand_id"]), "missing LLM result")]
        hybrid_label = model_label if model_status != "MODEL_FAILURE" and rule_row["label_status"] != "LABELED" else rule_row["label"]
        hybrid_status = model_status if model_status != "MODEL_FAILURE" and rule_row["label_status"] != "LABELED" else rule_row["label_status"]
        rows.append({**base, "model_label": model_label, "model_status": model_status, "model_warnings": json.dumps(warnings, ensure_ascii=False), "hybrid_label": hybrid_label, "hybrid_status": hybrid_status})
    result = pd.DataFrame(rows)
    summary = pd.DataFrame([
        {"method": "RULE_ONLY", "rows": len(result), "labeled": int((result.rule_status == "LABELED").sum()), "review": int((result.rule_status != "LABELED").sum()), "model_calls": 0},
        {"method": "MODEL_ONLY", "rows": len(result), "labeled": int((result.model_status == "LABELED").sum()), "review": int((result.model_status != "LABELED").sum()), "model_calls": llm.call_count},
        {"method": "RULE_AND_MODEL", "rows": len(result), "labeled": int((result.hybrid_status == "LABELED").sum()), "review": int((result.hybrid_status != "LABELED").sum()), "model_calls": llm.call_count},
    ])
    summary["rule_model_label_agreement"] = [1.0, None, float((result.rule_label == result.hybrid_label).mean())]
    return result, summary

"""Evidence-first Rule/LLM hybrid Facet candidate comparison."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd

from .model1_postprocess import (
    atomic_values,
    canonical_facet,
    canonical_value,
)

RULE_FIELDS = {
    "product_form": "product_form",
    "functional_ingredients": "functional_ingredients",
}


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip()


def _key(facet_id: Any, value: Any) -> tuple[str, str]:
    canonical_id, _ = canonical_facet(facet_id, facet_id)
    return canonical_id, canonical_value(canonical_id, value)


def build_rule_candidates(inputs: pd.DataFrame, min_support: int = 1, min_ratio: float = 0.0) -> pd.DataFrame:
    """Extract deterministic product Facet candidates and retain source evidence."""
    columns = [
        "category_key", "category_name", "facet_id_candidate", "name", "definition",
        "value", "alias", "source_product_id", "source_field", "source_text", "status",
        "rule_support", "rule_support_ratio",
    ]
    if inputs.empty:
        return pd.DataFrame(columns=columns)

    frame = inputs.fillna("").copy()
    if "source_type" in frame:
        frame = frame[~frame["source_type"].astype(str).isin({"CONSUMER_SEARCH", "DEMAND_BOARD_SYNTHETIC", "GROUNDED_DEMAND_SYNTHETIC"})]
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        for facet_id, source_field in RULE_FIELDS.items():
            raw = _text(row.get(source_field, ""))
            for value in atomic_values(facet_id, raw):
                if not value:
                    continue
                rows.append({
                    "category_key": _text(row.get("category_key", "")),
                    "category_name": _text(row.get("category_name", "")),
                    "facet_id_candidate": facet_id,
                    "name": {"product_form": "제품 형태", "functional_ingredients": "기능성 성분"}[facet_id],
                    "definition": "Observed in structured product evidence",
                    "value": value,
                    "alias": "",
                    "source_product_id": _text(row.get("source_product_id", "")),
                    "source_field": source_field,
                    "source_text": raw,
                    "status": "RULE_OBSERVED_CANDIDATE",
                })
    if not rows:
        return pd.DataFrame(columns=columns)

    result = pd.DataFrame(rows)
    category_totals = result.groupby("category_key")["source_product_id"].nunique().to_dict()
    supports = result.groupby(["category_key", "facet_id_candidate", "value"])["source_product_id"].nunique().to_dict()
    result["rule_support"] = [int(supports[(row.category_key, row.facet_id_candidate, row.value)]) for row in result.itertuples()]
    result["rule_support_ratio"] = [
        round(row.rule_support / max(int(category_totals.get(row.category_key, 0)), 1), 4)
        for row in result.itertuples()
    ]
    result = result[(result.rule_support >= min_support) & (result.rule_support_ratio >= min_ratio)]
    return result[columns].drop_duplicates().sort_values(
        ["category_key", "facet_id_candidate", "value", "source_product_id"], ignore_index=True
    )


def _candidate_key(row: pd.Series) -> tuple[str, str, str]:
    facet_id, _ = canonical_facet(row.get("facet_id_candidate", row.get("facet_id", "")), row.get("name", row.get("facet_name", "")))
    return _text(row.get("category_key", "")), facet_id, canonical_value(facet_id, row.get("value", ""))


def merge_rule_model_candidates(rule_candidates: pd.DataFrame, model_candidates: pd.DataFrame) -> pd.DataFrame:
    """Classify candidates without allowing unobserved model values to auto-promote."""
    output_columns = [
        "category_key", "facet_id", "value", "rule_support", "rule_support_ratio",
        "model_support", "model_names", "evidence_product_count", "source_fields",
        "hybrid_status", "model_only_review_required",
    ]
    rule = rule_candidates.fillna("").copy()
    model = model_candidates.fillna("").copy()
    if rule.empty and model.empty:
        return pd.DataFrame(columns=output_columns)

    rule_groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for _, row in rule.iterrows():
        key = _candidate_key(row)
        item = rule_groups.setdefault(key, {"supports": set(), "ratios": [], "fields": set()})
        item["supports"].add(_text(row.get("source_product_id", "")))
        item["ratios"].append(float(row.get("rule_support_ratio", 0) or 0))
        item["fields"].add(_text(row.get("source_field", "")))

    model_groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for _, row in model.iterrows():
        key = _candidate_key(row)
        item = model_groups.setdefault(key, {"models": set(), "evidence": set(), "fields": set()})
        item["models"].add(_text(row.get("model", "")))
        item["evidence"].update(_text(value) for value in _text(row.get("source_product_id", "")).split("|") if _text(value))
        item["fields"].add(_text(row.get("source_field", "")))

    rows = []
    for key in sorted(set(rule_groups) | set(model_groups)):
        category_key, facet_id, value = key
        rule_info = rule_groups.get(key, {})
        model_info = model_groups.get(key, {})
        has_rule = key in rule_groups
        has_model = key in model_groups
        if has_rule and has_model:
            status = "HYBRID_BACKED"
        elif has_rule:
            status = "RULE_ONLY"
        else:
            status = "MODEL_ONLY_REVIEW"
        rows.append({
            "category_key": category_key,
            "facet_id": facet_id,
            "value": value,
            "rule_support": len(rule_info.get("supports", set())),
            "rule_support_ratio": max(rule_info.get("ratios", [0])),
            "model_support": len(model_info.get("models", set())),
            "model_names": "|".join(sorted(model_info.get("models", set()))),
            "evidence_product_count": len(model_info.get("evidence", set())) or len(rule_info.get("supports", set())),
            "source_fields": "|".join(sorted(rule_info.get("fields", set()) | model_info.get("fields", set()))),
            "hybrid_status": status,
            "model_only_review_required": status == "MODEL_ONLY_REVIEW",
        })
    return pd.DataFrame(rows, columns=output_columns)


def benchmark_candidate_sets(rule_candidates: pd.DataFrame, model_candidates: pd.DataFrame, hybrid: pd.DataFrame) -> dict[str, Any]:
    """Return comparable operational metrics for Rule, Model, and Hybrid outputs."""
    rule_keys = {_candidate_key(row) for _, row in rule_candidates.fillna("").iterrows()}
    model_keys = {_candidate_key(row) for _, row in model_candidates.fillna("").iterrows()}
    hybrid_keys = set(zip(hybrid.get("category_key", []), hybrid.get("facet_id", []), hybrid.get("value", []))) if not hybrid.empty else set()
    model_only = hybrid[hybrid["hybrid_status"].eq("MODEL_ONLY_REVIEW")] if not hybrid.empty else pd.DataFrame()
    return {
        "rule_candidate_count": len(rule_keys),
        "model_candidate_count": len(model_keys),
        "hybrid_candidate_count": len(hybrid_keys),
        "hybrid_backed_count": int(hybrid["hybrid_status"].eq("HYBRID_BACKED").sum()) if not hybrid.empty else 0,
        "rule_only_count": int(hybrid["hybrid_status"].eq("RULE_ONLY").sum()) if not hybrid.empty else 0,
        "model_only_review_count": len(model_only),
        "model_observation_coverage": round(len(model_keys & rule_keys) / len(model_keys), 4) if model_keys else 0.0,
        "hybrid_observation_coverage": round(len(hybrid_keys & rule_keys) / len(hybrid_keys), 4) if hybrid_keys else 0.0,
        "unobserved_model_auto_accept_count": 0,
        "policy": "Rule evidence is the promotion gate; model-only candidates remain review-only.",
    }

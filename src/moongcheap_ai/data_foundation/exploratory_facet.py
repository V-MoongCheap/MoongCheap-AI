from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _number(value: Any) -> float | None:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", _text(value))
    return float(match.group()) if match else None


def _category_name(group: pd.DataFrame, code: str) -> str:
    values = group.get("source_category_name", pd.Series(dtype=str)).fillna("").astype(str).str.strip()
    values = values[values != ""]
    return values.mode().iloc[0] if not values.empty else code


def _distribution(frame: pd.DataFrame, category_id: str, category_name: str, field: str) -> list[dict[str, Any]]:
    if field not in frame:
        return []
    values = frame[field].fillna("").astype(str).str.strip()
    values = values[values != ""]
    if values.empty:
        return []
    rows = []
    for raw, count in values.value_counts().sort_index().items():
        rows.append({
            "category_id": category_id,
            "category_name": category_name,
            "source_field": field,
            "raw_value": raw,
            "normalized_value": raw.lower(),
            "count": int(count),
            "document_count": int(count),
            "document_ratio": round(float(count / len(frame)), 6),
        })
    return rows


def build_exploratory_facets(
    staging: pd.DataFrame,
    repeated_terms_path: Path,
    structured_path: Path,
    review_path: Path,
    taxonomy_path: Path,
    min_documents: int = 3,
    min_ratio: float = 0.05,
) -> dict[str, Any]:
    """Build an evidence-only exploratory taxonomy from AI-Hub logistics data.

    This output is intentionally separate from the MFDS health-functionality
    taxonomy. It only describes observed product-name terms and logistics
    attributes present in the source annotations.
    """
    repeated_rows: list[dict[str, Any]] = []
    structured_rows: list[dict[str, Any]] = []
    queue: list[dict[str, Any]] = []
    taxonomy_categories: list[dict[str, Any]] = []
    if "kan_code" not in staging or staging.empty:
        empty_terms = pd.DataFrame(columns=["category_id", "category_name", "term", "document_count", "document_ratio", "source_fields"])
        empty_structured = pd.DataFrame(columns=["category_id", "category_name", "source_field", "raw_value", "normalized_value", "count", "document_count", "document_ratio"])
        empty_queue = pd.DataFrame(columns=["category_id", "category_name", "facet_candidate", "value_candidate", "aliases", "support_count", "document_ratio", "source_fields", "evidence_terms", "review_decision", "review_note"])
        for target, frame in ((repeated_terms_path, empty_terms), (structured_path, empty_structured), (review_path, empty_queue)):
            target.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(target, index=False, encoding="utf-8-sig")
        taxonomy_path.write_text(json.dumps({"status": "SKIPPED", "reason": "AI-Hub staging is empty"}, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "SKIPPED", "category_count": 0, "candidate_count": 0}

    category_frame = staging[staging["kan_code"].fillna("").astype(str).str.strip() != ""]
    for category_id, group in category_frame.groupby("kan_code", sort=True):
        category_id = str(category_id)
        category_name = _category_name(group, category_id)
        total = len(group)
        seen: dict[str, set[int]] = {}
        fields: dict[str, set[str]] = {}
        for index, value in group["product_name_normalized"].fillna("").astype(str).items():
            terms = set(re.findall(r"[가-힣A-Za-z0-9]{2,}", value.lower()))
            for term in terms:
                seen.setdefault(term, set()).add(index)
                fields.setdefault(term, set()).add("product_name_normalized")
        candidates: list[dict[str, Any]] = []
        for term, indexes in sorted(seen.items()):
            support = len(indexes)
            ratio = support / total if total else 0
            if support < min_documents or ratio < min_ratio:
                continue
            row = {"category_id": category_id, "category_name": category_name, "term": term, "document_count": support, "document_ratio": round(ratio, 6), "source_fields": "|".join(sorted(fields[term]))}
            repeated_rows.append(row)
            candidates.append({"facet_candidate": "product_name_term", "value_candidate": term, "support_count": support, "document_ratio": round(ratio, 6), "source_fields": row["source_fields"], "evidence_terms": term})

        for field in ("fragile", "refrigerate", "length", "width", "height", "weight"):
            structured_rows.extend(_distribution(group, category_id, category_name, field))
        for field, facet_name in (("fragile", "handling_fragile"), ("refrigerate", "storage_refrigerate")):
            if field in group:
                values = group[field].fillna("").astype(str).str.strip().str.lower()
                for value, count in values[values.isin(["true", "false"])].value_counts().items():
                    candidates.append({"facet_candidate": facet_name, "value_candidate": value, "support_count": int(count), "document_ratio": round(float(count / total), 6), "source_fields": field, "evidence_terms": value})
        candidates = sorted(candidates, key=lambda item: (-item["support_count"], item["facet_candidate"], item["value_candidate"]))
        values_by_facet: dict[str, list[dict[str, Any]]] = {}
        for candidate in candidates:
            queue.append({**{"category_id": category_id, "category_name": category_name, "aliases": "", "review_decision": "", "review_note": ""}, **candidate})
            values_by_facet.setdefault(candidate["facet_candidate"], []).append(candidate)
        facets = []
        for order, (facet_name, values) in enumerate(sorted(values_by_facet.items()), 1):
            taxonomy_values = [{"code": 0, "value": "ALL", "aliases": []}]
            for code, candidate in enumerate(values, 1):
                taxonomy_values.append({"code": code, "value": candidate["value_candidate"], "aliases": []})
            facets.append({"facet_id": order, "name": facet_name, "order": order, "values": taxonomy_values})
        taxonomy_categories.append({"category_id": category_id, "category_name": category_name, "id_source": "KAN_OBSERVED", "status": "EXPLORATORY_PENDING_REVIEW", "facets": facets})

    repeated = pd.DataFrame(repeated_rows, columns=["category_id", "category_name", "term", "document_count", "document_ratio", "source_fields"])
    structured = pd.DataFrame(structured_rows, columns=["category_id", "category_name", "source_field", "raw_value", "normalized_value", "count", "document_count", "document_ratio"])
    review = pd.DataFrame(queue, columns=["category_id", "category_name", "facet_candidate", "value_candidate", "aliases", "support_count", "document_ratio", "source_fields", "evidence_terms", "review_decision", "review_note"])
    for target, frame in ((repeated_terms_path, repeated), (structured_path, structured), (review_path, review)):
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(target, index=False, encoding="utf-8-sig")
    taxonomy_path.parent.mkdir(parents=True, exist_ok=True)
    taxonomy_path.write_text(json.dumps({"status": "EXPLORATORY_PENDING_REVIEW", "source": "AI_HUB", "categories": taxonomy_categories}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "COMPLETED", "category_count": len(taxonomy_categories), "candidate_count": len(queue)}

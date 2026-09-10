"""Build a safe Alias registry from the human-reviewed Alias sheet."""

from __future__ import annotations

import argparse
import json
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd


def _normalize(value: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def _accepted(row: pd.Series) -> bool:
    decision = str(row.get("reviewer_decision", "")).strip()
    corrected = str(row.get("corrected_value_candidate", "")).strip()
    return decision == "APPROVE_ALIAS" or (decision == "NEEDS_REVIEW" and bool(corrected))


def build_registry(review_path: Path, taxonomy_path: Path, crosswalk_path: Path | None = None) -> tuple[dict[str, object], pd.DataFrame]:
    review = pd.read_csv(review_path, dtype=str).fillna("")
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    crosswalk = json.loads(crosswalk_path.read_text(encoding="utf-8")).get("mappings", {}) if crosswalk_path else {}
    taxonomy_values: dict[str, set[str]] = defaultdict(set)
    for category in taxonomy.get("categories", []):
        for facet in category.get("facets", []):
            facet_name = str(facet.get("name", "")).strip()
            for value in facet.get("values", []):
                if int(value.get("code", 0)) != 0:
                    taxonomy_values[facet_name].add(_normalize(value.get("value")))

    grouped: dict[tuple[str, str], dict[str, object]] = {}
    audit_rows: list[dict[str, object]] = []
    for _, row in review.iterrows():
        if not _accepted(row):
            continue
        facet = str(row["facet_id"]).strip()
        canonical = str(row.get("corrected_value_candidate", "")).strip() or str(row["value_candidate"]).strip()
        key = (facet, canonical)
        entry = grouped.setdefault(key, {"facet_name": facet, "canonical_value": canonical, "surfaces": [], "source_review_orders": []})
        surface = str(row["candidate_expression"]).strip()
        if surface and surface not in entry["surfaces"]:
            entry["surfaces"].append(surface)
        entry["source_review_orders"].append(int(row["review_order"]))

    for entry in grouped.values():
        facet = str(entry["facet_name"])
        canonical = str(entry["canonical_value"])
        taxonomy_canonical = str(crosswalk.get(facet, {}).get(canonical, canonical))
        entry["taxonomy_canonical_value"] = taxonomy_canonical
        if facet not in taxonomy_values:
            status = "BLOCKED_FACET_NOT_IN_TAXONOMY"
        elif _normalize(taxonomy_canonical) not in taxonomy_values[facet]:
            status = "BLOCKED_CANONICAL_VALUE_NOT_IN_TAXONOMY"
        else:
            status = "READY_TO_APPLY"
        audit_rows.append({
            "facet_name": facet,
            "canonical_value": canonical,
            "taxonomy_canonical_value": taxonomy_canonical,
            "surface_count": len(entry["surfaces"]),
            "surfaces": " | ".join(entry["surfaces"]),
            "source_review_orders": " | ".join(map(str, entry["source_review_orders"])),
            "apply_status": status,
        })

    audit = pd.DataFrame(audit_rows).sort_values(["apply_status", "facet_name", "canonical_value"], kind="stable") if audit_rows else pd.DataFrame()
    ready = [row for row in audit_rows if row["apply_status"] == "READY_TO_APPLY"]
    registry = {
        "version": "model1-reviewed-aliases-v1",
        "source": str(review_path),
        "taxonomy": str(taxonomy_path),
        "taxonomy_is_modified": False,
        "aliases": [
            {"facet_name": row["facet_name"], "canonical_value": row["taxonomy_canonical_value"], "surfaces": row["surfaces"].split(" | ") if row["surfaces"] else []}
            for row in ready
        ],
        "blocked_aliases": [row for row in audit_rows if row["apply_status"] != "READY_TO_APPLY"],
        "summary": {
            "accepted_review_rows": int(sum(_accepted(row) for _, row in review.iterrows())),
            "unique_alias_targets": len(audit_rows),
            "ready_to_apply_targets": len(ready),
            "blocked_targets": len(audit_rows) - len(ready),
            "decision_counts": Counter(str(value) for value in review["reviewer_decision"]),
        },
    }
    return registry, audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path, default=None)
    parser.add_argument("--output-registry", type=Path, required=True)
    parser.add_argument("--output-audit", type=Path, required=True)
    args = parser.parse_args()
    registry, audit = build_registry(args.review, args.taxonomy, args.crosswalk)
    args.output_registry.parent.mkdir(parents=True, exist_ok=True)
    args.output_audit.parent.mkdir(parents=True, exist_ok=True)
    args.output_registry.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    audit.to_csv(args.output_audit, index=False, encoding="utf-8-sig")
    print(json.dumps(registry["summary"], ensure_ascii=False, default=dict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

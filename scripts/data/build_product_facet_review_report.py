"""Build a human-review queue and quality summary for product facet mappings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


STATUS_PRIORITY = {
    "AMBIGUOUS": "HIGH",
    "UNKNOWN": "MEDIUM",
    "UNMATCHED_CATEGORY": "BLOCKED",
}
PRIORITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "BLOCKED": 2, "REVIEW": 3}


def build_review_queue(mapping: pd.DataFrame) -> pd.DataFrame:
    """Keep unresolved mappings and add review metadata without changing facts."""
    required = {
        "catalog_id",
        "source_product_id",
        "category_id",
        "facet_name",
        "value",
        "mapping_status",
        "mapping_reason",
        "matched_text",
        "source_fields",
        "source_document_id",
        "source",
    }
    missing = sorted(required - set(mapping.columns))
    if missing:
        raise ValueError("mapping is missing columns: " + ", ".join(missing))

    unresolved = mapping.loc[mapping["mapping_status"].ne("MAPPED")].copy()
    unresolved["review_priority"] = unresolved["mapping_status"].map(
        STATUS_PRIORITY
    ).fillna("REVIEW")
    unresolved["_priority_order"] = unresolved["review_priority"].map(
        PRIORITY_ORDER
    ).fillna(PRIORITY_ORDER["REVIEW"])
    unresolved["reviewed_value"] = ""
    unresolved["reviewed_code"] = ""
    unresolved["review_decision"] = ""
    unresolved["review_note"] = ""
    columns = [
        "review_priority",
        "mapping_status",
        "mapping_reason",
        "catalog_id",
        "source_product_id",
        "category_id",
        "facet_name",
        "value",
        "matched_text",
        "source_fields",
        "candidate_evidence",
        "source_document_id",
        "source",
        "reviewed_value",
        "reviewed_code",
        "review_decision",
        "review_note",
    ]
    if "candidate_evidence" not in unresolved:
        unresolved["candidate_evidence"] = "[]"
    return unresolved.sort_values(
        ["_priority_order", "category_id", "catalog_id", "facet_name"]
    )[columns].reset_index(drop=True)


def build_summary(mapping: pd.DataFrame, review_queue: pd.DataFrame) -> dict:
    """Summarize mapping uncertainty for triage; no accuracy claim is made."""
    def counts(frame: pd.DataFrame, columns: list[str]) -> dict:
        if frame.empty:
            return {}
        grouped = frame.groupby(columns, dropna=False).size()
        return {" / ".join(map(str, key if isinstance(key, tuple) else (key,))): int(value)
                for key, value in grouped.items()}

    return {
        "mapping_rows": int(len(mapping)),
        "mapped_rows": int(mapping["mapping_status"].eq("MAPPED").sum()),
        "review_rows": int(len(review_queue)),
        "status_counts": mapping["mapping_status"].value_counts(dropna=False).to_dict(),
        "status_by_facet": counts(mapping, ["facet_name", "mapping_status"]),
        "status_by_category": counts(mapping, ["category_id", "mapping_status"]),
        "priority_counts": review_queue["review_priority"].value_counts(dropna=False).to_dict(),
        "review_policy": {
            "AMBIGUOUS": "HIGH: multiple observed taxonomy values; human decision required",
            "UNKNOWN": "MEDIUM: no observed value in available product fields",
            "UNMATCHED_CATEGORY": "BLOCKED: category-to-taxonomy mapping required first",
            "MAPPED": "not included in queue; observed evidence remains auditable",
        },
    }


def build(mapping_path: Path, queue_path: Path, summary_path: Path) -> tuple[pd.DataFrame, dict]:
    mapping = pd.read_csv(mapping_path, dtype=str, encoding="utf-8-sig").fillna("")
    queue = build_review_queue(mapping)
    summary = build_summary(mapping, queue)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    queue.to_csv(queue_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return queue, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--queue-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    args = parser.parse_args()
    queue, summary = build(args.mapping, args.queue_output, args.summary_output)
    print(json.dumps({"status": "VALID", "queue_rows": len(queue), **summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

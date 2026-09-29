"""Build a deterministic, evidence-gated Taxonomy draft from Hybrid candidates."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

REVIEW_COLUMNS = [
    "category_id",
    "category_name",
    "facet_candidate",
    "value_candidate",
    "aliases",
    "support_count",
    "document_ratio",
    "source_fields",
    "evidence_terms",
    "hybrid_status",
    "review_decision",
    "review_note",
]
HYBRID_COLUMNS = {"category_key", "facet_id", "value", "rule_support", "rule_support_ratio", "hybrid_status", "source_fields"}


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _safe_int(value: object, default: int = 0) -> int:
    return int(_safe_float(value, default))


def build_draft(
    hybrid: pd.DataFrame,
    inputs: pd.DataFrame,
    *,
    min_support: int = 2,
    min_ratio: float = 0.1,
) -> tuple[dict, pd.DataFrame]:
    """Return a contract-shaped draft and a complete human review queue.

    Only candidates backed by structured Rule evidence can enter the draft.
    ``MODEL_ONLY_REVIEW`` rows remain visible in the queue and can never be
    promoted implicitly by this function.
    """
    frame = hybrid.fillna("").copy()
    missing = sorted(HYBRID_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"hybrid candidates missing required columns: {', '.join(missing)}")
    input_frame = inputs.fillna("")
    names = (
        input_frame.drop_duplicates("category_key")
        .set_index("category_key")["category_name"].to_dict()
        if {"category_key", "category_name"}.issubset(input_frame.columns)
        else {}
    )

    review_rows: list[dict] = []
    accepted = frame[
        (frame["hybrid_status"] != "MODEL_ONLY_REVIEW")
        & (pd.to_numeric(frame["rule_support"], errors="coerce").fillna(0) >= min_support)
        & (pd.to_numeric(frame["rule_support_ratio"], errors="coerce").fillna(0) >= min_ratio)
    ].copy()

    for _, row in frame.sort_values(["category_key", "facet_id", "value"]).iterrows():
        support = _safe_int(row.get("rule_support", 0))
        ratio = _safe_float(row.get("rule_support_ratio", 0))
        status = str(row.get("hybrid_status", ""))
        if status == "MODEL_ONLY_REVIEW":
            decision, note = "REVIEW_REQUIRED", "Model-only candidate; structured evidence gate not passed"
        elif support < min_support or ratio < min_ratio:
            decision, note = "REVIEW_REQUIRED", "Below draft promotion threshold"
        else:
            decision, note = "", "Evidence-backed draft candidate; human review required"
        review_rows.append(
            {
                "category_id": row.get("category_key", ""),
                "category_name": names.get(row.get("category_key", ""), row.get("category_key", "")),
                "facet_candidate": row.get("facet_id", ""),
                "value_candidate": row.get("value", ""),
                "aliases": "",
                "support_count": support,
                "document_ratio": ratio,
                "source_fields": row.get("source_fields", ""),
                "evidence_terms": row.get("value", ""),
                "hybrid_status": status,
                "review_decision": decision,
                "review_note": note,
            }
        )

    categories: list[dict] = []
    for category_key, group in accepted.groupby("category_key", sort=True):
        facets: list[dict] = []
        for order, (facet_id, facet_group) in enumerate(group.groupby("facet_id", sort=True), 1):
            values = facet_group.sort_values(
                ["rule_support", "rule_support_ratio", "value"],
                ascending=[False, False, True],
            ).drop_duplicates("value")
            facet_values = [{"code": 0, "value": "ALL", "aliases": []}]
            for code, value in enumerate(values["value"].astype(str), 1):
                facet_values.append({"code": code, "value": value, "aliases": []})
            facets.append({"facet_id": order, "name": facet_id, "order": order, "values": facet_values})
        categories.append(
            {
                "category_id": category_key,
                "category_name": names.get(category_key, category_key),
                "status": "DRAFT_PENDING_HUMAN_REVIEW",
                "facets": facets,
            }
        )
    return {
        "status": "DRAFT_PENDING_HUMAN_REVIEW",
        "source": "RULE_MODEL_HYBRID",
        "promotion_policy": "RULE_EVIDENCE_REQUIRED; MODEL_ONLY_REVIEW_NEVER_AUTO_PROMOTED",
        "thresholds": {"min_support": min_support, "min_ratio": min_ratio},
        "categories": categories,
    }, pd.DataFrame(review_rows, columns=REVIEW_COLUMNS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hybrid", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-support", type=int, default=2)
    parser.add_argument("--min-ratio", type=float, default=0.1)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    hybrid = pd.read_csv(args.hybrid, dtype=str).fillna("")
    inputs = pd.read_json(args.input, lines=True).fillna("")
    taxonomy, queue = build_draft(hybrid, inputs, min_support=args.min_support, min_ratio=args.min_ratio)
    serialized = json.dumps(taxonomy, ensure_ascii=False, indent=2)
    (args.output_dir / "facet_taxonomy_v0.json").write_text(serialized, encoding="utf-8")
    (args.output_dir / "taxonomy_candidate_v0.json").write_text(serialized, encoding="utf-8")
    queue.to_csv(args.output_dir / "facet_review_queue.csv", index=False, encoding="utf-8-sig")
    print(json.dumps({"categories": len(taxonomy["categories"]), "draft_candidates": int(queue["review_decision"].eq("").sum()), "review_rows": len(queue)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

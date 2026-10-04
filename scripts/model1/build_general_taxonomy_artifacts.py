"""Build reviewable, general-product Model 1 taxonomy artifacts.

Rule terms are evidence, not semantic facets.  Only model proposals whose value
also occurs in category evidence are promoted to the draft taxonomy; all other
terms remain in the review queue for human grouping or rejection.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

STATUS = "DRAFT_PENDING_HUMAN_REVIEW"
AUTO_STATUS = "AUTO_APPROVED_BY_STRICT_GATE"


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


def _normal(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def build_taxonomy(hybrid: pd.DataFrame) -> dict[str, object]:
    grounded = hybrid.loc[hybrid["source"].eq("LLM_GROUNDED_AND_RULE_MATCHED")].copy()
    categories: list[dict[str, object]] = []
    for category_key, category_rows in grounded.groupby("category_key", sort=True):
        facets: list[dict[str, object]] = []
        for facet_index, (facet_name, facet_rows) in enumerate(
            category_rows.groupby("facet_candidate", sort=True), start=1
        ):
            values = sorted(
                {_normal(value) for value in facet_rows["value"] if _normal(value)}
            )
            facets.append(
                {
                    "facet_id": facet_index,
                    "name": facet_name,
                    "order": facet_index,
                    "values": [
                        {"code": 0, "value": "ALL", "aliases": []},
                        *[
                            {"code": code, "value": value, "aliases": []}
                            for code, value in enumerate(values, start=1)
                        ],
                    ],
                }
            )
        categories.append(
            {
                "category_id": category_key,
                "category_key": category_key,
                "facets": facets,
            }
        )
    return {
        "status": STATUS,
        "id_source": "CATEGORY_KEY_UNTIL_BACKEND_ID_MAPPING",
        "policy": "Only evidence-gated model proposals enter the draft; rule-only terms remain review evidence.",
        "categories": categories,
    }


def build_review_queue(
    hybrid: pd.DataFrame, model_candidates: pd.DataFrame, terms: pd.DataFrame
) -> pd.DataFrame:
    model = model_candidates.copy()
    model["join_key"] = list(
        zip(
            model["category_key"].map(_normal),
            model["name"].map(_normal),
            model["value"].map(_normal),
        )
    )
    model = model.drop_duplicates("join_key")
    rows: list[dict[str, object]] = []
    for row in hybrid.to_dict(orient="records"):
        key = (
            _normal(row["category_key"]),
            _normal(row["facet_candidate"]),
            _normal(row["value"]),
        )
        match = model.loc[
            model["join_key"].map(lambda item, expected=key: item == expected)
        ]
        candidate = match.iloc[0].to_dict() if not match.empty else {}
        is_model = row["source"] == "LLM_GROUNDED_AND_RULE_MATCHED"
        rows.append(
            {
                "category_id": row["category_key"],
                "category_name": row["category_key"].removeprefix("domeggook:"),
                "facet_candidate": row["facet_candidate"],
                "value_candidate": row["value"],
                "aliases": candidate.get("alias", "") if is_model else "",
                "support_count": row["document_count"],
                "document_ratio": row["document_ratio"],
                "source_fields": row["source_fields"],
                "evidence_terms": row["value"],
                "source": row["source"],
                "source_product_id": candidate.get("source_product_id", ""),
                "source_text": candidate.get("source_text", ""),
                "review_decision": "",
                "review_note": (
                    "Model proposal grounded in observed category evidence; verify semantic facet and value."
                    if is_model
                    else "Observed term only; do not treat as a facet without semantic grouping review."
                ),
            }
        )
    return pd.DataFrame(rows)


def automatic_gate(
    hybrid: pd.DataFrame, model_candidates: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Approve only grounded, non-self-describing model proposals.

    This removes mandatory manual review, but deliberately abstains on ambiguous
    candidates instead of inventing a facet grouping.
    """
    grounded = hybrid.loc[hybrid["source"].eq("LLM_GROUNDED_AND_RULE_MATCHED")].copy()
    if grounded.empty:
        return grounded, grounded.copy()
    candidates = model_candidates.copy()
    candidates["value_norm"] = candidates["value"].map(_normal)
    candidates["facet_norm"] = candidates["name"].map(_normal)
    candidates["category_norm"] = candidates["category_name"].map(_normal)
    candidates["auto_gate_reason"] = ""
    candidates.loc[
        candidates["value_norm"].eq(candidates["facet_norm"]), "auto_gate_reason"
    ] = "facet_name_equals_value"
    candidates.loc[
        candidates["facet_norm"].eq(candidates["category_norm"]), "auto_gate_reason"
    ] = "facet_name_equals_category"
    candidates.loc[candidates["name"].str.strip().eq(""), "auto_gate_reason"] = (
        "missing_facet_name"
    )
    candidates["join_key"] = list(
        zip(
            candidates["category_key"].map(_normal),
            candidates["facet_norm"],
            candidates["value_norm"],
        )
    )
    grounded["join_key"] = list(
        zip(
            grounded["category_key"].map(_normal),
            grounded["facet_candidate"].map(_normal),
            grounded["value"].map(_normal),
        )
    )
    # A disagreeing duplicate must never be resolved by input order.
    rejected_keys = set(
        candidates.loc[candidates["auto_gate_reason"].ne(""), "join_key"]
    )
    accepted_keys = (
        set(candidates.loc[candidates["auto_gate_reason"].eq(""), "join_key"])
        - rejected_keys
    )
    accepted = grounded.loc[grounded["join_key"].isin(accepted_keys)].copy()
    rejected = candidates.loc[~candidates["join_key"].isin(accepted_keys)].copy()
    rejected = rejected[
        ["category_key", "category_name", "name", "value", "auto_gate_reason"]
    ]
    return accepted.drop(columns=["join_key"]), rejected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hybrid", type=Path, required=True)
    parser.add_argument("--model-candidates", type=Path, required=True)
    parser.add_argument("--terms", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--automatic",
        action="store_true",
        help="Also emit a strict auto-approved taxonomy and abstention queue.",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    hybrid = _read(args.hybrid)
    model = _read(args.model_candidates)
    terms = _read(args.terms)
    coverage = _read(args.coverage)
    taxonomy = build_taxonomy(hybrid)
    queue = build_review_queue(hybrid, model, terms)

    (args.output_dir / "facet_taxonomy_v1.json").write_text(
        json.dumps(taxonomy, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    queue.to_csv(
        args.output_dir / "facet_review_queue_v1.csv", index=False, encoding="utf-8-sig"
    )
    coverage.to_csv(
        args.output_dir / "product_coverage_v1.csv", index=False, encoding="utf-8-sig"
    )

    grounded_count = int(hybrid["source"].eq("LLM_GROUNDED_AND_RULE_MATCHED").sum())
    report = {
        "status": STATUS,
        "model": "qwen3:4b",
        "input_products": len(coverage),
        "covered_products": int(
            (coverage["coverage_status"] != "NO_RELIABLE_FACET_EVIDENCE").sum()
        ),
        "unresolved_products": int(
            (coverage["coverage_status"] == "NO_RELIABLE_FACET_EVIDENCE").sum()
        ),
        "hybrid_rows": len(hybrid),
        "grounded_model_rows": grounded_count,
        "taxonomy_categories": len(taxonomy["categories"]),
        "taxonomy_facets": sum(
            len(category["facets"]) for category in taxonomy["categories"]
        ),
        "review_queue_rows": len(queue),
        "rule_terms_not_auto_promoted": int(
            (hybrid["source"] == "RULE_EVIDENCE").sum()
        ),
        "human_review_required": True,
        "notes": [
            "This is a general-product draft, not a health-functional-food-only taxonomy.",
            "Products without reliable facet evidence are retained and marked unresolved.",
            "Backend category/product IDs are not available; category_key is used temporarily.",
        ],
    }
    (args.output_dir / "model1_final_report_v1.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if args.automatic:
        accepted, rejected = automatic_gate(hybrid, model)
        auto_taxonomy = build_taxonomy(accepted)
        auto_taxonomy["status"] = AUTO_STATUS
        auto_taxonomy["policy"] = (
            "Automatic approval requires model/rule grounding and rejects self-describing or ambiguous facet names."
        )
        (args.output_dir / "facet_taxonomy_auto_v1.json").write_text(
            json.dumps(auto_taxonomy, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        rejected.to_csv(
            args.output_dir / "facet_auto_abstention_queue_v1.csv",
            index=False,
            encoding="utf-8-sig",
        )
        auto_report = {
            "status": AUTO_STATUS,
            "accepted_rows": len(accepted),
            "abstained_rows": len(rejected),
            "accepted_categories": len(auto_taxonomy["categories"]),
            "accepted_facets": sum(
                len(c["facets"]) for c in auto_taxonomy["categories"]
            ),
            "human_review_required": False,
            "abstention_policy": "Ambiguous candidates are excluded from the automatic taxonomy, never silently promoted.",
        }
        (args.output_dir / "model1_auto_gate_report_v1.json").write_text(
            json.dumps(auto_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        report["automatic_gate"] = auto_report
        (args.output_dir / "model1_final_report_v1.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

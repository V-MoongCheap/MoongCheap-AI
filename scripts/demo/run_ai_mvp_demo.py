"""Print a reproducible local demo summary for the AI MVP pipeline.

The default mode replays historical local artifacts so a mentoring demo does not
need external APIs, a database account, Ollama, or cloud credentials.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]


def _csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


def _count(path: Path) -> int:
    return len(_csv(path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("all", "a", "b", "c"), default="all")
    parser.add_argument("--show-samples", action="store_true")
    args = parser.parse_args()

    a = ROOT / "data/processed/demand_5000_catalog_seed_v1/part_a_runtime_v2_2_6/part_a_runtime_v2_2_6.csv"
    b = ROOT / "data/processed/mvp_e2e_automatic_v2_2_6_resolved/demand_cluster_summary_v0.csv"
    c = ROOT / "data/processed/mvp_e2e_automatic_v2_2_6_resolved/seller_offer_matches_v0.csv"
    analysis = ROOT / "data/processed/mvp_e2e_automatic_v2_2_6_resolved/seller_demand_analysis_v0.csv"
    gold = ROOT / "data/processed/model2_gold_v1/model2_demand_gold_final_v1.csv"
    supported = ROOT / "data/processed/model2_gold_v1/model2_gold_supported_v1.csv"

    required = {"all": [a, b, c, analysis, gold, supported],
                "a": [a, gold, supported], "b": [b], "c": [b, c, analysis]}[args.stage]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        raise SystemExit("missing demo artifacts:\n- " + "\n- ".join(missing))

    print("저장된 과거 산출물 재생입니다. 현행 A/B/C 재실행·운영 보드 정책 검증이 아닙니다.")
    a_frame = _csv(a) if a in required else pd.DataFrame()
    b_frame = _csv(b) if b in required else pd.DataFrame()
    c_frame = _csv(c) if c in required else pd.DataFrame()
    analysis_frame = _csv(analysis) if analysis in required else pd.DataFrame()
    summary = {
        "status": "COMPLETED",
        "execution_mode": "HISTORICAL_ARTIFACT_REPLAY_NOT_RUNTIME_EVALUATION",
        "production_board_policy_verified": False,
        "human_review_used_during_demo": False,
        "a_labeling": {
            "rows": len(a_frame),
            "status_counts": a_frame.get("status", pd.Series(dtype=str)).value_counts().to_dict(),
        },
        "b_clustering": {
            "clusters": len(b_frame),
            "total_quantity": int(pd.to_numeric(b_frame.get("total_quantity", pd.Series(dtype=str)), errors="coerce").fillna(0).sum()),
        },
        "c_matching": {
            "offer_comparisons": len(c_frame),
            "candidate_matches": int(c_frame.get("match_status", pd.Series(dtype=str)).eq("CANDIDATE").sum()),
            "clusters_analyzed": len(analysis_frame),
        },
        "model2_gold": {
            "final_rows": _count(gold) if gold in required else None,
            "taxonomy_supported_rows": _count(supported) if supported in required else None,
            "out_of_taxonomy_rows": _count(gold) - _count(supported) if gold in required else None,
        },
    }
    if args.stage in {"all", "a"}:
        print("\n=== A: Demand Labeling ===")
        print("입력: 상품 Category + extra_requirement")
        print(a_frame[["demand_id", "extra_requirement", "status", "label", "reasonCodes"]].head(5).to_string(index=False))
    if args.stage in {"all", "b"}:
        print("\n=== B: Demand Clustering ===")
        print("입력: A Label + catalog/category + quantity + substitutable")
        print(b_frame[["cluster_id", "category_id", "label", "participant_count", "total_quantity", "substitutable"]].head(5).to_string(index=False))
    if args.stage in {"all", "c"}:
        print("\n=== C: Seller Matching / Analysis ===")
        print("입력: Cluster + Seller Offer. 타 판매자 가격은 표시하지 않음.")
        candidates = c_frame[c_frame["match_status"].eq("CANDIDATE")].copy()
        cluster_columns = ["cluster_id", "category_id", "label", "participant_count", "total_quantity"]
        offer_path = ROOT / "data/processed/domeggook/seller_offers_core.csv"
        if offer_path.exists() and not candidates.empty:
            offers = _csv(offer_path)
            offer_columns = ["item_id", "seller_id", "category_leaf", "min_unit_price", "moq", "inventory_raw"]
            candidates = candidates.merge(offers[[column for column in offer_columns if column in offers.columns]], on=["item_id", "seller_id"], how="left")
            candidates = candidates.merge(b_frame[cluster_columns], on="cluster_id", how="left")
        display_columns = [
            "cluster_id", "item_id", "seller_id", "category_id", "label", "participant_count", "total_quantity",
            "category_match", "moq_known", "moq_ok", "price_available", "min_unit_price", "moq", "score", "reason",
        ]
        print(candidates[[column for column in display_columns if column in candidates.columns]].head(5).to_string(index=False))
    if args.stage == "all":
        print("\n=== Pipeline summary ===")
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

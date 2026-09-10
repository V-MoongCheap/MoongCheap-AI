"""Run the CSV-only A -> B -> C MVP handoff locally."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from moongcheap_ai.demand_clustering.baseline import cluster_demands, summarize_clusters
from moongcheap_ai.seller_analysis.baseline import summarize_seller_demand
from moongcheap_ai.seller_matching.baseline import match_offers


def run(input_path: Path, offers_path: Path, output_dir: Path) -> dict[str, int | str]:
    demands = pd.read_csv(input_path, dtype=str).fillna("")
    offers = pd.read_csv(offers_path, dtype=str).fillna("") if offers_path.exists() else pd.DataFrame()
    clustered = cluster_demands(demands)
    clusters = summarize_clusters(clustered)
    matches = match_offers(clusters, offers)
    summary = summarize_seller_demand(clusters, matches)
    output_dir.mkdir(parents=True, exist_ok=True)
    clustered.to_csv(output_dir / "demand_clusters_v0.csv", index=False, encoding="utf-8-sig")
    clusters.to_csv(output_dir / "demand_cluster_summary_v0.csv", index=False, encoding="utf-8-sig")
    matches.to_csv(output_dir / "seller_offer_matches_v0.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(output_dir / "seller_demand_analysis_v0.csv", index=False, encoding="utf-8-sig")
    return {"status": "COMPLETED", "demands": len(demands), "clusters": len(clusters), "matches": len(matches), "offers": len(offers)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("../data/processed/demand_5000_v1/clustering_input_grounded_5000_v1.csv"))
    parser.add_argument("--offers", type=Path, default=Path("../data/processed/domeggook/seller_offers_core.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/mvp_e2e_v1"))
    args = parser.parse_args()
    print(run(args.input, args.offers, args.output_dir))


if __name__ == "__main__":
    main()

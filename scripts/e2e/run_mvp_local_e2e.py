"""Run the CSV-only B -> C MVP smoke locally.

This covers clustering -> offer candidate check -> seller summary only. It starts
from an already labeled demand CSV; the Part A parser and the A -> B input
generator (`scripts/demand/build_part_a_b_clustering_input.py`) are not run.

Choose the input explicitly:

    python scripts/e2e/run_mvp_local_e2e.py --example --output-dir /tmp/e2e-smoke
    python scripts/e2e/run_mvp_local_e2e.py --input <demands.csv> --offers <offers.csv>

Giving only one of `--input` / `--offers`, or mixing them with `--example`, is
rejected so that real and synthetic files are never combined silently.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from moongcheap_ai.demand_clustering.baseline import cluster_demands, summarize_clusters
from moongcheap_ai.seller_analysis.baseline import summarize_seller_demand
from moongcheap_ai.seller_matching.baseline import match_offers

EXAMPLE_DIR = Path(__file__).resolve().parents[2] / "data" / "samples" / "e2e"
EXAMPLE_DEMANDS = EXAMPLE_DIR / "demands_sample.csv"
EXAMPLE_OFFERS = EXAMPLE_DIR / "offers_sample.csv"


def run(input_path: Path, offers_path: Path, output_dir: Path) -> dict[str, int | str]:
    # A missing file must fail. Replacing it with an empty frame reports COMPLETED
    # with zero matches, which looks the same as "no candidate offers".
    for option, path in (("--input", input_path), ("--offers", offers_path)):
        if not path.exists():
            raise FileNotFoundError(f"{option} file not found: {path}")
    demands = pd.read_csv(input_path, dtype=str).fillna("")
    offers = pd.read_csv(offers_path, dtype=str).fillna("")
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--example", action="store_true", help="use the committed synthetic samples in data/samples/e2e")
    parser.add_argument("--input", type=Path, help="labeled demand CSV (required with --offers unless --example)")
    parser.add_argument("--offers", type=Path, help="seller offer CSV (required with --input unless --example)")
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/mvp_e2e_v1"))
    args = parser.parse_args(argv)

    # Reject before run() so a rejected call never creates the output directory.
    given = [option for option, value in (("--input", args.input), ("--offers", args.offers)) if value is not None]
    if args.example and given:
        parser.error(f"--example cannot be combined with {' / '.join(given)}")
    if not args.example and len(given) != 2:
        parser.error("give both --input and --offers, or use --example")

    mode = "example" if args.example else "files"
    input_path = EXAMPLE_DEMANDS if args.example else args.input
    offers_path = EXAMPLE_OFFERS if args.example else args.offers
    result = run(input_path, offers_path, args.output_dir)
    print({**result, "mode": mode, "input": str(input_path), "offers_file": str(offers_path)})


if __name__ == "__main__":
    main()

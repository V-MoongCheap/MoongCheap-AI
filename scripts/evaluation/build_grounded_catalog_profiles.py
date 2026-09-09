from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.mfds_product_profiles import (
    add_demand_profile_coverage,
    build_mfds_product_profile_candidates,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build MFDS-backed catalog profiles for grounded demands"
    )
    parser.add_argument("--demands", type=Path, required=True)
    parser.add_argument(
        "--products",
        type=Path,
        default=Path(
            "data/interim/facet_discovery/i0030_products_clean_dedup.csv"
        ),
    )
    parser.add_argument(
        "--references",
        type=Path,
        default=Path("data/interim/facet_discovery/i2710_reference.csv"),
    )
    parser.add_argument(
        "--claims",
        type=Path,
        default=Path("data/reports/mfds_function_claim_candidates_v1.csv"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise RuntimeError(
            f"refusing to overwrite output directory: {args.output_dir}"
        )

    demands = pd.read_csv(args.demands, dtype=str, keep_default_na=False)
    profiles, summary = build_mfds_product_profile_candidates(
        demands,
        pd.read_csv(args.products, dtype=str, keep_default_na=False),
        pd.read_csv(args.references, dtype=str, keep_default_na=False),
        pd.read_csv(args.claims, dtype=str, keep_default_na=False),
    )
    manifest = {
        **add_demand_profile_coverage(summary, demands, profiles),
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sourcePaths": {
            "demands": str(args.demands),
            "products": str(args.products),
            "references": str(args.references),
            "claims": str(args.claims),
        },
        "profileFile": "catalog_profile_candidates.csv",
    }
    args.output_dir.mkdir(parents=True)
    profiles.to_csv(
        args.output_dir / "catalog_profile_candidates.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()

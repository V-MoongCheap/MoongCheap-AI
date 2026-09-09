from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.function_claims import (
    build_function_claim_candidates,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build review candidates for atomic MFDS function claims"
    )
    parser.add_argument(
        "--references",
        type=Path,
        default=Path("data/interim/facet_discovery/i2710_reference.csv"),
    )
    parser.add_argument(
        "--signatures",
        type=Path,
        default=Path("data/reports/mfds_function_signatures_v1.csv"),
    )
    parser.add_argument(
        "--claims",
        type=Path,
        default=Path("data/reports/mfds_function_claim_candidates_v1.csv"),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("data/reports/mfds_function_claim_analysis_v1.json"),
    )
    args = parser.parse_args()

    references = pd.read_csv(
        args.references,
        dtype=str,
        keep_default_na=False,
    )
    signatures, claims, summary = build_function_claim_candidates(references)
    for path in (args.signatures, args.claims, args.summary):
        path.parent.mkdir(parents=True, exist_ok=True)
    signatures.to_csv(args.signatures, index=False, encoding="utf-8-sig")
    claims.to_csv(args.claims, index=False, encoding="utf-8-sig")
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Apply human decisions entered in the Model 1 review queue."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from moongcheap_ai.data_foundation.model1_review import apply_human_decisions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, default=Path("data/processed/model1_multisource_v1/multisource_candidate_review_queue_v1.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/model1_multisource_v1"))
    args = parser.parse_args()
    queue = pd.read_csv(args.queue, dtype=str).fillna("")
    resolved, accepted = apply_human_decisions(queue)
    resolved.to_csv(args.output_dir / "multisource_candidate_review_resolved_v1.csv", index=False, encoding="utf-8-sig")
    accepted.to_csv(args.output_dir / "multisource_candidate_human_accepted_v1.csv", index=False, encoding="utf-8-sig")
    print({"rows": len(resolved), "accepted": len(accepted), "unreviewed": int(resolved.resolution_status.eq("UNREVIEWED").sum())})


if __name__ == "__main__":
    main()

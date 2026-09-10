"""Export fixed Part A Gold splits only after every candidate is reviewed."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


REQUIRED = {"DEV": 100, "HOLDOUT": 50, "CHALLENGE": 50}


def finalize(input_path: Path, output_dir: Path) -> dict[str, int]:
    frame = pd.read_csv(input_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    missing = {column for column in ("case_id", "evaluation_partition_candidate", "reviewer_status") if column not in frame}
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")
    if len(frame) != 200:
        raise ValueError(f"expected 200 reviewed candidates, got {len(frame)}")
    if frame["case_id"].duplicated().any():
        raise ValueError("case_id must be unique")
    pending = frame.loc[frame["reviewer_status"].str.upper().ne("APPROVED")]
    if not pending.empty:
        raise ValueError(f"{len(pending)} rows are not APPROVED; Gold export is blocked")
    counts = frame["evaluation_partition_candidate"].value_counts().to_dict()
    if counts != REQUIRED:
        raise ValueError(f"unexpected partition counts: {counts}; expected {REQUIRED}")
    output_dir.mkdir(parents=True, exist_ok=True)
    for partition, count in REQUIRED.items():
        frame.loc[frame["evaluation_partition_candidate"].eq(partition)].to_csv(
            output_dir / f"part_a_v2_2_{partition.lower()}_gold.csv", index=False, encoding="utf-8-sig"
        )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(finalize(args.input, args.output_dir))


if __name__ == "__main__":
    main()

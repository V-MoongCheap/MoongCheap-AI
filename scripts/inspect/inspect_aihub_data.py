"""Inspect AI-Hub files without modifying or extracting raw archives."""

import argparse
import json
from pathlib import Path

import pandas as pd

from moongcheap_ai.inspect_data import inspect


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("data/raw/aihub"))
    args = parser.parse_args()
    files, samples = inspect(args.root)
    reports = Path("data/reports")
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "aihub_inspection.json").write_text(json.dumps({"files": files, "samples": samples}, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(files).to_csv(reports / "aihub_file_inventory.csv", index=False, encoding="utf-8-sig")
    print(f"Inspected {len(files)} files. Reports: {reports}")


if __name__ == "__main__":
    main()

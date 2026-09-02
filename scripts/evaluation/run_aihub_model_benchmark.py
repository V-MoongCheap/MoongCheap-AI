from __future__ import annotations

import argparse
from pathlib import Path

from moongcheap_ai.data_foundation.model_benchmark import write_benchmark_outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare lightweight AI-Hub product-name matching baselines")
    parser.add_argument("--staging", type=Path, default=Path("data/interim/products/product_staging.parquet"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/evaluation/matching"))
    parser.add_argument("--max-rows", type=int, default=50000)
    args = parser.parse_args()
    print(write_benchmark_outputs(args.staging, args.output_dir, args.max_rows))


if __name__ == "__main__":
    main()

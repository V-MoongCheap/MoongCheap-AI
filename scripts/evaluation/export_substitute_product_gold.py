from __future__ import annotations

import argparse
import json
from pathlib import Path

from moongcheap_ai.demand_clustering.evaluation.substitute_annotation import (
    SubstituteAnnotationStore,
    dataset_fingerprint,
    load_pair_frame,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export adjudicated substitute-product gold labels"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/processed/substitute_product/pair_review_v1.csv"),
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(
            "data/processed/substitute_product/pair_annotations_v1.sqlite3"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "data/processed/substitute_product/pair_review_gold_v1.csv"
        ),
    )
    args = parser.parse_args()

    pairs = load_pair_frame(args.input)
    store = SubstituteAnnotationStore(args.database)
    store.verify_dataset(
        pairs["pair_id"].tolist(), dataset_fingerprint(args.input)
    )
    result = store.export_gold(pairs, args.output)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

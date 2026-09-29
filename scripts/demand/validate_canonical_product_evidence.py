"""Validate a real product evidence export before Demand generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from moongcheap_ai.data_foundation.canonical_product import load_canonical_product_evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    frame = load_canonical_product_evidence(args.path)
    print(json.dumps({
        "status": "VALID",
        "rows": len(frame),
        "catalog_count": int(frame["catalog_id"].nunique()),
        "category_count": int(frame["category_id"].nunique()),
        "source_document_count": int(frame["source_document_id"].nunique()),
        "review_provenance_rows": int(frame["source_review_id"].ne("").sum()),
        "keyword_provenance_rows": int(frame["source_keyword"].ne("").sum()),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

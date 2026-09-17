"""Build category-level MFDS evidence and observed catalog facet mappings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from moongcheap_ai.data_foundation.product_facet_mapping import (
    build_category_evidence,
    build_reference_evidence,
    build_product_mapping,
    load_taxonomy,
)


def read_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--mfds", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--mapping-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    parser.add_argument("--mfds-reference", type=Path)
    parser.add_argument("--reference-output", type=Path)
    parser.add_argument("--min-evidence-documents", type=int, default=3)
    parser.add_argument("--min-evidence-ratio", type=float, default=0.05)
    args = parser.parse_args()
    taxonomy = load_taxonomy(str(args.taxonomy))
    catalog = read_frame(args.catalog)
    mfds = read_frame(args.mfds)
    evidence = build_category_evidence(mfds, taxonomy, args.min_evidence_documents, args.min_evidence_ratio)
    mapping = build_product_mapping(catalog, taxonomy)
    references = read_frame(args.mfds_reference) if args.mfds_reference else None
    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    args.mapping_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    evidence.to_csv(args.evidence_output, index=False, encoding="utf-8-sig")
    mapping.to_csv(args.mapping_output, index=False, encoding="utf-8-sig")
    reference_rows = 0
    reference_mapped_rows = 0
    if references is not None:
        if not args.reference_output:
            raise SystemExit("--reference-output is required with --mfds-reference")
        reference_evidence = build_reference_evidence(references, taxonomy)
        args.reference_output.parent.mkdir(parents=True, exist_ok=True)
        reference_evidence.to_csv(args.reference_output, index=False, encoding="utf-8-sig")
        reference_rows = len(reference_evidence)
        reference_mapped_rows = int(reference_evidence["category_id"].ne("").sum())
    summary = {
        "catalog_rows": int(len(catalog)),
        "mapping_rows": int(len(mapping)),
        "mapped_rows": int((mapping["mapping_status"] == "MAPPED").sum()),
        "unknown_rows": int((mapping["mapping_status"] == "UNKNOWN").sum()),
        "ambiguous_rows": int((mapping["mapping_status"] == "AMBIGUOUS").sum()),
        "mfds_rows": int(len(mfds)),
        "evidence_rows": int(len(evidence)),
        "evidence_categories": int(evidence["category_id"].nunique()) if not evidence.empty else 0,
        "join_policy": "category crosswalk only; no direct Domeggook-MFDS product-id join",
        "evidence_rule": {"min_documents": args.min_evidence_documents, "min_ratio": args.min_evidence_ratio},
        "mfds_reference_rows": int(reference_rows),
        "mfds_reference_category_mapped_rows": int(reference_mapped_rows),
    }
    args.summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

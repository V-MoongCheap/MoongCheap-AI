from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from moongcheap_ai.data_foundation.facet_evidence import (
    SOURCE_LICENSES,
    aggregate_evidence,
    build_audit,
    build_kuaisearch,
    build_review_queue,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Add KuaiSearch Lite evidence to an existing Facet evidence snapshot")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--evidence-dir", type=Path, default=Path("data/interim/facet_evidence"))
    parser.add_argument("--translated", type=Path, default=None, help="Optional Korean translation parquet for query matching")
    args = parser.parse_args()
    unified_path = args.evidence_dir / "facet_evidence_unified.parquet"
    if not unified_path.exists():
        raise SystemExit(f"existing evidence not found: {unified_path}")
    kuai = build_kuaisearch(args.root / "data/raw/consumer_reference/kuaisearch", args.evidence_dir / "kuaiseach_health_queries.parquet", args.translated)
    unified = pd.concat([pd.read_parquet(unified_path), kuai], ignore_index=True).drop_duplicates(subset=["evidence_id"])
    aggregate = aggregate_evidence(unified)
    review = build_review_queue(aggregate, unified)
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    unified.to_parquet(unified_path, index=False)
    unified.to_csv(args.evidence_dir / "facet_evidence_unified_preview.csv", index=False, encoding="utf-8-sig")
    aggregate.to_csv(args.evidence_dir / "facet_cross_source_evidence.csv", index=False, encoding="utf-8-sig")
    review.to_csv(args.evidence_dir / "facet_review_queue_v1.csv", index=False, encoding="utf-8-sig")
    (args.evidence_dir / "facet_candidates_v1.json").write_text(__import__("json").dumps({"version": "v1", "status": "REVIEW", "candidates": aggregate.to_dict(orient="records")}, ensure_ascii=False, indent=2), encoding="utf-8")
    report_dir = args.root / "data/reports/facet_discovery"
    report_dir.mkdir(parents=True, exist_ok=True)
    statuses = [{"source": "kuaisearch", "status": "AVAILABLE", "rows": len(kuai)}]
    (report_dir / "FACET_EVIDENCE_RESULT.md").write_text(build_audit(unified, aggregate, statuses), encoding="utf-8")
    license_row = {"source": "kuaisearch", "official_url": SOURCE_LICENSES["kuaisearch"][0], "license": SOURCE_LICENSES["kuaisearch"][1], "download_allowed": "UNKNOWN", "processing_allowed": "UNKNOWN", "redistribution_allowed": "UNKNOWN", "github_raw_allowed": "UNKNOWN", "local_only": True, "notes": "AVAILABLE_LITE"}
    license_path = report_dir / "facet_evidence_source_license.csv"
    existing = pd.read_csv(license_path, dtype=str).fillna("") if license_path.exists() else pd.DataFrame()
    existing = existing[existing.get("source", pd.Series(dtype=str)).ne("kuaisearch")] if not existing.empty else existing
    pd.concat([existing, pd.DataFrame([license_row])], ignore_index=True).to_csv(license_path, index=False, encoding="utf-8-sig")
    print({"status": "COMPLETED", "kuaisearch_evidence_rows": len(kuai), "unified_rows": len(unified), "candidate_rows": len(aggregate)})


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.function_relation_artifact import (
    build_function_relation_runtime_payload,
)
from moongcheap_ai.demand_clustering.function_relation_registry import (
    function_relation_registry_from_payload,
)
from moongcheap_ai.demand_clustering.evaluation.product_candidate_graph import (
    add_candidate_demand_coverage,
    build_offline_product_candidate_graph,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build an exhaustive offline product hard-gate graph"
    )
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--relations", type=Path, required=True)
    parser.add_argument("--relation-manifest", type=Path, required=True)
    parser.add_argument("--demands", type=Path)
    parser.add_argument("--allow-unapproved-offline", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise RuntimeError(
            f"refusing to overwrite output directory: {args.output_dir}"
        )

    relation_frame = pd.read_csv(
        args.relations,
        dtype=str,
        keep_default_na=False,
    )
    relation_manifest = json.loads(
        args.relation_manifest.read_text(encoding="utf-8")
    )
    payload = build_function_relation_runtime_payload(
        relation_frame,
        relation_manifest,
    )
    if (
        payload["deploymentStatus"] != "APPROVED"
        and not args.allow_unapproved_offline
    ):
        raise RuntimeError(
            "relation artifact is unapproved; pass --allow-unapproved-offline "
            "only for an explicitly offline diagnostic"
        )
    registry = function_relation_registry_from_payload(
        payload,
        require_approved=not args.allow_unapproved_offline,
    )
    pairs, sources, summary = build_offline_product_candidate_graph(
        pd.read_csv(args.profiles, dtype=str, keep_default_na=False),
        registry,
    )
    if args.demands is not None:
        summary = add_candidate_demand_coverage(
            summary,
            pd.read_csv(args.demands, dtype=str, keep_default_na=False),
            sources,
        )
    manifest = {
        **summary,
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sourcePaths": {
            "profiles": str(args.profiles),
            "relations": str(args.relations),
            "relationManifest": str(args.relation_manifest),
            "demands": str(args.demands) if args.demands else None,
        },
        "usedUnapprovedRelationCandidate": (
            payload["deploymentStatus"] != "APPROVED"
        ),
        "pairFile": "eligible_product_pairs.csv",
        "sourceSummaryFile": "source_candidate_summary.csv",
    }
    args.output_dir.mkdir(parents=True)
    pairs.to_csv(
        args.output_dir / "eligible_product_pairs.csv",
        index=False,
        encoding="utf-8-sig",
    )
    sources.to_csv(
        args.output_dir / "source_candidate_summary.csv",
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

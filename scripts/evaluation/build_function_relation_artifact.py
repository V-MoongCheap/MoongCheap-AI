from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.function_relation_artifact import (
    build_function_relation_runtime_payload,
    compile_function_relation_artifact,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile adjudicated function relations into a runtime candidate"
    )
    parser.add_argument("--base-status", type=Path, required=True)
    parser.add_argument("--pilot-status", type=Path, required=True)
    parser.add_argument("--full-status", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument(
        "--artifact-version",
        default="mfds-function-coverage-relations-v1",
    )
    parser.add_argument("--rule-version", default="v3")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise RuntimeError(f"refusing to overwrite output directory: {args.output_dir}")

    source_paths = {
        "BASE_SAFETY_AUDITED": args.base_status,
        "CANDIDATE_PILOT_V3": args.pilot_status,
        "CANDIDATE_FULL_V3": args.full_status,
    }
    named_statuses = {
        name: pd.read_csv(path, dtype=str, keep_default_na=False)
        for name, path in source_paths.items()
    }
    audit, artifact, summary = compile_function_relation_artifact(
        named_statuses,
        candidate_directions=pd.read_csv(
            args.candidates,
            dtype=str,
            keep_default_na=False,
        ),
        artifact_version=args.artifact_version,
        rule_version=args.rule_version,
    )
    manifest = {
        **summary,
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sourcePaths": {
            name: str(path) for name, path in source_paths.items()
        },
        "candidatePath": str(args.candidates),
        "auditFile": "relation_status_audit.csv",
        "artifactFile": "coverage_relations_candidate.csv",
        "runtimeArtifactFile": "coverage_relations_candidate.json",
    }
    args.output_dir.mkdir(parents=True)
    audit.to_csv(
        args.output_dir / "relation_status_audit.csv",
        index=False,
        encoding="utf-8-sig",
    )
    artifact.to_csv(
        args.output_dir / "coverage_relations_candidate.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (args.output_dir / "coverage_relations_candidate.json").write_text(
        json.dumps(
            build_function_relation_runtime_payload(artifact, summary),
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()

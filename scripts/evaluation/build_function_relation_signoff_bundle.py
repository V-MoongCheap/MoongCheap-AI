from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.function_relation_signoff import (
    build_function_relation_signoff_bundle,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the offline domain sign-off queue for COVERS relations"
    )
    parser.add_argument("--relations", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise RuntimeError(
            f"refusing to overwrite output directory: {args.output_dir}"
        )

    bundle, summary = build_function_relation_signoff_bundle(
        pd.read_csv(args.relations, dtype=str, keep_default_na=False),
        pd.read_csv(args.audit, dtype=str, keep_default_na=False),
    )
    manifest = {
        **summary,
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "relationsPath": str(args.relations),
        "auditPath": str(args.audit),
        "signoffFile": "relation_signoff_queue.csv",
    }
    args.output_dir.mkdir(parents=True)
    bundle.to_csv(
        args.output_dir / "relation_signoff_queue.csv",
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

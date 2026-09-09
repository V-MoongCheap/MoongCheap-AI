"""Build validated, non-sending Backend requests from one simulation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from moongcheap_ai.demand_clustering.evaluation.backend_requests import (
    build_backend_plan_request_bundle,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build dry-run substitute admission API requests"
    )
    parser.add_argument("--simulation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")

    simulation = json.loads(args.simulation.read_text(encoding="utf-8"))
    bundle = build_backend_plan_request_bundle(simulation)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(args.output),
        "requestCount": bundle["requestCount"],
        "proposalCount": bundle["proposalCount"],
        "mode": "DRY_RUN_NO_HTTP",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Build a non-sending two-stage Backend handoff from one simulation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from moongcheap_ai.demand_clustering.evaluation.backend_requests import (
    build_backend_plan_request_bundle,
    build_board_plan_request_bundle_from_simulation,
)
from moongcheap_ai.demand_clustering.backend_board_plan import (
    BOARD_PLAN_ENDPOINT_PROPOSAL,
)
from moongcheap_ai.demand_clustering.backend_plan_client import (
    PLAN_ENDPOINT,
)


HANDOFF_SCHEMA_VERSION = "demand-clustering-backend-handoff.v0.1"


def build_handoff(simulation: dict[str, object]) -> dict[str, object]:
    board_bundle = build_board_plan_request_bundle_from_simulation(simulation)
    substitute_bundle = build_backend_plan_request_bundle(simulation)
    summary = simulation["summary"]
    return {
        "schemaVersion": HANDOFF_SCHEMA_VERSION,
        "mode": "DRY_RUN_NO_HTTP_SYNTHETIC_IDS",
        "sourceSimulationSchema": simulation["schemaVersion"],
        "executionOrder": [
            {
                "step": 1,
                "name": "APPLY_DIRECT_BOARD_PLAN",
                "proposedEndpoint": BOARD_PLAN_ENDPOINT_PROPOSAL,
                "requestBundle": board_bundle,
            },
            {
                "step": 2,
                "name": "REFRESH_BACKEND_BOARD_STATE",
                "reason": "resolve clientBoardKey to Backend demandBoardId",
            },
            {
                "step": 3,
                "name": "APPLY_SUBSTITUTE_OFFER_PLAN",
                "draftEndpoint": PLAN_ENDPOINT,
                "requestBundle": substitute_bundle,
            },
        ],
        "summary": {
            "sourceDemandCount": summary["sourceDemandCount"],
            "newBoardCount": board_bundle["newBoardCount"],
            "directAssignedDemandCount": board_bundle[
                "directAssignedDemandCount"
            ],
            "substituteProposalCount": substitute_bundle["proposalCount"],
            "expiredDemandCount": summary["expiredDemandCount"],
            "runtimeReviewCount": summary["reviewQueueCount"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the complete dry-run Backend handoff bundle"
    )
    parser.add_argument("--simulation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")

    simulation = json.loads(args.simulation.read_text(encoding="utf-8"))
    result = build_handoff(simulation)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(args.output),
        "mode": result["mode"],
        **result["summary"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

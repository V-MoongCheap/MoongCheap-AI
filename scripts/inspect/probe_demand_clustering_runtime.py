"""Offline component smoke/resource probe; never connects to DB or Backend.

This measures initialization, parsing, and E5 encoding, not a complete batch
or worst-case candidate fan-out. Mount this script into the runtime image.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import sys
import time
from pathlib import Path


def positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def memory_snapshot() -> dict[str, float | None]:
    peak_path = Path("/sys/fs/cgroup/memory.peak")
    try:
        cgroup_peak = int(peak_path.read_text().strip()) / 1024**2
    except (OSError, ValueError):
        cgroup_peak = None
    return {
        "processPeakRssMiB": round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2
        ),
        "cgroupPeakMiB": round(cgroup_peak, 2) if cgroup_peak is not None else None,
    }


def main() -> int:
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--profiles", type=Path, required=True)
    arguments.add_argument("--taxonomy", type=Path, required=True)
    arguments.add_argument("--model", type=Path, required=True)
    arguments.add_argument("--query-count", type=positive_integer, default=100)
    arguments.add_argument("--passage-count", type=positive_integer, default=100)
    arguments.add_argument("--batch-size", type=positive_integer, default=32)
    arguments.add_argument(
        "--rules", type=Path,
        default=Path(os.environ.get(
            "DEMAND_CONSTRAINT_RULES_PATH", "config/demand_constraint_rules.json"
        )),
    )
    arguments.add_argument(
        "--aliases", type=Path,
        default=os.environ.get(
            "DEMAND_CONSTRAINT_ALIASES_PATH", "config/model1_aliases_reviewed_v2.json"
        ) or None,
    )
    arguments.add_argument("--without-a-aliases", dest="aliases", action="store_const", const=None)
    arguments.add_argument(
        "--compatibility-aliases", type=Path,
        default=os.environ.get("DEMAND_CONSTRAINT_COMPAT_ALIASES_PATH", "config/demand_constraint_aliases.json"),
    )
    args = arguments.parse_args()
    if platform.system() != "Linux":
        arguments.error("resource units and container checks require Linux")
    if not args.model.is_dir():
        arguments.error("--model must be an existing local E5 directory")
    if os.environ.get("HF_HUB_OFFLINE") != "1":
        arguments.error("set HF_HUB_OFFLINE=1; model downloads are not allowed")

    start = time.perf_counter()
    phases: dict[str, dict[str, float | None]] = {}
    previous = start

    def checkpoint(name: str) -> None:
        nonlocal previous
        current = time.perf_counter()
        phases[name] = {
            "seconds": round(current - previous, 3),
            **memory_snapshot(),
        }
        previous = current
        print(json.dumps({"phase": name, **phases[name]}), file=sys.stderr)

    import pandas as pd
    import psycopg

    from moongcheap_ai.demand_clustering.e5_runtime_scorer import (
        E5RuntimeScorerConfig,
        E5RuntimeTextSimilarityScorer,
    )
    from moongcheap_ai.demand_clustering.substitute_proposal_planner import (
        ClaimIndexedSubstituteProposalPlanner,
        build_runtime_catalog_profiles,
    )
    from moongcheap_ai.demand_clustering.part_a_integration import (
        build_part_b_parser, validate_profile_versions,
    )

    profiles = pd.read_csv(args.profiles, dtype=str).fillna("")
    if profiles.empty:
        arguments.error("--profiles must contain at least one catalog")
    taxonomy = json.loads(args.taxonomy.read_text(encoding="utf-8"))
    checkpoint("importsAndArtifactRead")

    validate_profile_versions(profiles, taxonomy)
    parser, integration = build_part_b_parser(
        taxonomy, rules_path=args.rules, aliases_path=args.aliases,
        compatibility_aliases_path=args.compatibility_aliases,
    )
    scorer = E5RuntimeTextSimilarityScorer(E5RuntimeScorerConfig(
        model_path=args.model, batch_size=args.batch_size,
    ))
    planner = ClaimIndexedSubstituteProposalPlanner(
        profiles, taxonomy, parser, text_similarity_scorer=scorer,
    )
    checkpoint("parserAndPlannerInitialization")

    category = str(profiles.iloc[0]["service_category_id"])
    queries = [
        f"휴대하기 편하고 부담 없이 먹을 수 있으면 좋겠어요. 사용 상황 {index}"
        for index in range(args.query_count)
    ]
    for query in queries:
        parser.interpret(category, query, is_substitutable=True)
    checkpoint("requirementParsing")

    sampled_profiles = build_runtime_catalog_profiles(
        profiles.head(args.passage_count), taxonomy,
    )
    passages = [profile.semantic_text for profile in sampled_profiles.values()]
    scorer.prepare(queries, passages)
    score = scorer(queries[0], passages[0])
    if not scorer.model_loaded or not 0 <= score <= 1:
        raise RuntimeError("E5 smoke verification failed")
    import torch

    if torch.version.cuda is not None or torch.version.hip is not None:
        raise RuntimeError("this probe expects a CPU-only PyTorch installation")
    checkpoint("e5LoadAndEncoding")

    usage = resource.getrusage(resource.RUSAGE_SELF)
    print(json.dumps({
        "scope": "OFFLINE_COMPONENT_PROBE_NOT_FULL_BATCH",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "uid": os.getuid(),
        "torch": torch.__version__,
        "torchThreads": torch.get_num_threads(),
        "psycopg": psycopg.__version__,
        "index": dict(planner.index_summary),
        "taxonomyCategoryCount": len(taxonomy["categories"]),
        "partAIntegration": integration,
        "parserInputCount": len(queries),
        "requestedPassageCount": args.passage_count,
        "e5BatchSize": args.batch_size,
        "e5": dict(scorer.cache_summary),
        "sampleScore": score,
        "elapsedSeconds": round(time.perf_counter() - start, 3),
        "processCpuSeconds": round(usage.ru_utime + usage.ru_stime, 3),
        **memory_snapshot(),
        "phases": phases,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

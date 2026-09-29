"""Reject unapproved changes to shared demand-clustering policy in Part A PRs.

This is intentionally small and dependency-free so it can run in CI before the
full test suite. A shared policy change is allowed only when the PR explicitly
records that B-part approval was obtained.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Sequence


SHARED_POLICY_PATHS = (
    "src/moongcheap_ai/demand_constraints/input_policy.py",
    "src/moongcheap_ai/demand_constraints/extractor.py",
    "src/moongcheap_ai/demand_constraints/classifier.py",
    "src/moongcheap_ai/demand_constraints/taxonomy_matcher.py",
)
# These files are owned by Part B. Keeping them out of a Part A PR prevents
# unrelated runtime/deployment changes from being coupled to labeling work.
# A cross-part change must be moved to a B PR or reviewed as a separate change.
PART_B_OWNED_PATHS = (
    "src/moongcheap_ai/demand_clustering/runtime_job.py",
    "src/moongcheap_ai/demand_clustering/part_a_integration.py",
    "src/moongcheap_ai/demand_clustering/README.md",
    "docker/Dockerfile.demand-clustering",
    "docker/Dockerfile.demand-clustering.dockerignore",
    "packaging/demand-clustering/README.md",
    "packaging/demand-clustering/runtime-assets/README.md",
    "k8s/base/demand-clustering-job/cronjob.yaml",
    "k8s/base/demand-clustering-job/kustomization.yaml",
    "k8s/README.md",
    "docs/DEMAND_CLUSTERING_CONTAINER.md",
    "docs/PART_B_V22_INTEGRATION.md",
    "docs/ci-cd-demand-clustering-handoff.yml",
    "tests/demand_clustering/test_runtime_job.py",
    "tests/deployment/test_demand_clustering_manifests.py",
    "tests/evaluation/test_build_backend_catalog_profiles.py",
    "tests/evaluation/test_build_backend_runtime_profiles_from_exports.py",
    "tests/evaluation/test_build_backend_seed_exports.py",
    "tests/data_foundation/test_backend_catalog_mapping.py",
    "scripts/data/build_backend_catalog_mapping.py",
    "scripts/evaluation/build_backend_catalog_profiles.py",
    "scripts/evaluation/build_backend_runtime_profiles_from_exports.py",
    "scripts/evaluation/build_backend_seed_exports.py",
)
APPROVAL_MARKER = "shared-policy-approved"


def changed_files(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def shared_policy_changes(files: Sequence[str]) -> list[str]:
    return [path for path in files if path in SHARED_POLICY_PATHS]


def part_b_changes(files: Sequence[str]) -> list[str]:
    return [path for path in files if path in PART_B_OWNED_PATHS]


def validate_scope(
    files: Sequence[str], *, pr_body: str = "", allow_shared: bool = False
) -> list[str]:
    owned_by_b = part_b_changes(files)
    if owned_by_b:
        errors = [
            "Part A PR changes Part B-owned files: " + ", ".join(owned_by_b),
            "Move these changes to a Part B PR or split the PR before review.",
        ]
    else:
        errors = []
    changed = shared_policy_changes(files)
    if not changed:
        return errors
    approved = allow_shared or bool(
        re.search(
            rf"(?im)^\s*-\s*\[x\]\s*`{re.escape(APPROVAL_MARKER)}`",
            pr_body,
        )
    )
    if approved:
        return errors
    return errors + [
        "Part A PR changes shared demand policy without B approval: "
        + ", ".join(changed),
        f"Check `[{APPROVAL_MARKER}]` in the PR body only after B-part policy review, "
        "or move the shared-policy change to a separate PR.",
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="origin/develop")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--allow-shared", action="store_true")
    args = parser.parse_args(argv)

    files = changed_files(args.base, args.head)
    errors = validate_scope(
        files,
        pr_body=os.environ.get("PR_BODY", ""),
        allow_shared=args.allow_shared,
    )
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors), file=sys.stderr)
        return 1
    print("Part A PR scope check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

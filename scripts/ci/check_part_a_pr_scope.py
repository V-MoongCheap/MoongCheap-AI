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


def validate_scope(
    files: Sequence[str], *, pr_body: str = "", allow_shared: bool = False
) -> list[str]:
    changed = shared_policy_changes(files)
    if not changed:
        return []
    approved = allow_shared or bool(
        re.search(
            rf"(?im)^\s*-\s*\[x\]\s*`{re.escape(APPROVAL_MARKER)}`",
            pr_body,
        )
    )
    if approved:
        return []
    return [
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

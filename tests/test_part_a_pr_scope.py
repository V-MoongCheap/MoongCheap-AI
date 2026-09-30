from __future__ import annotations

from scripts.ci.check_part_a_pr_scope import validate_scope


def test_part_a_changes_without_shared_policy_are_allowed() -> None:
    assert validate_scope(["src/moongcheap_ai/data_foundation/model1.py"]) == []


def test_unapproved_shared_policy_change_is_rejected() -> None:
    errors = validate_scope(["src/moongcheap_ai/demand_constraints/input_policy.py"])
    assert errors
    assert "B approval" in errors[0]


def test_shared_policy_change_requires_explicit_marker() -> None:
    assert validate_scope(
        ["src/moongcheap_ai/demand_constraints/input_policy.py"],
        pr_body="- [ ] `shared-policy-approved`",
    )
    assert validate_scope(
        ["src/moongcheap_ai/demand_constraints/input_policy.py"],
        pr_body="- [x] `shared-policy-approved`",
    ) == []


def test_part_b_runtime_change_is_allowed_in_a_shared_repository() -> None:
    assert validate_scope(["docker/Dockerfile.demand-clustering"]) == []


def test_mixed_part_changes_are_allowed_when_shared_policy_is_unchanged() -> None:
    assert validate_scope(
        [
            "src/moongcheap_ai/data_foundation/model1.py",
            "src/moongcheap_ai/demand_clustering/runtime_job.py",
            "docker/Dockerfile.seller-analysis",
        ]
    ) == []

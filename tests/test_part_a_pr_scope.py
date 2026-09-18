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

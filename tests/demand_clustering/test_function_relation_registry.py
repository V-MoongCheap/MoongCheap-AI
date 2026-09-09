from __future__ import annotations

import copy

import pandas as pd
import pytest

from moongcheap_ai.demand_clustering.evaluation.function_relation_artifact import (
    build_function_relation_runtime_payload,
    function_direction_id,
    function_relation_artifact_fingerprint,
)
from moongcheap_ai.demand_clustering.function_relation_registry import (
    function_relation_registry_from_payload,
)


def _payload(deployment_status: str = "APPROVED") -> dict[str, object]:
    artifact = pd.DataFrame([{
        "relation_id": function_direction_id("source", "candidate"),
        "source_claim_id": "source",
        "source_claim_text": "source text",
        "candidate_claim_id": "candidate",
        "candidate_claim_text": "candidate text",
        "coverage_label": "COVERS",
        "rule_version": "v3",
        "artifact_version": "artifact-v1",
        "decision_reason_code": "SAME_ENDPOINT_EQUIVALENT_WORDING",
        "decision_provenance": "TEST",
    }])
    summary = {
        "schemaVersion": "mfds-function-coverage-relation-artifact.v1",
        "artifactVersion": "artifact-v1",
        "ruleVersion": "v3",
        "artifactFingerprintSha256": function_relation_artifact_fingerprint(
            artifact
        ),
        "deploymentStatus": deployment_status,
        "goldStatus": "TEST",
        "identityPolicy": "identity",
        "transitivityPolicy": "none",
        "runtimePolicy": "approved explicit edges only",
    }
    return build_function_relation_runtime_payload(artifact, summary)


def test_registry_uses_identity_and_explicit_direction_only() -> None:
    registry = function_relation_registry_from_payload(_payload())

    assert registry.covers("source", "source")
    assert registry.covers("source", "candidate")
    assert not registry.covers("candidate", "source")
    resolution = registry.resolve(
        ("source", "uncovered"),
        ("candidate",),
    )
    assert resolution.covered_by == (("source", "candidate"),)
    assert resolution.missing_source_claim_ids == ("uncovered",)


def test_runtime_loader_rejects_candidate_without_domain_signoff() -> None:
    with pytest.raises(ValueError, match="not approved"):
        function_relation_registry_from_payload(
            _payload("REQUIRES_DOMAIN_OWNER_SIGNOFF")
        )


def test_runtime_loader_rejects_tampered_artifact() -> None:
    payload = copy.deepcopy(_payload())
    payload["relations"][0]["sourceClaimText"] = "tampered"

    with pytest.raises(ValueError, match="fingerprint mismatch"):
        function_relation_registry_from_payload(payload)

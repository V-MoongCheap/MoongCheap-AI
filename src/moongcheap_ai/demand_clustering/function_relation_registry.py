"""Validated runtime lookup for approved directional function relations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .function_relation_contract import (
    ARTIFACT_COLUMNS,
    function_direction_id,
    function_relation_artifact_fingerprint,
)


RUNTIME_SCHEMA_VERSION = "mfds-function-coverage-relation-artifact.v1"


@dataclass(frozen=True, slots=True)
class FunctionCoverageResolution:
    """Witnesses showing how every source claim was or was not covered."""

    covered_by: tuple[tuple[str, str], ...]
    missing_source_claim_ids: tuple[str, ...]

    @property
    def fully_covered(self) -> bool:
        return not self.missing_source_claim_ids


@dataclass(frozen=True, slots=True)
class FunctionCoverageRelationRegistry:
    """Immutable identity-or-explicit-edge relation registry."""

    artifact_version: str
    rule_version: str
    artifact_fingerprint_sha256: str
    edges: frozenset[tuple[str, str]]

    def covers(self, source_claim_id: str, candidate_claim_id: str) -> bool:
        source = str(source_claim_id).strip()
        candidate = str(candidate_claim_id).strip()
        if not source or not candidate:
            raise ValueError("claim IDs must not be blank")
        return source == candidate or (source, candidate) in self.edges

    def __call__(self, source_claim_id: str, candidate_claim_id: str) -> bool:
        return self.covers(source_claim_id, candidate_claim_id)

    def resolve(
        self,
        source_claim_ids: tuple[str, ...],
        candidate_claim_ids: tuple[str, ...],
    ) -> FunctionCoverageResolution:
        """Resolve all source claims without inferring transitive edges."""

        sources = tuple(sorted({value.strip() for value in source_claim_ids}))
        candidates = tuple(sorted({value.strip() for value in candidate_claim_ids}))
        if any(not value for value in (*sources, *candidates)):
            raise ValueError("claim IDs must not be blank")
        covered_by = []
        missing = []
        for source in sources:
            witness = next(
                (
                    candidate
                    for candidate in candidates
                    if self.covers(source, candidate)
                ),
                None,
            )
            if witness is None:
                missing.append(source)
            else:
                covered_by.append((source, witness))
        return FunctionCoverageResolution(tuple(covered_by), tuple(missing))


def _require_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a nonblank string")
    return value.strip()


def function_relation_registry_from_payload(
    payload: Mapping[str, Any],
    *,
    require_approved: bool = True,
) -> FunctionCoverageRelationRegistry:
    """Validate a JSON-contract payload and return an immutable registry."""

    if payload.get("schemaVersion") != RUNTIME_SCHEMA_VERSION:
        raise ValueError("unsupported function relation schemaVersion")
    artifact_version = _require_string(payload, "artifactVersion")
    rule_version = _require_string(payload, "ruleVersion")
    fingerprint = _require_string(payload, "artifactFingerprintSha256")
    deployment_status = _require_string(payload, "deploymentStatus")
    if require_approved and deployment_status != "APPROVED":
        raise ValueError(
            "function relation artifact is not approved for runtime loading"
        )
    raw_relations = payload.get("relations")
    if not isinstance(raw_relations, list):
        raise ValueError("relations must be an array")

    rows = []
    relation_ids = set()
    edges = set()
    for index, raw_relation in enumerate(raw_relations):
        if not isinstance(raw_relation, Mapping):
            raise ValueError(f"relations[{index}] must be an object")
        relation_id = _require_string(raw_relation, "relationId")
        source_id = _require_string(raw_relation, "sourceClaimId")
        candidate_id = _require_string(raw_relation, "candidateClaimId")
        if source_id == candidate_id:
            raise ValueError("identity directions must not be stored as edges")
        if relation_id != function_direction_id(source_id, candidate_id):
            raise ValueError(f"invalid relationId: {relation_id}")
        if relation_id in relation_ids or (source_id, candidate_id) in edges:
            raise ValueError("relation IDs and directed edges must be unique")
        if raw_relation.get("coverageLabel") != "COVERS":
            raise ValueError("runtime artifact may contain only COVERS relations")
        if raw_relation.get("artifactVersion") != artifact_version:
            raise ValueError("relation artifactVersion disagrees with envelope")
        if raw_relation.get("ruleVersion") != rule_version:
            raise ValueError("relation ruleVersion disagrees with envelope")

        relation_ids.add(relation_id)
        edges.add((source_id, candidate_id))
        rows.append({
            "relation_id": relation_id,
            "source_claim_id": source_id,
            "source_claim_text": str(raw_relation.get("sourceClaimText", "")),
            "candidate_claim_id": candidate_id,
            "candidate_claim_text": str(
                raw_relation.get("candidateClaimText", "")
            ),
            "coverage_label": "COVERS",
            "rule_version": rule_version,
            "artifact_version": artifact_version,
            "decision_reason_code": str(
                raw_relation.get("decisionReasonCode", "")
            ),
            "decision_provenance": str(
                raw_relation.get("decisionProvenance", "")
            ),
        })

    frame = pd.DataFrame(rows, columns=ARTIFACT_COLUMNS)
    actual_fingerprint = function_relation_artifact_fingerprint(frame)
    if actual_fingerprint != fingerprint:
        raise ValueError("function relation artifact fingerprint mismatch")
    return FunctionCoverageRelationRegistry(
        artifact_version=artifact_version,
        rule_version=rule_version,
        artifact_fingerprint_sha256=fingerprint,
        edges=frozenset(edges),
    )


def load_function_relation_registry(
    path: str | Path,
    *,
    require_approved: bool = True,
) -> FunctionCoverageRelationRegistry:
    """Load the versioned Backend JSON artifact from disk."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("function relation artifact root must be an object")
    return function_relation_registry_from_payload(
        payload,
        require_approved=require_approved,
    )

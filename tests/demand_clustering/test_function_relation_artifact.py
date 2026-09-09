from __future__ import annotations

import hashlib

import pandas as pd
import pytest

from moongcheap_ai.demand_clustering.evaluation.function_relation_artifact import (
    compile_function_relation_artifact,
)


def _direction_id(source: str, candidate: str) -> str:
    digest = hashlib.sha256(f"{source}->{candidate}".encode()).hexdigest()
    return f"MFDS-FDIR-{digest[:16].upper()}"


def _status(source: str, candidate: str, label: str) -> pd.DataFrame:
    return pd.DataFrame([{
        "direction_id": _direction_id(source, candidate),
        "source_claim_id": source,
        "source_claim_text": f"text {source}",
        "candidate_claim_id": candidate,
        "candidate_claim_text": f"text {candidate}",
        "final_coverage_label": label,
        "final_reason_code": "SAME" if label == "COVERS" else "DIFFERENT",
    }])


def test_compiles_covers_only_artifact_and_keeps_negative_audit() -> None:
    covers = _status("a", "b", "COVERS")
    negative = _status("b", "a", "DOES_NOT_COVER")
    candidates = pd.DataFrame({
        "direction_id": [
            covers.at[0, "direction_id"],
            negative.at[0, "direction_id"],
        ]
    })

    audit, artifact, summary = compile_function_relation_artifact(
        {"FIRST": covers, "SECOND": negative},
        candidate_directions=candidates,
    )

    assert len(audit) == 2
    assert artifact["source_claim_id"].tolist() == ["a"]
    assert artifact.at[0, "coverage_label"] == "COVERS"
    assert summary["coversRelations"] == 1
    assert summary["candidateSetDecisionsComplete"]
    assert summary["candidateSetDoesNotCover"] == 1
    assert summary["deploymentStatus"] == "REQUIRES_DOMAIN_OWNER_SIGNOFF"


def test_rejects_overlapping_status_sources() -> None:
    status = _status("a", "b", "COVERS")

    with pytest.raises(ValueError, match="overlap direction IDs"):
        compile_function_relation_artifact({"FIRST": status, "SECOND": status})

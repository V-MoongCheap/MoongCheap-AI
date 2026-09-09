"""Shared schema, IDs and fingerprints for approved function-relation artifacts."""

from __future__ import annotations

import hashlib

import pandas as pd


ARTIFACT_COLUMNS = [
    "relation_id",
    "source_claim_id",
    "source_claim_text",
    "candidate_claim_id",
    "candidate_claim_text",
    "coverage_label",
    "rule_version",
    "artifact_version",
    "decision_reason_code",
    "decision_provenance",
]


def function_direction_id(source_claim_id: str, candidate_claim_id: str) -> str:
    key = f"{source_claim_id}->{candidate_claim_id}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16].upper()
    return f"MFDS-FDIR-{digest}"


def function_relation_artifact_fingerprint(frame: pd.DataFrame) -> str:
    """Return the semantic fingerprint used by CSV and JSON artifacts."""

    if missing := sorted(set(ARTIFACT_COLUMNS) - set(frame.columns)):
        raise ValueError(
            "relation artifact missing fingerprint columns: "
            + ", ".join(missing)
        )
    canonical = frame.loc[:, ARTIFACT_COLUMNS].fillna("").astype(str).sort_values(
        ARTIFACT_COLUMNS,
        kind="stable",
    )
    payload = "\n".join(
        "\x1f".join(row)
        for row in canonical.itertuples(index=False, name=None)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

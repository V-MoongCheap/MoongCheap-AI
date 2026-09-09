"""Shared eligibility contract for runtime and offline catalog profiles."""

SUBSTITUTION_EVIDENCE_READY_STATUSES = frozenset({
    "CANDIDATE_READY",  # v1 artifact compatibility
    "EVIDENCE_READY",
})

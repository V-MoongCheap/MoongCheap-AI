import json

import pandas as pd
import pytest

from moongcheap_ai.demand_clustering.claim_containment_index import (
    IdentityClaimContainmentIndex,
)


def _profile(
    catalog_id: str,
    category: str,
    claims: list[str],
    status: str = "EVIDENCE_READY",
) -> dict[str, str]:
    return {
        "catalog_id": catalog_id,
        "service_category_id": category,
        "profile_status": status,
        "main_functionality_claim_ids_json": json.dumps(claims),
    }


def test_lookup_uses_same_category_and_claim_set_inclusion() -> None:
    index = IdentityClaimContainmentIndex(pd.DataFrame([
        _profile("source", "probiotics", ["gut", "bowel"]),
        _profile("superset", "probiotics", ["gut", "bowel", "immune"]),
        _profile("exact", "probiotics", ["bowel", "gut"]),
        _profile("partial", "probiotics", ["gut"]),
        _profile("other-category", "vitamin", ["gut", "bowel"]),
        _profile(
            "insufficient",
            "probiotics",
            ["gut", "bowel"],
            "INSUFFICIENT_EVIDENCE",
        ),
    ]))

    result = index.lookup("source")

    assert result.source_profile_status == "EVIDENCE_READY"
    assert result.source_claim_ids == ("bowel", "gut")
    assert result.candidate_catalog_ids == ("exact", "superset")
    assert index.summary["pairMaterialization"] == "NONE"
    assert index.summary["indexedEvidenceReadyProfiles"] == 5


def test_lookup_can_be_bounded_to_active_board_catalogs() -> None:
    index = IdentityClaimContainmentIndex(pd.DataFrame([
        _profile("source", "probiotics", ["gut"]),
        _profile("active-match", "probiotics", ["gut", "immune"]),
        _profile("inactive-match", "probiotics", ["gut"]),
        _profile("active-nonmatch", "probiotics", ["immune"]),
    ]))

    result = index.lookup(
        "source",
        candidate_catalog_ids=["active-match", "active-nonmatch", "missing"],
    )

    assert result.candidate_catalog_ids == ("active-match",)


def test_lookup_reports_missing_or_insufficient_source_without_candidates() -> None:
    index = IdentityClaimContainmentIndex(pd.DataFrame([
        _profile(
            "insufficient",
            "probiotics",
            [],
            "INSUFFICIENT_EVIDENCE",
        ),
    ]))

    insufficient = index.lookup("insufficient")
    missing = index.lookup("missing")

    assert insufficient.source_profile_status == "INSUFFICIENT_EVIDENCE"
    assert insufficient.candidate_catalog_ids == ()
    assert missing.source_profile_status == "PROFILE_NOT_FOUND"
    assert missing.candidate_catalog_ids == ()


def test_index_rejects_duplicate_catalog_ids() -> None:
    profiles = pd.DataFrame([
        _profile("duplicate", "probiotics", ["gut"]),
        _profile("duplicate", "probiotics", ["gut"]),
    ])

    with pytest.raises(ValueError, match="must be unique"):
        IdentityClaimContainmentIndex(profiles)

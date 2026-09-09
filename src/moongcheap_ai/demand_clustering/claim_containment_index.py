"""CPU lookup index for identity claim-containment candidates.

The index deliberately avoids materializing every directed product pair.
Production callers should normally restrict a lookup to catalog IDs that have
an active demand board, then rank the returned candidates separately.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd

from .profile_contract import SUBSTITUTION_EVIDENCE_READY_STATUSES


PROFILE_COLUMNS = {
    "catalog_id",
    "service_category_id",
    "profile_status",
    "main_functionality_claim_ids_json",
}


@dataclass(frozen=True)
class ClaimContainmentLookup:
    """One source product's deterministic identity-coverage result."""

    source_catalog_id: str
    source_profile_status: str
    source_claim_ids: tuple[str, ...]
    candidate_catalog_ids: tuple[str, ...]


@dataclass(frozen=True)
class _IndexedProfile:
    catalog_id: str
    service_category_id: str
    claim_ids: frozenset[str]


def _claim_ids(value: object) -> frozenset[str]:
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as error:
        raise ValueError("function claim IDs must be a JSON array") from error
    if not isinstance(parsed, list):
        raise ValueError("function claim IDs must be a JSON array")
    normalized = frozenset(str(item).strip() for item in parsed)
    if not normalized or "" in normalized:
        raise ValueError("evidence-ready profiles require nonblank claim IDs")
    return normalized


class IdentityClaimContainmentIndex:
    """Find same-category candidates whose claim set covers the source set.

    Coverage is identity-only: every source claim ID must occur unchanged in
    the candidate claim set. Approved directional claim relations can be added
    as a separate policy later without weakening this baseline.
    """

    def __init__(self, profiles: pd.DataFrame) -> None:
        if missing := sorted(PROFILE_COLUMNS - set(profiles.columns)):
            raise ValueError("profiles missing columns: " + ", ".join(missing))

        normalized = profiles.fillna("").copy()
        normalized["catalog_id"] = normalized["catalog_id"].astype(str).str.strip()
        if normalized["catalog_id"].eq("").any():
            raise ValueError("profile catalog IDs must not be blank")
        if normalized["catalog_id"].duplicated().any():
            raise ValueError("profile catalog IDs must be unique")

        self._status_by_catalog = {
            str(row.catalog_id): str(row.profile_status)
            for row in normalized.itertuples(index=False)
        }
        self._profiles: dict[str, _IndexedProfile] = {}
        mutable_postings: dict[tuple[str, str], set[str]] = {}

        ready = normalized.loc[
            normalized["profile_status"].isin(
                SUBSTITUTION_EVIDENCE_READY_STATUSES
            )
        ]
        for row in ready.itertuples(index=False):
            catalog_id = str(row.catalog_id)
            category = str(row.service_category_id).strip()
            if not category:
                raise ValueError(
                    "evidence-ready profile categories must not be blank"
                )
            claims = _claim_ids(row.main_functionality_claim_ids_json)
            self._profiles[catalog_id] = _IndexedProfile(
                catalog_id=catalog_id,
                service_category_id=category,
                claim_ids=claims,
            )
            for claim_id in claims:
                mutable_postings.setdefault((category, claim_id), set()).add(
                    catalog_id
                )

        self._postings = {
            key: frozenset(catalog_ids)
            for key, catalog_ids in mutable_postings.items()
        }
        self._summary: dict[str, Any] = {
            "schemaVersion": "identity-claim-containment-index.v1",
            "coveragePolicy": "IDENTITY_CLAIM_SUBSET_ONLY",
            "profileRows": int(len(normalized)),
            "indexedEvidenceReadyProfiles": int(len(self._profiles)),
            "excludedProfiles": int(len(normalized) - len(self._profiles)),
            "categoryCount": len({
                profile.service_category_id
                for profile in self._profiles.values()
            }),
            "uniqueClaimCount": len({
                claim_id for _, claim_id in self._postings
            }),
            "postingMembershipCount": sum(
                len(profile.claim_ids) for profile in self._profiles.values()
            ),
            "pairMaterialization": "NONE",
        }

    @property
    def summary(self) -> dict[str, Any]:
        return dict(self._summary)

    def lookup(
        self,
        source_catalog_id: object,
        *,
        candidate_catalog_ids: Iterable[object] | None = None,
        include_source: bool = False,
    ) -> ClaimContainmentLookup:
        """Return deterministic candidates, optionally limited to active IDs."""

        source_id = str(source_catalog_id).strip()
        source = self._profiles.get(source_id)
        source_status = self._status_by_catalog.get(
            source_id,
            "PROFILE_NOT_FOUND",
        )
        if source is None:
            return ClaimContainmentLookup(
                source_catalog_id=source_id,
                source_profile_status=source_status,
                source_claim_ids=(),
                candidate_catalog_ids=(),
            )

        if candidate_catalog_ids is None:
            posting_sets = [
                self._postings[(source.service_category_id, claim_id)]
                for claim_id in source.claim_ids
            ]
            matches = set(min(posting_sets, key=len))
            for posting in posting_sets:
                matches.intersection_update(posting)
        else:
            matches = set()
            for raw_candidate_id in candidate_catalog_ids:
                candidate_id = str(raw_candidate_id).strip()
                candidate = self._profiles.get(candidate_id)
                if (
                    candidate is not None
                    and candidate.service_category_id
                    == source.service_category_id
                    and source.claim_ids.issubset(candidate.claim_ids)
                ):
                    matches.add(candidate_id)

        if not include_source:
            matches.discard(source_id)
        return ClaimContainmentLookup(
            source_catalog_id=source_id,
            source_profile_status=source_status,
            source_claim_ids=tuple(sorted(source.claim_ids)),
            candidate_catalog_ids=tuple(sorted(matches)),
        )

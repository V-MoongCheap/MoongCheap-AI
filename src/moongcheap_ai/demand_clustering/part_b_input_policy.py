"""Part B-only input normalization layered on the shared stable policy."""

from __future__ import annotations

from collections.abc import Mapping

from ..demand_constraints import ConstraintInputPolicy, TaxonomyEquivalence
from ..demand_constraints.extractor import ConstraintExtractor
from ..demand_constraints.facet_matcher import KiwiFacetMatcher


class PartBConstraintInputPolicy(ConstraintInputPolicy):
    """Preserve retired value codes only at Part B downstream boundaries."""

    def __init__(
        self,
        matcher: KiwiFacetMatcher,
        extractor: ConstraintExtractor,
        canonical_codes: Mapping[tuple[str, str, int], int],
    ) -> None:
        super().__init__(matcher, extractor)
        self._part_b_canonical_codes = dict(canonical_codes)

    def canonicalize_value_code(
        self,
        category_id: str,
        facet_name: str,
        value_code: int,
    ) -> tuple[int, TaxonomyEquivalence | None]:
        category_key = self._category_key(category_id)
        canonical_code = self._part_b_canonical_codes.get(
            (category_key, facet_name, int(value_code)),
            int(value_code),
        )
        return super().canonicalize_value_code(
            category_id,
            facet_name,
            canonical_code,
        )

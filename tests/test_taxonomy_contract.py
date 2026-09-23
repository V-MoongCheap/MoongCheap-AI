from __future__ import annotations

import pytest

from moongcheap_ai.taxonomy_contract import (
    CanonicalTaxonomyValue,
    canonical_taxonomy_values,
)


def test_deprecated_surfaces_are_redirected_to_the_active_value() -> None:
    values = [
        {"code": 1, "value": "표준값", "aliases": ["표준 별칭"]},
        {
            "code": 2,
            "value": "이전값",
            "aliases": ["이전 별칭"],
            "status": "DEPRECATED",
            "canonical_code": 1,
        },
    ]

    assert canonical_taxonomy_values(values) == (
        CanonicalTaxonomyValue(
            code=1,
            value="표준값",
            aliases=("표준 별칭", "이전값", "이전 별칭"),
        ),
    )


def test_missing_deprecated_target_fails_closed() -> None:
    values = [
        {
            "code": 2,
            "value": "이전값",
            "status": "DEPRECATED",
            "canonical_code": 99,
        }
    ]

    with pytest.raises(ValueError, match="not in the same facet"):
        canonical_taxonomy_values(values)


def test_deprecated_target_cycle_fails_closed() -> None:
    values = [
        {
            "code": 1,
            "value": "이전값 1",
            "status": "DEPRECATED",
            "canonical_code": 2,
        },
        {
            "code": 2,
            "value": "이전값 2",
            "status": "DEPRECATED",
            "canonical_code": 1,
        },
    ]

    with pytest.raises(ValueError, match="cyclic"):
        canonical_taxonomy_values(values)

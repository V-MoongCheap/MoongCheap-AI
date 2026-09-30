"""Part B-only compatibility for taxonomy values retired by Part A."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from ..demand_constraints.classifier import normalize

ROOT_CATEGORY_ID = "__root__"


@dataclass(frozen=True, slots=True)
class PartBTaxonomyCompatibility:
    """A private taxonomy copy plus flattened deprecated-code redirects."""

    taxonomy: dict[str, Any]
    canonical_codes: Mapping[tuple[str, str, int], int]

    @property
    def canonicalized_value_count(self) -> int:
        return len(self.canonical_codes)


def _aliases(value: Mapping[str, Any]) -> list[str]:
    raw = value.get("aliases", [])
    if isinstance(raw, str):
        raw = raw.split("|")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _canonicalize_facet(
    category_id: str,
    facet: dict[str, Any],
    canonical_codes: dict[tuple[str, str, int], int],
) -> None:
    facet_name = str(facet.get("name", "")).strip()
    values = facet.get("values", [])
    if not facet_name or not isinstance(values, list):
        return

    values_by_code: dict[int, dict[str, Any]] = {}
    for value in values:
        if not isinstance(value, dict):
            continue
        try:
            code = int(value["code"])
        except (KeyError, TypeError, ValueError):
            continue
        values_by_code[code] = value

    deprecated = [
        value
        for value in values_by_code.values()
        if str(value.get("status", "")).upper() == "DEPRECATED"
    ]
    for value in deprecated:
        deprecated_code = int(value["code"])
        target_code = deprecated_code
        visited = {deprecated_code}
        while True:
            target = values_by_code.get(target_code)
            if target is None:
                raise ValueError(
                    "deprecated taxonomy value references a missing canonical code: "
                    f"{category_id}/{facet_name}/{target_code}"
                )
            if str(target.get("status", "")).upper() != "DEPRECATED":
                break
            try:
                target_code = int(target["canonical_code"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    "deprecated taxonomy value requires canonical_code: "
                    f"{category_id}/{facet_name}/{deprecated_code}"
                ) from error
            if target_code in visited:
                raise ValueError(
                    "deprecated taxonomy canonical_code cycle: "
                    f"{category_id}/{facet_name}/{deprecated_code}"
                )
            visited.add(target_code)

        if target_code == 0:
            raise ValueError(
                "deprecated taxonomy value must resolve to a nonzero active value: "
                f"{category_id}/{facet_name}/{deprecated_code}"
            )
        canonical_codes[(category_id, facet_name, deprecated_code)] = target_code

        aliases = _aliases(target)
        seen = {normalize(item) for item in aliases}
        deprecated_surfaces = [str(value.get("value", "")).strip(), *_aliases(value)]
        for surface in deprecated_surfaces:
            if surface and normalize(surface) not in seen:
                aliases.append(surface)
                seen.add(normalize(surface))
        target["aliases"] = aliases

    facet["values"] = [
        value
        for value in values
        if not isinstance(value, Mapping)
        or str(value.get("status", "")).upper() != "DEPRECATED"
    ]


def prepare_part_b_taxonomy(
    taxonomy: Mapping[str, Any],
) -> PartBTaxonomyCompatibility:
    """Return a B-local view where retired values alias their active targets.

    The input is never mutated. Part A keeps using the shared matcher and its
    own input policy against the original taxonomy object.
    """

    prepared = deepcopy(dict(taxonomy))
    canonical_codes: dict[tuple[str, str, int], int] = {}

    root_facets = prepared.get("facets", [])
    if isinstance(root_facets, list):
        for facet in root_facets:
            if isinstance(facet, dict):
                _canonicalize_facet(ROOT_CATEGORY_ID, facet, canonical_codes)

    categories = prepared.get("categories", [])
    if isinstance(categories, list):
        for category in categories:
            if not isinstance(category, dict):
                continue
            category_id = str(category.get("category_id", "")).strip()
            facets = category.get("facets", [])
            if not category_id or not isinstance(facets, list):
                continue
            for facet in facets:
                if isinstance(facet, dict):
                    _canonicalize_facet(category_id, facet, canonical_codes)

    return PartBTaxonomyCompatibility(prepared, canonical_codes)

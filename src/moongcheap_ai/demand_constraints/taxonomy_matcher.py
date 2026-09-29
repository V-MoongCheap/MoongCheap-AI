"""Adapter from the integrated taxonomy JSON to the frozen facet matcher."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .classifier import normalize
from .facet_matcher import (
    FacetMatchResult,
    FacetOccurrence,
    KiwiFacetMatcher,
    MatchedFacet,
)

ROOT_CATEGORY_ID = "__root__"


class TaxonomyFacetMatcher(KiwiFacetMatcher):
    """Build the parser matcher directly from the integrated taxonomy shape."""

    def __init__(
        self,
        taxonomy: Mapping[str, Any],
        alias_path: str | Path | None = None,
    ) -> None:
        from kiwipiepy import Kiwi

        self.kiwi = Kiwi()
        self.values = defaultdict(lambda: defaultdict(list))
        self.aliases = defaultdict(list)
        self.deprecated_value_groups: list[dict[str, Any]] = []

        root_facets = taxonomy.get("facets")
        if isinstance(root_facets, list):
            self._add_category(ROOT_CATEGORY_ID, root_facets)

        categories = taxonomy.get("categories", [])
        if isinstance(categories, list):
            for category in categories:
                if not isinstance(category, Mapping):
                    continue
                category_id = str(category.get("category_id", "")).strip()
                facets = category.get("facets")
                if category_id and isinstance(facets, list):
                    self._add_category(category_id, facets)

        if alias_path is not None:
            payload = json.loads(Path(alias_path).read_text(encoding="utf-8"))
            for rule in payload.get("aliases", []):
                local_values = rule.get("category_local_values", {})
                for category_id, facets in self.values.items():
                    local_target = local_values.get(category_id, {})
                    target_code = local_target.get("code")
                    target_value = local_target.get(
                        "value", rule.get("canonical_value", "")
                    )
                    for candidate in facets.get(rule["facet_name"], []):
                        # Reviewed aliases may use a language-neutral target
                        # (for example powder) while V2.2 stores the
                        # category-local value as 분말. Prefer the reviewed
                        # local code, then its local value, then the legacy
                        # canonical value for older alias rows.
                        matches_local_code = (
                            target_code is not None
                            and candidate.value_code == int(target_code)
                        )
                        matches_local_value = normalize(candidate.value) == normalize(
                            str(target_value)
                        )
                        if matches_local_code or matches_local_value:
                            self.aliases[
                                (
                                    category_id,
                                    candidate.facet_name,
                                    candidate.value_code,
                                )
                            ].extend(rule["surfaces"])

        self.normalized_duplicate_groups = []
        for category_id, facets in self.values.items():
            for facet_name, candidates in facets.items():
                grouped = defaultdict(list)
                for candidate in candidates:
                    grouped[normalize(candidate.value)].append(candidate)
                for normalized_value, duplicates in grouped.items():
                    if len(duplicates) > 1:
                        self.normalized_duplicate_groups.append(
                            {
                                "category_id": category_id,
                                "facet_name": facet_name,
                                "normalized_value": normalized_value,
                                "codes_and_values": [
                                    {"value_code": item.value_code, "value": item.value}
                                    for item in duplicates
                                ],
                            }
                        )

    def _add_category(self, category_id: str, facets: list[Any]) -> None:
        for facet in facets:
            if not isinstance(facet, Mapping):
                continue
            facet_name = str(facet.get("name", "")).strip()
            if not facet_name:
                continue
            values = facet.get("values", [])
            if not isinstance(values, list):
                continue
            values_by_code: dict[int, Mapping[str, Any]] = {}
            for value in values:
                if not isinstance(value, Mapping):
                    continue
                try:
                    value_code = int(value["code"])
                except (KeyError, TypeError, ValueError):
                    continue
                canonical_value = str(value.get("value", "")).strip()
                if value_code == 0 or not canonical_value:
                    continue
                values_by_code[value_code] = value

            candidates_by_code: dict[int, MatchedFacet] = {}
            for value_code, value in values_by_code.items():
                if str(value.get("status", "")).upper() == "DEPRECATED":
                    continue
                canonical_value = str(value.get("value", "")).strip()
                candidate = MatchedFacet(facet_name, value_code, canonical_value)
                self.values[category_id][facet_name].append(candidate)
                candidates_by_code[value_code] = candidate
                raw_aliases = value.get("aliases", [])
                if isinstance(raw_aliases, str):
                    raw_aliases = [item.strip() for item in raw_aliases.split("|")]
                if isinstance(raw_aliases, list):
                    self.aliases[(category_id, facet_name, value_code)].extend(
                        str(item).strip() for item in raw_aliases if str(item).strip()
                    )

            deprecated_by_canonical: dict[int, list[tuple[int, str]]] = defaultdict(
                list
            )
            for deprecated_code, value in values_by_code.items():
                if str(value.get("status", "")).upper() != "DEPRECATED":
                    continue
                target_code = deprecated_code
                visited = {deprecated_code}
                while True:
                    target = values_by_code.get(target_code)
                    if target is None:
                        raise ValueError(
                            "deprecated taxonomy value references a missing "
                            f"canonical code: {category_id}/{facet_name}/{target_code}"
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

                canonical = candidates_by_code.get(target_code)
                if canonical is None:
                    raise ValueError(
                        "deprecated taxonomy value must resolve to an active value: "
                        f"{category_id}/{facet_name}/{deprecated_code}"
                    )
                deprecated_value = str(value.get("value", "")).strip()
                deprecated_by_canonical[target_code].append(
                    (deprecated_code, deprecated_value)
                )
                raw_aliases = value.get("aliases", [])
                if isinstance(raw_aliases, str):
                    raw_aliases = [item.strip() for item in raw_aliases.split("|")]
                surfaces = [deprecated_value]
                if isinstance(raw_aliases, list):
                    surfaces.extend(
                        str(item).strip() for item in raw_aliases if str(item).strip()
                    )
                alias_key = (category_id, facet_name, canonical.value_code)
                existing = {normalize(item) for item in self.aliases[alias_key]}
                for surface in surfaces:
                    if surface and normalize(surface) not in existing:
                        self.aliases[alias_key].append(surface)
                        existing.add(normalize(surface))

            for canonical_code, deprecated in deprecated_by_canonical.items():
                canonical = candidates_by_code[canonical_code]
                self.deprecated_value_groups.append(
                    {
                        "category_id": category_id,
                        "facet_name": facet_name,
                        "canonical_value_code": canonical.value_code,
                        "canonical_value": canonical.value,
                        "deprecated_codes_and_values": [
                            {"value_code": code, "value": value}
                            for code, value in sorted(deprecated)
                        ],
                    }
                )

    def _category_key(self, category_id: str) -> str:
        key = str(category_id or "").strip()
        if key in self.values:
            return key
        if ROOT_CATEGORY_ID in self.values:
            return ROOT_CATEGORY_ID
        return key

    def protected_spans(
        self, category_id: str, text: str
    ) -> tuple[tuple[int, int], ...]:
        return super().protected_spans(self._category_key(category_id), text)

    def occurrences(self, category_id: str, text: str) -> tuple[FacetOccurrence, ...]:
        return super().occurrences(self._category_key(category_id), text)

    def match(self, category_id: str, text: str) -> FacetMatchResult:
        return super().match(self._category_key(category_id), text)

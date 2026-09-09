"""Adapter from the integrated taxonomy JSON to the frozen facet matcher."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from .classifier import normalize
from .facet_matcher import FacetMatchResult, FacetOccurrence, KiwiFacetMatcher, MatchedFacet


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
                for category_id, facets in self.values.items():
                    for candidate in facets.get(rule["facet_name"], []):
                        if normalize(candidate.value) == normalize(rule["canonical_value"]):
                            self.aliases[
                                (category_id, candidate.facet_name, candidate.value_code)
                            ].extend(rule["surfaces"])

        self.normalized_duplicate_groups = []
        for category_id, facets in self.values.items():
            for facet_name, candidates in facets.items():
                grouped = defaultdict(list)
                for candidate in candidates:
                    grouped[normalize(candidate.value)].append(candidate)
                for normalized_value, duplicates in grouped.items():
                    if len(duplicates) > 1:
                        self.normalized_duplicate_groups.append({
                            "category_id": category_id,
                            "facet_name": facet_name,
                            "normalized_value": normalized_value,
                            "codes_and_values": [
                                {"value_code": item.value_code, "value": item.value}
                                for item in duplicates
                            ],
                        })

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
                candidate = MatchedFacet(facet_name, value_code, canonical_value)
                self.values[category_id][facet_name].append(candidate)
                raw_aliases = value.get("aliases", [])
                if isinstance(raw_aliases, str):
                    raw_aliases = [item.strip() for item in raw_aliases.split("|")]
                if isinstance(raw_aliases, list):
                    self.aliases[(category_id, facet_name, value_code)].extend(
                        str(item).strip() for item in raw_aliases if str(item).strip()
                    )

    def _category_key(self, category_id: str) -> str:
        key = str(category_id or "").strip()
        if key in self.values:
            return key
        if ROOT_CATEGORY_ID in self.values:
            return ROOT_CATEGORY_ID
        return key

    def protected_spans(self, category_id: str, text: str) -> tuple[tuple[int, int], ...]:
        return super().protected_spans(self._category_key(category_id), text)

    def occurrences(self, category_id: str, text: str) -> tuple[FacetOccurrence, ...]:
        return super().occurrences(self._category_key(category_id), text)

    def match(self, category_id: str, text: str) -> FacetMatchResult:
        return super().match(self._category_key(category_id), text)

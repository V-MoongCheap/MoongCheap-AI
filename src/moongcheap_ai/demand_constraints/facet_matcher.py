from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .classifier import normalize


@dataclass(frozen=True)
class MatchedFacet:
    facet_name: str
    value_code: int
    value: str


@dataclass(frozen=True)
class FacetMatchResult:
    facets: tuple[MatchedFacet, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class FacetOccurrence:
    facet: MatchedFacet
    start: int
    end: int


class KiwiFacetMatcher:
    """A narrow probe: retain Part A's literal matching but protect one-character values."""

    def __init__(self, codebook_path: str | Path, alias_path: str | Path | None = None) -> None:
        from kiwipiepy import Kiwi

        self.kiwi = Kiwi()
        self.values = defaultdict(lambda: defaultdict(list))
        self.aliases = defaultdict(list)
        with Path(codebook_path).open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                if row["value_code"] == "0":
                    continue
                candidate = MatchedFacet(row["facet_name"], int(row["value_code"]), row["value"])
                self.values[row["category_id"]][row["facet_name"]].append(candidate)
                raw_aliases = str(row.get("aliases", "") or "").strip()
                if raw_aliases:
                    try:
                        parsed_aliases = json.loads(raw_aliases)
                    except json.JSONDecodeError:
                        parsed_aliases = [item.strip() for item in raw_aliases.split("|")]
                    if isinstance(parsed_aliases, list):
                        self.aliases[(row["category_id"], row["facet_name"], candidate.value_code)].extend(
                            str(item).strip() for item in parsed_aliases if str(item).strip()
                        )
        if alias_path is not None:
            payload = json.loads(Path(alias_path).read_text(encoding="utf-8"))
            for rule in payload.get("aliases", []):
                for category_id, facets in self.values.items():
                    for candidate in facets.get(rule["facet_name"], []):
                        if normalize(candidate.value) == normalize(rule["canonical_value"]):
                            self.aliases[(category_id, candidate.facet_name, candidate.value_code)].extend(rule["surfaces"])
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

    @staticmethod
    def _surface(text: str) -> str:
        """Normalize characters without collapsing spaces so match offsets stay usable."""
        return unicodedata.normalize("NFKC", text).casefold()

    def _candidate_spans(
        self,
        category_id: str,
        candidate: MatchedFacet,
        text: str,
    ) -> tuple[tuple[int, int], ...]:
        surface = self._surface(text)
        candidates = [candidate.value, *self.aliases[(category_id, candidate.facet_name, candidate.value_code)]]
        spans = []
        for candidate_surface in candidates:
            value = self._surface(candidate_surface)
            if len(value) == 1:
                # Character lookaheads cannot distinguish the product form `바+로`
                # from the adverb `바로`. Require Kiwi to expose the one-syllable
                # value as its own token instead.
                spans.extend(
                    (token.start, token.start + token.len)
                    for token in self.kiwi.tokenize(text)
                    if self._surface(token.form) == value and token.len == 1
                    and (
                        token.start == 0
                        or not re.match(r"[가-힣A-Za-z0-9]", text[token.start - 1])
                    )
                )
                continue
            else:
                pattern = re.compile(re.escape(value))
            spans.extend(match.span() for match in pattern.finditer(surface))
        return tuple(sorted(set(spans)))

    def protected_spans(self, category_id: str, text: str) -> tuple[tuple[int, int], ...]:
        """Return taxonomy literal spans whose internal punctuation is not a clause break."""
        spans = []
        for candidates in self.values.get(category_id, {}).values():
            for candidate in candidates:
                if len(self._surface(candidate.value)) > 1:
                    spans.extend(self._candidate_spans(category_id, candidate, text))
        return tuple(spans)

    def occurrences(self, category_id: str, text: str) -> tuple[FacetOccurrence, ...]:
        """Return concrete value occurrences, retaining competing values for safe clause splitting."""
        raw = []
        for candidates in self.values.get(category_id, {}).values():
            for candidate in candidates:
                raw.extend(
                    FacetOccurrence(candidate, start, end)
                    for start, end in self._candidate_spans(category_id, candidate, text)
                )

        # Prefer a longer taxonomy literal when a shorter form is embedded in it.
        kept = []
        for occurrence in raw:
            embedded = any(
                other.facet != occurrence.facet
                and other.start <= occurrence.start
                and occurrence.end <= other.end
                and (other.end - other.start) > (occurrence.end - occurrence.start)
                for other in raw
            )
            if not embedded:
                kept.append(occurrence)
        return tuple(sorted(set(kept), key=lambda item: (item.start, -(item.end - item.start))))

    def match(self, category_id: str, text: str) -> FacetMatchResult:
        results_with_spans = []
        warnings = []
        for facet_name, candidates in self.values.get(category_id, {}).items():
            matches = []
            for candidate in candidates:
                spans = self._candidate_spans(category_id, candidate, text)
                if spans:
                    matches.append((candidate, spans))
            if not matches:
                continue
            longest = max(len(normalize(candidate.value)) for candidate, _ in matches)
            best = [item for item in matches if len(normalize(item[0].value)) == longest]
            if len(best) > 1:
                warnings.append(f"ambiguous values for facet: {facet_name}")
                continue
            results_with_spans.append(best[0])

        # A long taxonomy literal wins over a shorter value embedded at the same location,
        # even when the two belong to different facets (미숙여주주정추출분말 vs 분말).
        results = []
        for candidate, spans in results_with_spans:
            embedded = any(
                other != candidate
                and len(normalize(other.value)) > len(normalize(candidate.value))
                and any(
                    other_start <= start and end <= other_end
                    for start, end in spans
                    for other_start, other_end in other_spans
                )
                for other, other_spans in results_with_spans
            )
            if not embedded:
                results.append(candidate)
        return FacetMatchResult(tuple(results), tuple(warnings))

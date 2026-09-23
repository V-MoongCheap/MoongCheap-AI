"""Shared interpretation of canonical and deprecated taxonomy values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CanonicalTaxonomyValue:
    """One active value with every surface redirected to its canonical code."""

    code: int
    value: str
    aliases: tuple[str, ...]


def _value_code(value: Mapping[str, Any], field: str = "code") -> int | None:
    raw = value.get(field)
    if isinstance(raw, bool):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _aliases(value: Mapping[str, Any]) -> tuple[str, ...]:
    raw = value.get("aliases", ())
    if isinstance(raw, str):
        raw = raw.split("|")
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(surface for item in raw if (surface := str(item).strip()))


def canonical_taxonomy_values(values: Any) -> tuple[CanonicalTaxonomyValue, ...]:
    """Return active values and redirect deprecated surfaces to canonical codes.

    ``canonical_code`` is resolved within the same Facet. Invalid targets and
    cycles fail closed so a malformed approved taxonomy cannot silently create
    a different parser and product-profile contract.
    """

    if not isinstance(values, list):
        return ()

    by_code: dict[int, Mapping[str, Any]] = {}
    ordered_codes: list[int] = []
    for raw in values:
        if not isinstance(raw, Mapping):
            continue
        code = _value_code(raw)
        value = str(raw.get("value", "")).strip()
        if code is None or code == 0 or not value:
            continue
        if code in by_code:
            raise ValueError(f"duplicate taxonomy value code: {code}")
        by_code[code] = raw
        ordered_codes.append(code)

    def canonical_code(source_code: int) -> int:
        seen: set[int] = set()
        current_code = source_code
        while True:
            if current_code in seen:
                raise ValueError(
                    f"cyclic deprecated taxonomy canonical_code: {source_code}"
                )
            seen.add(current_code)
            current = by_code.get(current_code)
            if current is None:
                raise ValueError(
                    "deprecated taxonomy canonical_code is not in the same facet: "
                    f"{current_code}"
                )
            if str(current.get("status", "")).strip().upper() != "DEPRECATED":
                return current_code
            target_code = _value_code(current, "canonical_code")
            if target_code is None or target_code <= 0:
                raise ValueError(
                    "deprecated taxonomy value must declare a positive canonical_code: "
                    f"{current_code}"
                )
            current_code = target_code

    active_codes = [
        code
        for code in ordered_codes
        if str(by_code[code].get("status", "")).strip().upper() != "DEPRECATED"
    ]
    aliases_by_code: dict[int, list[str]] = {
        code: list(_aliases(by_code[code])) for code in active_codes
    }
    for code in ordered_codes:
        target_code = canonical_code(code)
        if target_code == code:
            continue
        source = by_code[code]
        aliases_by_code[target_code].extend(
            (
                str(source["value"]).strip(),
                *_aliases(source),
            )
        )

    result = []
    for code in active_codes:
        value = str(by_code[code]["value"]).strip()
        aliases = []
        seen = {value}
        for surface in aliases_by_code[code]:
            if surface not in seen:
                aliases.append(surface)
                seen.add(surface)
        result.append(CanonicalTaxonomyValue(code, value, tuple(aliases)))
    return tuple(result)

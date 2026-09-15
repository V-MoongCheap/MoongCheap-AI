"""Part A artifact checks and B's explicit legacy-expression compatibility."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from ..demand_constraints import DemandConstraintParser
from ..demand_constraints.classifier import normalize


def taxonomy_version(taxonomy: Mapping[str, Any]) -> str:
    versions = {
        str(taxonomy[key]).strip()
        for key in ("version", "taxonomy_version")
        if taxonomy.get(key)
    }
    if len(versions) != 1 or not next(iter(versions), ""):
        raise ValueError("taxonomy must declare one unambiguous version")
    return versions.pop()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_profile_versions(
    profiles: pd.DataFrame, taxonomy: Mapping[str, Any],
) -> str:
    expected = taxonomy_version(taxonomy)
    if "taxonomy_version" not in profiles:
        raise ValueError("profiles missing taxonomy_version")
    if profiles.empty:
        raise ValueError("profiles must not be empty")
    actual = set(profiles["taxonomy_version"].fillna("").astype(str).str.strip())
    if actual - {expected}:
        raise ValueError(
            f"profile taxonomy versions {sorted(actual)} do not match {expected}; "
            "rebuild profiles with the supplied taxonomy before starting the batch"
        )
    return expected


def _alias_registry(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("aliases"), list):
        raise ValueError("alias registry must contain an aliases array")
    if any(not isinstance(row, dict) for row in payload["aliases"]):
        raise ValueError("alias registry rows must be objects")
    return payload, hashlib.sha256(raw).hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"alias {field} must be a nonempty string")
    return value.strip()


def _surfaces(rule: Mapping[str, Any]) -> list[str]:
    surfaces = rule.get("surfaces")
    if not isinstance(surfaces, list) or not surfaces:
        raise ValueError("alias surfaces must be a nonempty array")
    return [_text(surface, "surface") for surface in surfaces]


def _approved_bindings(primary, taxonomy):
    """Resolve only explicit category-local targets; never guess from canonical_value."""
    if primary.get("taxonomy_version") != taxonomy_version(taxonomy):
        raise ValueError("primary alias taxonomy version does not match taxonomy")
    _text(primary.get("version"), "version")
    categories = {c["category_id"]: c for c in taxonomy["categories"]}
    bindings = {}
    for rule in primary["aliases"]:
        # The current APPLIED-only A export omits row status. Explicitly
        # rejected/deferred rows or a full review registry are not that export.
        if rule.get("review_status", rule.get("status", "APPLIED")) != "APPLIED":
            raise ValueError("primary aliases must be an APPLIED-only export")
        facet_name = _text(rule.get("facet_name"), "facet_name")
        surfaces = _surfaces(rule)
        local_values = rule.get("category_local_values")
        if not isinstance(local_values, dict) or not local_values:
            raise ValueError("primary aliases require category_local_values")
        for category_id, target in local_values.items():
            if category_id not in categories:
                raise ValueError(f"primary alias category not in taxonomy: {category_id}")
            facets = {f["name"]: f for f in categories[category_id]["facets"]}
            if facet_name not in facets:
                raise ValueError(f"primary alias facet not in category: {category_id}/{facet_name}")
            if not isinstance(target, dict):
                raise ValueError("primary alias target must be an object")
            code = target.get("code")
            if type(code) is not int or code <= 0:
                raise ValueError("primary alias code must be a positive integer")
            candidates = [v for v in facets[facet_name]["values"] if int(v["code"]) == code]
            if len(candidates) != 1:
                raise ValueError(f"primary alias code not in facet: {category_id}/{facet_name}/{code}")
            value = _text(target.get("value"), "target value")
            if normalize(value) != normalize(candidates[0]["value"]):
                raise ValueError(f"primary alias code/value mismatch: {category_id}/{facet_name}/{code}")
            for surface in surfaces:
                key = (category_id, normalize(surface))
                binding = (facet_name, code, candidates[0]["value"], surface)
                if key in bindings and bindings[key][:2] != binding[:2]:
                    raise ValueError(f"conflicting primary alias targets: {category_id}/{surface}")
                # A literal taxonomy value remains matchable even if all its
                # aliases are removed. Reject redirects that would be ambiguous.
                if any(
                    normalize(v["value"]) == key[1]
                    and (f["name"], int(v["code"])) != binding[:2]
                    for f in facets.values() for v in f["values"] if int(v["code"]) != 0
                ):
                    raise ValueError(f"primary alias conflicts with taxonomy literal: {category_id}/{surface}")
                bindings[key] = binding
    return bindings


def build_part_b_parser(
    taxonomy: Mapping[str, Any],
    *,
    rules_path: Path,
    aliases_path: Path | None = None,
    compatibility_aliases_path: Path | None = None,
) -> tuple[DemandConstraintParser, dict[str, Any]]:
    """Use B expressions continuously, preferring valid A targets where available.

    Runtime requires the B registry. A-only is allowed here for evaluation.
    An unconfigured A registry falls back; a configured missing, unreadable, or
    invalid registry fails. Removing an A binding intentionally leaves the B
    binding available.
    """
    version = taxonomy_version(taxonomy)
    primary = None
    primary_hash = None
    primary_status = "NOT_CONFIGURED"
    if aliases_path is not None:
        primary, primary_hash = _alias_registry(aliases_path)
        primary_status = "LOADED"
    bindings = _approved_bindings(primary, taxonomy) if primary is not None else {}
    compatibility = None
    compatibility_hash = None
    if compatibility_aliases_path is not None:
        compatibility, compatibility_hash = _alias_registry(compatibility_aliases_path)
        for rule in compatibility["aliases"]:
            _text(rule.get("facet_name"), "facet_name")
            _text(rule.get("canonical_value"), "canonical_value")
            _surfaces(rule)
    if primary is None and compatibility is None:
        raise ValueError("at least the B alias registry must be available")
    summary: dict[str, Any] = {
        "taxonomyVersion": version,
        "aliasPolicy": "B_BASE_WITH_A_PRIORITY",
        "aliasMode": "A_AND_B" if primary is not None and compatibility is not None else (
            "A_ONLY_EVALUATION" if primary is not None else "B_ONLY"
        ),
        "primaryAliasLoadStatus": primary_status,
        "primaryAliasVersion": primary.get("version") if primary is not None else None,
        "primaryAliasSha256": primary_hash,
        "primaryBindingCount": len(bindings),
        "compatibilityAliasVersion": compatibility.get("version", "") if compatibility is not None else None,
        "compatibilityAliasStatus": compatibility.get("status", "UNREVIEWED") if compatibility is not None else None,
        "compatibilityAliasSha256": compatibility_hash,
        "compatibilitySurfaceCount": 0,
        "compatibilityOverlapWithA": 0,
    }
    enriched = deepcopy(taxonomy)
    for category in enriched.get("categories", []):
        category_id = category["category_id"]
        for facet in category["facets"]:
            for value in facet["values"]:
                key = (facet["name"], int(value["code"]))
                existing = value.get("aliases", [])
                if isinstance(existing, str):
                    existing = existing.split("|")
                # Remove competing taxonomy aliases too, so A's priority is
                # independent of whether B aliases came from a file or taxonomy.
                aliases = [surface for surface in existing if (
                    (binding := bindings.get((category_id, normalize(surface)))) is None
                    or binding[:2] == key
                )]
                seen = {normalize(surface) for surface in aliases}
                for rule in compatibility["aliases"] if compatibility is not None else ():
                    if key[1] == 0 or rule["facet_name"] != facet["name"] or (
                        normalize(rule["canonical_value"]) != normalize(value["value"])
                    ) or rule.get("review_status", rule.get("status")) in {"DEFERRED", "REJECTED"}:
                        continue
                    for surface in rule["surfaces"]:
                        normalized = normalize(surface)
                        if (category_id, normalized) in bindings:
                            summary["compatibilityOverlapWithA"] += 1
                        elif normalized not in seen:
                            aliases.append(surface)
                            seen.add(normalized)
                            summary["compatibilitySurfaceCount"] += 1
                for (bound_category, normalized), binding in bindings.items():
                    if bound_category == category_id and binding[:2] == key and normalized not in seen:
                        aliases.append(binding[3])
                        seen.add(normalized)
                value["aliases"] = aliases
    # All A bindings were validated and applied to their exact category/code.
    # B never invokes the shared matcher's permissive code-or-value fallback.
    return DemandConstraintParser.from_taxonomy(enriched, rules_path=rules_path), summary

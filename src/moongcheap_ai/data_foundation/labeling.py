"""Rule/Alias based Demand Labeling V0."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd


class TaxonomyValidationError(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TaxonomyValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _text(value: Any) -> str:
    """Convert scalar input safely, including pandas missing scalars."""
    if value is None:
        return ""
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, bool) and missing:
        return ""
    return str(value)


def _normalise(value: Any) -> str:
    return re.sub(
        r"\s+", " ", unicodedata.normalize("NFKC", _text(value)).casefold()
    ).strip()


def _ordered_facets(facets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return facets in their validated explicit order, preserving defaults."""
    return [
        facet
        for _, facet in sorted(
            enumerate(facets, start=1),
            key=lambda item: int(item[1].get("order", item[0])),
        )
    ]


NO_REQUIREMENT_PHRASES = {
    "조건 없음",
    "조건없음",
    "상관 없음",
    "상관없음",
    "아무 조건 없음",
    "무관",
}


class TaxonomyLoader:
    def __init__(self, taxonomy: dict[str, Any]) -> None:
        if not isinstance(taxonomy, dict):
            raise TaxonomyValidationError("taxonomy root must be an object")
        self.taxonomy = taxonomy
        self.categories: dict[str, dict[str, Any]] = {}
        self.root_category: dict[str, Any] | None = None
        if taxonomy.get("facets"):
            root_facets = taxonomy["facets"]
            self._validate_category(
                {"category_id": "__root__", "facets": root_facets}
            )
            self.root_category = {
                "category_id": "__root__",
                "facets": _ordered_facets(root_facets),
            }
        categories = taxonomy.get("categories", [])
        if not isinstance(categories, list):
            raise TaxonomyValidationError("taxonomy categories must be a list")
        for category in categories:
            if not isinstance(category, dict):
                raise TaxonomyValidationError("taxonomy category must be an object")
            category_id = str(category.get("category_id", "")).strip()
            if not category_id:
                raise TaxonomyValidationError("taxonomy category_id is required")
            if category_id in self.categories:
                raise TaxonomyValidationError(f"duplicate category_id: {category_id}")
            self._validate_category(category)
            self.categories[category_id] = {
                **category,
                "facets": _ordered_facets(category["facets"]),
            }

    @classmethod
    def from_path(cls, path: Path) -> TaxonomyLoader:
        try:
            payload = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=_unique_json_object,
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise TaxonomyValidationError(f"invalid taxonomy JSON: {path}") from exc
        if not isinstance(payload, dict):
            raise TaxonomyValidationError("taxonomy root must be an object")
        return cls(payload)

    def _validate_category(self, category: dict[str, Any]) -> None:
        seen_facets: set[str] = set()
        seen_orders: set[int] = set()
        facets = category.get("facets")
        if not isinstance(facets, list):
            raise TaxonomyValidationError("category facets must be a list")
        for index, facet in enumerate(facets, 1):
            if not isinstance(facet, dict):
                raise TaxonomyValidationError("taxonomy facet must be an object")
            name = str(facet.get("name", "")).strip()
            if not name or name in seen_facets:
                raise TaxonomyValidationError(f"invalid or duplicate facet: {name}")
            seen_facets.add(name)
            try:
                raw_order = facet.get("order", index)
                if isinstance(raw_order, bool) or not isinstance(raw_order, (int, str)):
                    raise TypeError
                order_text = str(raw_order).strip()
                if not order_text.isdigit():
                    raise ValueError
                order = int(order_text)
            except (KeyError, TypeError, ValueError) as exc:
                raise TaxonomyValidationError(f"invalid facet order: {name}") from exc
            if order in seen_orders:
                raise TaxonomyValidationError(f"duplicate facet order: {order}")
            seen_orders.add(order)
            codes: set[int] = set()
            has_all = False
            values = facet.get("values")
            if not isinstance(values, list) or not values:
                raise TaxonomyValidationError(f"facet has no values: {name}")
            for value in values:
                if not isinstance(value, dict):
                    raise TaxonomyValidationError(
                        f"taxonomy value must be an object: {name}"
                    )
                try:
                    raw_code = value["code"]
                    if isinstance(raw_code, bool) or not isinstance(
                        raw_code, (int, str)
                    ):
                        raise TypeError
                    code_text = str(raw_code).strip()
                    if not re.fullmatch(r"-?\d+", code_text):
                        raise ValueError
                    code = int(code_text)
                except (KeyError, TypeError, ValueError) as exc:
                    raise TaxonomyValidationError(
                        f"invalid value code in facet: {name}"
                    ) from exc
                if code < 0:
                    raise TaxonomyValidationError(
                        f"value code must be non-negative in facet: {name}"
                    )
                if code in codes:
                    raise TaxonomyValidationError(
                        f"duplicate value code {code} in facet: {name}"
                    )
                codes.add(code)
                value_name = str(value.get("value", "")).strip()
                if code == 0 and value_name and value_name != "ALL":
                    raise TaxonomyValidationError(
                        f"code 0 must be ALL in facet: {name}"
                    )
                if code != 0 and value_name == "ALL":
                    raise TaxonomyValidationError(
                        f"ALL must use code 0 in facet: {name}"
                    )
                if code != 0 and not value_name:
                    raise TaxonomyValidationError(
                        f"taxonomy value name is required for nonzero code in facet: {name}"
                    )
                aliases = value.get("aliases", [])
                if not isinstance(aliases, list) or any(
                    not isinstance(alias, str) for alias in aliases
                ):
                    raise TaxonomyValidationError(
                        f"taxonomy aliases must be a list of strings in facet: {name}"
                    )
                has_all = has_all or code == 0
            if not has_all:
                raise TaxonomyValidationError(f"facet has no ALL(code=0): {name}")
        if seen_orders and seen_orders != set(range(1, len(seen_orders) + 1)):
            raise TaxonomyValidationError("facet orders must be contiguous from 1")

    def category(self, category_id: Any) -> dict[str, Any] | None:
        return self.categories.get(_text(category_id).strip()) or self.root_category

    def resolve(
        self, category_id: Any, extra_requirement: Any
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        category = self.category(category_id)
        if category is None:
            return {}, [f"taxonomy category not found: {category_id}"]
        text = _normalise(extra_requirement)
        result: dict[str, dict[str, Any]] = {}
        warnings: list[str] = []
        facets = sorted(
            category.get("facets", []),
            key=lambda item: (int(item.get("order", 0)), str(item.get("name", ""))),
        )
        for facet in facets:
            candidates: list[tuple[int, int, dict[str, Any], str]] = []
            for value in facet.get("values", []):
                code = int(value["code"])
                if code == 0 or str(value.get("status", "")).upper() == "DEPRECATED":
                    continue
                aliases = [value.get("value", ""), *(value.get("aliases") or [])]
                for alias in aliases:
                    alias_text = _normalise(alias)
                    if alias_text and alias_text in text:
                        candidates.append((len(alias_text), code, value, alias_text))
            if candidates:
                candidates.sort(key=lambda item: (-item[0], item[1]))
                best = candidates[0]
                if (
                    len(
                        {
                            candidate[1]
                            for candidate in candidates
                            if candidate[0] == best[0]
                        }
                    )
                    > 1
                ):
                    warnings.append(
                        f"ambiguous requirement for facet: {facet.get('name')}"
                    )
                result[str(facet["name"])] = {
                    "code": best[1],
                    "value": best[2].get("value", ""),
                    "matched_alias": best[3],
                }
            else:
                all_value = next(
                    value
                    for value in facet.get("values", [])
                    if int(value["code"]) == 0
                )
                result[str(facet["name"])] = {
                    "code": 0,
                    "value": all_value.get("value", "ALL"),
                    "matched_alias": None,
                }
        if (
            text
            and text not in NO_REQUIREMENT_PHRASES
            and result
            and all(item["code"] == 0 for item in result.values())
        ):
            warnings.append("requirement did not match any taxonomy value")
        return result, warnings

    def encode(self, facet_values: dict[str, dict[str, Any]]) -> str:
        return "-".join(str(item["code"]) for item in facet_values.values())

    def product_defaults(
        self, category_id: Any, rows: list[dict[str, Any]]
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        """Convert mapped product facet evidence into taxonomy defaults."""
        category = self.categories.get(_text(category_id).strip())
        if category is None:
            return {}, [f"taxonomy category not found: {category_id}"]
        defaults: dict[str, dict[str, Any]] = {}
        warnings: list[str] = []
        facets = {str(facet.get("name")): facet for facet in category.get("facets", [])}
        mapped_values: dict[str, dict[int, dict[str, Any]]] = {}
        counts: dict[str, int] = {}
        for row in rows:
            facet_name = str(row.get("facet_name", "")).strip()
            raw_value = str(row.get("value", "")).strip()
            row_category_id = str(row.get("category_id", "")).strip()
            counts[facet_name] = counts.get(facet_name, 0) + 1
            if row_category_id != str(category_id).strip():
                warnings.append(
                    f"product facet category mismatch: {row_category_id} != {category_id}"
                )
                continue
            facet = facets.get(facet_name)
            if facet is None:
                warnings.append(f"product facet not found in taxonomy: {facet_name}")
                continue
            status = str(row.get("mapping_status", "")).strip().upper()
            if status != "MAPPED":
                warnings.append(
                    f"product facet is not known: {facet_name} ({status or 'NO_STATUS'})"
                )
                continue
            if not raw_value:
                warnings.append(f"mapped product facet has no value: {facet_name}")
                continue
            all_matches = []
            for value in facet.get("values", []):
                aliases = [value.get("value", ""), *(value.get("aliases") or [])]
                if any(_normalise(alias) == _normalise(raw_value) for alias in aliases):
                    all_matches.append(value)
            value_matches = list(all_matches)
            declared_code = str(row.get("value_code", "")).strip()
            if declared_code:
                try:
                    expected_code = int(declared_code)
                except ValueError:
                    warnings.append(
                        f"invalid product facet code: {facet_name}={declared_code}"
                    )
                    continue
                all_matches = [
                    value
                    for value in all_matches
                    if int(value["code"]) == expected_code
                ]
            matches = [
                value
                for value in all_matches
                if str(value.get("status", "")).upper() != "DEPRECATED"
            ]
            if len(matches) == 1 and int(matches[0]["code"]) > 0:
                value = matches[0]
                code = int(value["code"])
                mapped_values.setdefault(facet_name, {})[code] = {
                    "code": code,
                    "value": value.get("value", ""),
                    "matched_alias": raw_value,
                }
            elif len(matches) == 1:
                warnings.append(
                    f"ALL is not a product Facet value: {facet_name}={raw_value}"
                )
            elif not matches and all_matches:
                warnings.append(
                    f"deprecated product Facet value is not valid: {facet_name}={raw_value}"
                )
            elif not matches:
                if declared_code and value_matches:
                    warnings.append(
                        f"product facet code does not match taxonomy: {facet_name}={raw_value}"
                    )
                else:
                    warnings.append(
                        f"product facet value not found in taxonomy: {facet_name}={raw_value}"
                    )
            else:
                warnings.append(
                    f"product facet value is ambiguous in taxonomy: {facet_name}={raw_value}"
                )
        for facet_name in facets:
            if counts.get(facet_name, 0) == 0:
                warnings.append(f"product Facet profile is missing facet: {facet_name}")
            elif counts[facet_name] > 1:
                warnings.append(f"product Facet profile duplicates facet: {facet_name}")
        # The compact Backend label is a positional vector. Always serialize
        # in taxonomy facet order, never in the incidental CSV row order.
        for facet_name in facets:
            values = mapped_values.get(facet_name, {})
            if not values:
                continue
            if len(values) == 1:
                defaults[facet_name] = next(iter(values.values()))
            else:
                warnings.append(
                    f"conflicting product facet values for facet: {facet_name}"
                )
        return defaults, warnings


def load_taxonomy(path: Path) -> TaxonomyLoader:
    return TaxonomyLoader.from_path(path)


def taxonomy_from_category_facet_rows(frame: pd.DataFrame) -> dict[str, Any]:
    """Build a taxonomy payload from Backend ``category.facet`` text rows."""
    categories: dict[str, dict[str, Any]] = {}
    if "category_facet" not in frame.columns:
        raise TaxonomyValidationError("database rows do not contain category_facet")
    for _, row in frame.iterrows():
        raw = _text(row.get("category_facet", "")).strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw, object_pairs_hook=_unique_json_object)
        except json.JSONDecodeError as exc:
            raise TaxonomyValidationError(
                "category.facet contains invalid JSON"
            ) from exc
        category_id = _text(row.get("category_id", "")).strip()
        if isinstance(parsed, dict):
            category_id = _text(parsed.get("category_id", "")).strip() or category_id
            facets = parsed.get("facets", [])
        elif isinstance(parsed, list):
            facets = parsed
        else:
            raise TaxonomyValidationError("category.facet must be an object or list")
        if not category_id:
            raise TaxonomyValidationError("category.facet row has no category key")
        candidate = {"category_id": category_id, "facets": facets}
        previous = categories.get(category_id)
        if previous is not None and previous != candidate:
            raise TaxonomyValidationError(
                f"conflicting category.facet rows: {category_id}"
            )
        categories[category_id] = candidate
    if not categories:
        raise TaxonomyValidationError("no usable category.facet rows")
    return {
        "version": "backend-category-facet",
        "categories": list(categories.values()),
    }


def build_product_facet_map(frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    """Index mapped product facets by every available catalog identifier."""
    result: dict[str, list[dict[str, Any]]] = {}
    normalized = frame.fillna("")
    if "mapping_status" in normalized:
        normalized = normalized[
            normalized["mapping_status"].astype(str).str.upper().isin({"MAPPED"})
        ]
    for payload in normalized.to_dict(orient="records"):
        source_id = _text(payload.get("source_product_id"))
        keys = {
            _text(payload.get(column))
            for column in ("catalog_id", "product_catalog_id", "id", "catalog_seed_id")
            if _text(payload.get(column))
        }
        if source_id:
            keys.update({source_id, f"catalog-seed-{source_id}"})
        for key in sorted(keys):
            result.setdefault(key, []).append(payload)
    return result


def label_demand(
    demand_id: int | str,
    catalog_id: int | str,
    extra_requirement: str,
    taxonomy: dict[str, Any],
    category_id: str = "",
    product_facet_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    loader = TaxonomyLoader(taxonomy)
    labeled = label_demands(
        pd.DataFrame(
            [
                {
                    "demand_id": demand_id,
                    "catalog_id": catalog_id,
                    "category_id": category_id,
                    "extra_requirement": extra_requirement,
                }
            ]
        ),
        loader,
        product_facet_map={str(catalog_id): product_facet_rows or []},
    ).iloc[0]
    facet_values = json.loads(str(labeled["facet_values"]))
    warnings = json.loads(str(labeled["label_warnings"]))
    return {
        "demand_id": demand_id,
        "catalog_id": catalog_id,
        "category_id": category_id,
        "facet_values": facet_values,
        "label": str(labeled["label"]),
        "label_status": str(labeled["label_status"]),
        "warnings": warnings,
    }


def label_demands(
    frame: pd.DataFrame,
    loader: TaxonomyLoader,
    catalog_category_map: dict[str, Any] | None = None,
    product_facet_map: dict[str, list[dict[str, Any]]] | None = None,
    requirement_interpreter: Callable[[str, str, bool], Any] | None = None,
) -> pd.DataFrame:
    """Batch label demands through ERD's catalog_id -> category_id path."""
    rows: list[dict[str, Any]] = []
    for _, demand in frame.iterrows():
        interpretation_status = "REVIEW"
        catalog_id = _text(demand.get("catalog_id", ""))
        category_id = _text(demand.get("category_id", "")) or _text(
            demand.get("kan_code", "")
        )
        if not category_id and catalog_category_map:
            category_id = _text(catalog_category_map.get(catalog_id, ""))
        requirement = _text(demand.get("extra_requirement", ""))
        if not category_id:
            warnings = ["CATEGORY_MISSING"]
            facet_values = {}
            unresolved_items = [requirement] if requirement else []
            label_status = "REVIEW"
            label = ""
        elif category_id not in loader.categories:
            warnings = ["CATEGORY_NOT_IN_TAXONOMY"]
            facet_values = {}
            unresolved_items = [requirement] if requirement else []
            label_status = "REVIEW"
            label = ""
        else:
            profile_rows = (product_facet_map or {}).get(catalog_id, [])
            defaults, warnings = loader.product_defaults(category_id, profile_rows)
            expected_facets = {
                str(facet.get("name", ""))
                for facet in loader.categories[category_id].get("facets", [])
            }
            if not profile_rows or set(defaults) != expected_facets or warnings:
                if not profile_rows:
                    warnings = [
                        f"product Facet profile not found for catalog_id={catalog_id}"
                    ]
                facet_values = {}
                unresolved_items = [requirement] if requirement else []
                label_status = "REVIEW"
                label = ""
            else:
                facet_values = {name: dict(value) for name, value in defaults.items()}
                unresolved_items = []
                interpretation_status = "NONE" if not requirement else "UNRESOLVED"
                if requirement_interpreter is None:
                    requested, request_warnings = loader.resolve(
                        category_id, requirement
                    )
                    warnings.extend(request_warnings)
                    normalized_requirement = _normalise(requirement)
                    no_requirement = (
                        not normalized_requirement
                        or normalized_requirement in NO_REQUIREMENT_PHRASES
                    )
                    ambiguous_facets = {
                        warning.rsplit(": ", 1)[-1]
                        for warning in request_warnings
                        if warning.startswith("ambiguous requirement for facet:")
                    }
                    non_positive_markers = (
                        "아니",
                        "말고",
                        "제외",
                        "빼고",
                        "없이",
                        "않",
                        "안 ",
                        "싫",
                        "피하",
                        "알레르기",
                        "알러지",
                        "금지",
                        "without",
                        "avoid",
                        "except",
                        "exclude",
                        "allergy",
                        "not ",
                    )
                    has_non_positive = any(
                        marker in _normalise(requirement)
                        for marker in non_positive_markers
                    )
                    overrides: dict[str, dict[str, Any]] = {}
                    if no_requirement:
                        interpretation_status = "NONE"
                    elif has_non_positive:
                        warnings.append(
                            "non-positive requirement retained product Facet baseline"
                        )
                    else:
                        for facet_name, value in requested.items():
                            if (
                                facet_name not in ambiguous_facets
                                and int(value.get("code", 0)) > 0
                            ):
                                overrides[facet_name] = value
                        facet_values.update(overrides)
                    stable_override = bool(overrides)
                    if not no_requirement:
                        interpretation_status = (
                            "PARSED" if stable_override else "UNRESOLVED"
                        )
                    if requirement and not no_requirement and not stable_override:
                        unresolved_items.append(requirement)
                else:
                    consent = _text(demand.get("is_substitutable", "true")) or "true"
                    consent = consent.strip().casefold()
                    is_substitutable = consent not in {
                        "false",
                        "0",
                        "0.0",
                        "no",
                        "n",
                        "미동의",
                    }
                    interpreted = requirement_interpreter(
                        category_id,
                        requirement,
                        is_substitutable=is_substitutable,
                    )
                    status = str(interpreted.status)
                    interpretation_status = status
                    warnings.extend(str(warning) for warning in interpreted.warnings)
                    if status == "PARSED":
                        constraints_by_facet: dict[str, set[tuple[int, str]]] = {}
                        for constraint in interpreted.constraints:
                            if str(constraint.constraint_type).upper() not in {
                                "MUST",
                                "PREFER",
                            }:
                                continue
                            facet_name = str(constraint.facet_name)
                            code = int(constraint.value_code)
                            if facet_name not in expected_facets or code <= 0:
                                continue
                            constraints_by_facet.setdefault(facet_name, set()).add(
                                (code, str(constraint.value))
                            )
                        taxonomy_facets = {
                            str(facet["name"]): facet
                            for facet in loader.categories[category_id].get(
                                "facets", []
                            )
                        }
                        for facet_name, candidates in constraints_by_facet.items():
                            if len(candidates) != 1:
                                continue
                            code, _value = next(iter(candidates))
                            match = next(
                                (
                                    value
                                    for value in taxonomy_facets[facet_name].get(
                                        "values", []
                                    )
                                    if int(value.get("code", -1)) == code
                                ),
                                None,
                            )
                            if match is not None:
                                facet_values[facet_name] = {
                                    "code": code,
                                    "value": str(match.get("value", "")),
                                    "matched_alias": "DEMAND_REQUIREMENT",
                                }
                    if (
                        status not in {"PARSED", "NONE", "NOT_APPLICABLE"}
                        and requirement
                    ):
                        unresolved_items.append(requirement)
                label_status = "LABELED"
                label = loader.encode(facet_values)
        row = demand.to_dict()
        row.update(
            {
                "category_id": str(category_id or ""),
                "label": label,
                "facet_values": json.dumps(
                    facet_values, ensure_ascii=False, separators=(",", ":")
                ),
                "desired_price_min": demand.get(
                    "desired_price_min", demand.get("desired_price", "")
                ),
                "desired_price_max": demand.get("desired_price_max", ""),
                "quantity": demand.get("quantity", demand.get("desired_quantity", "")),
                "is_substitutable": demand.get("is_substitutable", True),
                "label_status": label_status,
                "interpretation_status": interpretation_status,
                "label_warnings": json.dumps(warnings, ensure_ascii=False),
                "unresolved_items": json.dumps(unresolved_items, ensure_ascii=False),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)

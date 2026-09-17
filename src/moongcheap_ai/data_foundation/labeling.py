"""Rule/Alias based Demand Labeling V0."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd


class TaxonomyValidationError(ValueError):
    pass


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
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", _text(value)).casefold()).strip()


NO_REQUIREMENT_PHRASES = {"조건 없음", "조건없음", "상관 없음", "상관없음", "아무 조건 없음", "무관"}


class TaxonomyLoader:
    def __init__(self, taxonomy: dict[str, Any]) -> None:
        if not isinstance(taxonomy, dict):
            raise TaxonomyValidationError("taxonomy root must be an object")
        self.taxonomy = taxonomy
        self.categories: dict[str, dict[str, Any]] = {}
        self.root_category: dict[str, Any] | None = None
        if taxonomy.get("facets"):
            self._validate_category({"category_id": "__root__", "facets": taxonomy["facets"]})
            self.root_category = {"category_id": "__root__", "facets": taxonomy["facets"]}
        categories = taxonomy.get("categories", [])
        if not isinstance(categories, list):
            raise TaxonomyValidationError("taxonomy categories must be a list")
        for category in categories:
            if not isinstance(category, dict):
                raise TaxonomyValidationError("taxonomy category must be an object")
            category_id = str(category.get("category_id", "")).strip()
            if not category_id:
                continue
            if category_id in self.categories:
                raise TaxonomyValidationError(f"duplicate category_id: {category_id}")
            self._validate_category(category)
            self.categories[category_id] = category

    @classmethod
    def from_path(cls, path: Path) -> TaxonomyLoader:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
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
                order = int(facet.get("order", index))
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
                    raise TaxonomyValidationError(f"taxonomy value must be an object: {name}")
                try:
                    code = int(value["code"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise TaxonomyValidationError(f"invalid value code in facet: {name}") from exc
                if code in codes:
                    raise TaxonomyValidationError(f"duplicate value code {code} in facet: {name}")
                codes.add(code)
                has_all = has_all or code == 0
            if not has_all:
                raise TaxonomyValidationError(f"facet has no ALL(code=0): {name}")
        if seen_orders and seen_orders != set(range(1, len(seen_orders) + 1)):
            raise TaxonomyValidationError("facet orders must be contiguous from 1")

    def category(self, category_id: Any) -> dict[str, Any] | None:
        return self.categories.get(_text(category_id).strip()) or self.root_category

    def resolve(self, category_id: Any, extra_requirement: Any) -> tuple[dict[str, dict[str, Any]], list[str]]:
        category = self.category(category_id)
        if category is None:
            return {}, [f"taxonomy category not found: {category_id}"]
        text = _normalise(extra_requirement)
        result: dict[str, dict[str, Any]] = {}
        warnings: list[str] = []
        facets = sorted(category.get("facets", []), key=lambda item: (int(item.get("order", 0)), str(item.get("name", ""))))
        for facet in facets:
            candidates: list[tuple[int, int, dict[str, Any], str]] = []
            for value in facet.get("values", []):
                code = int(value["code"])
                if code == 0:
                    continue
                aliases = [value.get("value", ""), *(value.get("aliases") or [])]
                for alias in aliases:
                    alias_text = _normalise(alias)
                    if alias_text and alias_text in text:
                        candidates.append((len(alias_text), code, value, alias_text))
            if candidates:
                candidates.sort(key=lambda item: (-item[0], item[1]))
                best = candidates[0]
                if len({candidate[1] for candidate in candidates if candidate[0] == best[0]}) > 1:
                    warnings.append(f"ambiguous requirement for facet: {facet.get('name')}")
                result[str(facet["name"])] = {"code": best[1], "value": best[2].get("value", ""), "matched_alias": best[3]}
            else:
                all_value = next(value for value in facet.get("values", []) if int(value["code"]) == 0)
                result[str(facet["name"])] = {"code": 0, "value": all_value.get("value", "ALL"), "matched_alias": None}
        if text and text not in NO_REQUIREMENT_PHRASES and result and all(item["code"] == 0 for item in result.values()):
            warnings.append("requirement did not match any taxonomy value")
        return result, warnings

    def encode(self, facet_values: dict[str, dict[str, Any]]) -> str:
        return "-".join(str(item["code"]) for item in facet_values.values())

    def product_defaults(self, category_id: Any, rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[str]]:
        """Convert mapped product facet evidence into taxonomy defaults."""
        category = self.category(category_id)
        if category is None:
            return {}, [f"taxonomy category not found: {category_id}"]
        defaults, warnings = self.resolve(category_id, "")
        facets = {str(facet.get("name")): facet for facet in category.get("facets", [])}
        for row in rows:
            facet_name = str(row.get("facet_name", "")).strip()
            source_field = str(row.get("source_field", "")).strip()
            raw_value = str(row.get("value", "")).strip()
            facet = facets.get(facet_name)
            if facet is None and source_field:
                facet_name = source_field
                facet = facets.get(facet_name)
            if not facet or not raw_value or str(row.get("mapping_status", "MAPPED")).upper() != "MAPPED":
                continue
            matches = []
            for value in facet.get("values", []):
                aliases = [value.get("value", ""), *(value.get("aliases") or [])]
                if any(_normalise(alias) == _normalise(raw_value) for alias in aliases):
                    matches.append(value)
            if len(matches) == 1:
                value = matches[0]
                defaults[facet_name] = {"code": int(value["code"]), "value": value.get("value", ""), "matched_alias": raw_value}
            elif not matches:
                warnings.append(f"product facet value not found in taxonomy: {facet_name}={raw_value}")
        return defaults, warnings


def load_taxonomy(path: Path) -> TaxonomyLoader:
    return TaxonomyLoader.from_path(path)


def taxonomy_from_category_facet_rows(frame: pd.DataFrame) -> dict[str, Any]:
    """Build a taxonomy payload from Backend ``category.facet`` text rows."""
    categories: dict[str, dict[str, Any]] = {}
    if "category_facet" not in frame.columns:
        raise TaxonomyValidationError("database rows do not contain category_facet")
    for _, row in frame.iterrows():
        raw = str(row.get("category_facet", "") or "").strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TaxonomyValidationError("category.facet contains invalid JSON") from exc
        category_id = str(row.get("category_id", "") or "").strip()
        if isinstance(parsed, dict):
            category_id = str(parsed.get("category_id", category_id)).strip()
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
            raise TaxonomyValidationError(f"conflicting category.facet rows: {category_id}")
        categories[category_id] = candidate
    if not categories:
        raise TaxonomyValidationError("no usable category.facet rows")
    return {"version": "backend-category-facet", "categories": list(categories.values())}


def build_product_facet_map(frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    """Index approved product facets by source ID and every supplied catalog ID."""
    result: dict[str, list[dict[str, Any]]] = {}
    normalized = frame.fillna("")
    if "mapping_status" in normalized:
        normalized = normalized[normalized["mapping_status"].astype(str).str.upper().isin({"MAPPED"})]
    for payload in normalized.to_dict(orient="records"):
        source_id = str(payload.get("source_product_id", "")).strip()
        catalog_id = str(payload.get("catalog_id", "")).strip()
        keys = [key for key in (source_id, catalog_id, f"catalog-seed-{source_id}") if key]
        for key in dict.fromkeys(keys):
            result.setdefault(key, []).append(payload)
    return result


def label_demand(demand_id: int | str, catalog_id: int | str, extra_requirement: str,
                 taxonomy: dict[str, Any], category_id: str = "") -> dict[str, Any]:
    loader = TaxonomyLoader(taxonomy)
    facet_values, warnings = loader.resolve(category_id, extra_requirement)
    return {"demand_id": demand_id, "catalog_id": catalog_id, "category_id": category_id,
            "facet_values": facet_values, "label": loader.encode(facet_values), "warnings": warnings}


def label_demands(frame: pd.DataFrame, loader: TaxonomyLoader,
                  catalog_category_map: dict[str, Any] | None = None,
                  product_facet_map: dict[str, list[dict[str, Any]]] | None = None) -> pd.DataFrame:
    """Batch label demands through ERD's catalog_id -> category_id path."""
    rows: list[dict[str, Any]] = []
    for _, demand in frame.iterrows():
        category_id = str(demand.get("category_id", "") or demand.get("kan_code", "")).strip()
        if not category_id and catalog_category_map:
            category_id = str(catalog_category_map.get(str(demand.get("catalog_id", "")), "") or "").strip()
        requirement = str(demand.get("extra_requirement", "") or "").strip()
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
            defaults, default_warnings = loader.product_defaults(category_id, (product_facet_map or {}).get(str(demand.get("catalog_id", "")), []))
            requested, request_warnings = loader.resolve(category_id, requirement)
            facet_values = defaults.copy()
            for facet_name, value in requested.items():
                if int(value.get("code", 0)) != 0:
                    facet_values[facet_name] = value
            warnings = default_warnings + request_warnings
            unresolved_items = []
            if requirement and any("did not match" in warning for warning in warnings):
                unresolved_items.append(requirement)
            label_status = "LABELED" if not warnings else "LABELED_WITH_REVIEW"
            label = loader.encode(facet_values)
        row = demand.to_dict()
        row.update({
            "category_id": str(category_id or ""),
            "label": label,
            "facet_values": json.dumps(facet_values, ensure_ascii=False, separators=(",", ":")),
            "desired_price_min": demand.get("desired_price_min", demand.get("desired_price", "")),
            "desired_price_max": demand.get("desired_price_max", ""),
            "quantity": demand.get("quantity", demand.get("desired_quantity", "")),
            "is_substitutable": demand.get("is_substitutable", True),
            "label_status": label_status,
            "label_warnings": json.dumps(warnings, ensure_ascii=False),
            "unresolved_items": json.dumps(unresolved_items, ensure_ascii=False),
        })
        rows.append(row)
    return pd.DataFrame(rows)

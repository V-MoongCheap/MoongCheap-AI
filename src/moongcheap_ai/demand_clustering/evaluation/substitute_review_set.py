"""Build a deterministic, evidence-rich review set for product substitution.

This is an offline gold-labeling utility.  Its review fields must never be
interpreted as a runtime demand status or as a reason to question a buyer.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from ...data_foundation.category_v2_1 import classify_v2_1
from ...data_foundation.health_v1 import (
    classify_record_type,
    normalize_form,
    split_ingredient_text,
    split_recognition_number,
)
from ..substitute_admission import character_ngram_cosine_similarity


SAMPLING_STRATA = (
    "SAME_CATEGORY_SHARED_INGREDIENT",
    "SAME_CATEGORY_HIGH_FUNCTION_TEXT",
    "SAME_CATEGORY_NO_SHARED_INGREDIENT",
    "CROSS_CATEGORY_SHARED_INGREDIENT",
    "CROSS_CATEGORY_CONTROL",
    "NON_FINISHED_PRODUCT_PAIR",
    "MISSING_REQUIRED_EVIDENCE",
)

REVIEW_COLUMNS = (
    "pair_id",
    "reciprocal_group_id",
    "split",
    "source_product_id",
    "candidate_product_id",
    "source_product_name",
    "candidate_product_name",
    "source_service_category",
    "candidate_service_category",
    "source_record_type_candidate",
    "candidate_record_type_candidate",
    "source_product_form",
    "candidate_product_form",
    "source_functional_ingredients",
    "candidate_functional_ingredients",
    "shared_functional_ingredients",
    "source_main_functionality",
    "candidate_main_functionality",
    "source_intake_method",
    "candidate_intake_method",
    "category_match",
    "ingredient_jaccard",
    "function_text_similarity",
    "source_evidence_complete",
    "candidate_evidence_complete",
    "sampling_stratum",
    "gold_label",
    "label_reason_codes",
    "critical_negative",
    "reviewer_1",
    "reviewer_2",
    "adjudicator",
    "reviewed_at",
)


def _text(value: object) -> str:
    return re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFKC", str(value or "")),
    ).strip()


def _stable_hash(*values: object) -> str:
    payload = "\x1f".join(str(value) for value in values)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalized_ingredients(value: object) -> tuple[str, ...]:
    ingredients, _status = split_ingredient_text(value)
    normalized = {
        _text(split_recognition_number(ingredient)[0]).casefold()
        for ingredient in ingredients
        if _text(split_recognition_number(ingredient)[0])
    }
    return tuple(sorted(normalized))


@dataclass(frozen=True, slots=True)
class ReviewProduct:
    source_product_id: str
    product_name: str
    service_category: str
    record_type_candidate: str
    product_form: str
    functional_ingredients: tuple[str, ...]
    main_functionality: str
    intake_method: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ReviewProduct:
        product_id = _text(value.get("source_product_id"))
        if not product_id:
            raise ValueError("source_product_id must not be empty")
        source_category = _text(value.get("product_type"))
        if source_category:
            category_key, _name, _confidence, _reason = classify_v2_1(
                pd.Series(value)
            )
            service_category = f"health-functional-food:{category_key.lower()}"
        else:
            service_category = "UNMAPPED"
        record_type, _evidence, _confidence = classify_record_type(
            pd.Series(value)
        )
        return cls(
            source_product_id=product_id,
            product_name=_text(value.get("name")),
            service_category=service_category,
            record_type_candidate=record_type,
            product_form=normalize_form(value.get("product_form")),
            functional_ingredients=_normalized_ingredients(
                value.get("functional_ingredients")
            ),
            main_functionality=_text(value.get("main_functionality")),
            intake_method=_text(value.get("intake_method")),
        )

    @property
    def evidence_complete(self) -> bool:
        return bool(
            self.product_name
            and self.service_category != "UNMAPPED"
            and self.record_type_candidate != "UNCERTAIN"
            and self.functional_ingredients
            and self.main_functionality
        )


def _ordered_ids(
    product_ids: Iterable[str],
    *,
    seed: int,
    salt: str,
) -> list[str]:
    return sorted(
        set(product_ids),
        key=lambda product_id: (
            _stable_hash(seed, salt, product_id),
            product_id,
        ),
    )


def _add_neighbor_pairs(
    target: set[tuple[str, str]],
    product_ids: Iterable[str],
    *,
    seed: int,
    salt: str,
    window: int,
) -> None:
    ordered = _ordered_ids(product_ids, seed=seed, salt=salt)
    if len(ordered) < 2:
        return
    max_offset = min(window, len(ordered) - 1)
    for index, left in enumerate(ordered):
        for offset in range(1, max_offset + 1):
            right = ordered[(index + offset) % len(ordered)]
            if left != right:
                target.add(tuple(sorted((left, right))))


def _ingredient_jaccard(
    left: ReviewProduct,
    right: ReviewProduct,
) -> float | None:
    left_values = set(left.functional_ingredients)
    right_values = set(right.functional_ingredients)
    if not left_values or not right_values:
        return None
    return round(
        len(left_values & right_values) / len(left_values | right_values),
        6,
    )


def _pair_stratum(left: ReviewProduct, right: ReviewProduct) -> str:
    if (
        "INGREDIENT_MATERIAL_CANDIDATE"
        in {left.record_type_candidate, right.record_type_candidate}
    ):
        return "NON_FINISHED_PRODUCT_PAIR"
    if not left.evidence_complete or not right.evidence_complete:
        return "MISSING_REQUIRED_EVIDENCE"

    category_match = left.service_category == right.service_category
    shared_ingredients = set(left.functional_ingredients) & set(
        right.functional_ingredients
    )
    if not category_match:
        return (
            "CROSS_CATEGORY_SHARED_INGREDIENT"
            if shared_ingredients
            else "CROSS_CATEGORY_CONTROL"
        )
    if shared_ingredients:
        return "SAME_CATEGORY_SHARED_INGREDIENT"

    function_similarity = character_ngram_cosine_similarity(
        left.main_functionality,
        right.main_functionality,
    )
    if function_similarity >= 0.55:
        return "SAME_CATEGORY_HIGH_FUNCTION_TEXT"
    return "SAME_CATEGORY_NO_SHARED_INGREDIENT"


def _candidate_pairs(
    products: Sequence[ReviewProduct],
    *,
    seed: int,
) -> set[tuple[str, str]]:
    by_category: dict[str, list[str]] = defaultdict(list)
    by_ingredient: dict[str, list[str]] = defaultdict(list)
    product_by_id = {product.source_product_id: product for product in products}
    for product in products:
        by_category[product.service_category].append(product.source_product_id)
        for ingredient in product.functional_ingredients:
            by_ingredient[ingredient].append(product.source_product_id)

    pairs: set[tuple[str, str]] = set()
    for category, product_ids in sorted(by_category.items()):
        _add_neighbor_pairs(
            pairs,
            product_ids,
            seed=seed,
            salt=f"category:{category}",
            window=12,
        )
    for ingredient, product_ids in sorted(by_ingredient.items()):
        _add_neighbor_pairs(
            pairs,
            product_ids,
            seed=seed,
            salt=f"ingredient:{ingredient}",
            window=6,
        )

    all_ids = [product.source_product_id for product in products]
    global_order = _ordered_ids(all_ids, seed=seed, salt="global")
    if len(global_order) > 1:
        for index, left_id in enumerate(global_order):
            left = product_by_id[left_id]
            for offset in range(1, min(24, len(global_order) - 1) + 1):
                right_id = global_order[(index + offset) % len(global_order)]
                right = product_by_id[right_id]
                if left.service_category != right.service_category:
                    pairs.add(tuple(sorted((left_id, right_id))))
                    break

    complete_ids = [
        product.source_product_id
        for product in products
        if product.evidence_complete
    ]
    complete_order = _ordered_ids(
        complete_ids,
        seed=seed,
        salt="complete",
    )
    if complete_order:
        for product in products:
            if product.evidence_complete:
                continue
            index = int(
                _stable_hash(seed, "missing", product.source_product_id)[:16],
                16,
            ) % len(complete_order)
            candidate_id = complete_order[index]
            if candidate_id != product.source_product_id:
                pairs.add(
                    tuple(sorted((product.source_product_id, candidate_id)))
                )
    return pairs


def _select_diverse_pairs(
    pairs: Iterable[tuple[str, str]],
    *,
    count: int,
    seed: int,
    stratum: str,
) -> tuple[tuple[str, str], ...]:
    ordered = sorted(
        set(pairs),
        key=lambda pair: (
            _stable_hash(seed, stratum, *pair),
            pair,
        ),
    )
    selected: list[tuple[str, str]] = []
    selected_set: set[tuple[str, str]] = set()
    degree: dict[str, int] = defaultdict(int)
    for degree_limit in (1, 2, 3, math.inf):
        for pair in ordered:
            if pair in selected_set:
                continue
            if any(degree[product_id] >= degree_limit for product_id in pair):
                continue
            selected.append(pair)
            selected_set.add(pair)
            for product_id in pair:
                degree[product_id] += 1
            if len(selected) == count:
                return tuple(selected)
    return tuple(selected)


def _split_for_source(source_product_id: str, seed: int) -> str:
    bucket = int(
        _stable_hash(seed, "source-split", source_product_id)[:16],
        16,
    ) % 10
    return "development" if bucket < 7 else "holdout"


def build_substitute_product_pair_review_set(
    rows: Iterable[Mapping[str, Any]],
    *,
    directional_pairs_per_stratum: int = 60,
    seed: int = 20260906,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    """Build reciprocal directional pairs with blank human-label fields."""

    if directional_pairs_per_stratum < 2 or directional_pairs_per_stratum % 2:
        raise ValueError("directional_pairs_per_stratum must be a positive even number")
    products = tuple(ReviewProduct.from_mapping(row) for row in rows)
    if len(products) < 2:
        raise ValueError("at least two products are required")
    product_ids = [product.source_product_id for product in products]
    if len(product_ids) != len(set(product_ids)):
        raise ValueError("duplicate source_product_id")

    product_by_id = {product.source_product_id: product for product in products}
    pools: dict[str, set[tuple[str, str]]] = {
        stratum: set() for stratum in SAMPLING_STRATA
    }
    for pair in _candidate_pairs(products, seed=seed):
        left, right = (product_by_id[product_id] for product_id in pair)
        pools[_pair_stratum(left, right)].add(pair)

    unordered_target = directional_pairs_per_stratum // 2
    selected = {
        stratum: _select_diverse_pairs(
            pools[stratum],
            count=unordered_target,
            seed=seed,
            stratum=stratum,
        )
        for stratum in SAMPLING_STRATA
    }

    output_rows: list[dict[str, Any]] = []
    for stratum in SAMPLING_STRATA:
        for left_id, right_id in selected[stratum]:
            reciprocal_id = "sprg-" + _stable_hash(
                seed,
                "reciprocal",
                left_id,
                right_id,
            )[:12]
            for source_id, candidate_id in (
                (left_id, right_id),
                (right_id, left_id),
            ):
                source = product_by_id[source_id]
                candidate = product_by_id[candidate_id]
                shared = sorted(
                    set(source.functional_ingredients)
                    & set(candidate.functional_ingredients)
                )
                output_rows.append({
                    "pair_id": "spr-" + _stable_hash(
                        seed,
                        "directional",
                        source_id,
                        candidate_id,
                    )[:12],
                    "reciprocal_group_id": reciprocal_id,
                    "split": _split_for_source(source_id, seed),
                    "source_product_id": source_id,
                    "candidate_product_id": candidate_id,
                    "source_product_name": source.product_name,
                    "candidate_product_name": candidate.product_name,
                    "source_service_category": source.service_category,
                    "candidate_service_category": candidate.service_category,
                    "source_record_type_candidate": (
                        source.record_type_candidate
                    ),
                    "candidate_record_type_candidate": (
                        candidate.record_type_candidate
                    ),
                    "source_product_form": source.product_form,
                    "candidate_product_form": candidate.product_form,
                    "source_functional_ingredients": " | ".join(
                        source.functional_ingredients
                    ),
                    "candidate_functional_ingredients": " | ".join(
                        candidate.functional_ingredients
                    ),
                    "shared_functional_ingredients": " | ".join(shared),
                    "source_main_functionality": source.main_functionality,
                    "candidate_main_functionality": candidate.main_functionality,
                    "source_intake_method": source.intake_method,
                    "candidate_intake_method": candidate.intake_method,
                    "category_match": (
                        source.service_category == candidate.service_category
                    ),
                    "ingredient_jaccard": _ingredient_jaccard(
                        source,
                        candidate,
                    ),
                    "function_text_similarity": (
                        character_ngram_cosine_similarity(
                            source.main_functionality,
                            candidate.main_functionality,
                        )
                    ),
                    "source_evidence_complete": source.evidence_complete,
                    "candidate_evidence_complete": candidate.evidence_complete,
                    "sampling_stratum": stratum,
                    "gold_label": "",
                    "label_reason_codes": "",
                    "critical_negative": "",
                    "reviewer_1": "",
                    "reviewer_2": "",
                    "adjudicator": "",
                    "reviewed_at": "",
                })

    output_rows.sort(key=lambda row: (row["sampling_stratum"], row["pair_id"]))
    counts = {
        stratum: sum(
            row["sampling_stratum"] == stratum for row in output_rows
        )
        for stratum in SAMPLING_STRATA
    }
    split_sources = {
        split: len({
            row["source_product_id"]
            for row in output_rows
            if row["split"] == split
        })
        for split in ("development", "holdout")
    }
    summary = {
        "schemaVersion": "substitute-product-pair-review-set.v1",
        "seed": seed,
        "productCount": len(products),
        "directionalPairCount": len(output_rows),
        "targetDirectionalPairsPerStratum": directional_pairs_per_stratum,
        "samplingStratumCounts": counts,
        "samplingStratumShortfalls": {
            stratum: directional_pairs_per_stratum - count
            for stratum, count in counts.items()
            if count < directional_pairs_per_stratum
        },
        "uniqueSourceProductCountBySplit": split_sources,
        "goldLabelsPrepopulated": False,
        "runtimeReviewStateCreated": False,
    }
    return tuple(output_rows), summary

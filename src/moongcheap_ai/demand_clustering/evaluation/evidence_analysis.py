"""Measure whether MFDS fields can support substitute-product decisions.

The analysis separates three questions that must not be conflated:

* Is a product operationally eligible for a domestic finished-product pool?
* Can every declared functional ingredient be linked to an I2710 reference?
* Is the product's free-text functionality consistent enough to audit that link?

It does not assign substitute labels. In particular, a reference link or a high
text score is evidence about a product, not proof that two products substitute
for one another.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from ...data_foundation.health_v1 import classify_record_type, split_ingredient_text
from ..substitute_admission import character_ngram_cosine_similarity


CORE_PRODUCT_FIELDS = (
    "name",
    "product_type",
    "main_functionality",
    "functional_ingredients",
)
STRICT_PRODUCT_FIELDS = (*CORE_PRODUCT_FIELDS, "product_form", "intake_method")
SAFE_RESOLUTION_STATUSES = {
    "EXACT",
    "RECOGNITION_ID",
    "GENERIC_LEGACY_ALIAS",
    "FUNCTION_EQUIVALENT_ALIAS",
}
EXPORT_MARKER_RE = re.compile(r"(?:전량\s*)?수출\s*(?:용|전용)|\bexport\b", re.I)
RECOGNITION_NUMBER_RE = re.compile(r"(?:제\s*)?(20\d{2})\s*-\s*(\d+)\s*(?:호)?")
RECOGNITION_PHRASE_RE = re.compile(
    r"\(\s*(?:기능성\s*원료\s*인정\s*)?(?:제\s*)?20\d{2}\s*-\s*\d+\s*(?:호)?\s*\)"
    r"|(?:기능성\s*원료\s*인정\s*)(?:제\s*)?20\d{2}\s*-\s*\d+\s*(?:호)?"
)
REFERENCE_INDIRECTION_RE = re.compile(r"에\s*따름|참조")


def _text(value: object) -> str:
    return re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFKC", str(value or "")),
    ).strip()


def _function_text(value: object) -> str:
    """Normalize whitespace without folding circled list markers to digits."""

    return re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFC", str(value or "")),
    ).strip()


def _key(value: object) -> str:
    """Return a punctuation-insensitive key without dropping identity data."""

    return re.sub(r"[^0-9a-z가-힣]+", "", _text(value).casefold())


def _recognition_number(value: object) -> str:
    match = RECOGNITION_NUMBER_RE.search(_text(value))
    return f"{match.group(1)}-{int(match.group(2))}" if match else ""


def _reference_base_key(value: object) -> str:
    text = RECOGNITION_PHRASE_RE.sub("", _text(value))
    return _key(text)


def _generic_legacy_key(value: object) -> str:
    text = re.sub(r"\(\s*원료성\s*\)", "", _text(value))
    text = re.sub(r"\s*제품$", "", text)
    return _key(text)


def _function_key(value: object) -> str:
    """Normalize a functionality field for conservative text diagnostics."""

    text = _text(value).casefold()
    text = re.split(r"(?:\(\s*2\s*\)|②)\s*일일\s*섭취량", text, maxsplit=1)[0]
    text = re.sub(r"기능성\s*내용\s*:", " ", text)
    text = re.sub(r"[①②③④⑤⑥⑦⑧⑨⑩]", "", text)
    text = re.sub(r"(?:^|\s)[\(\[]?\d+[\)\].]\s*", " ", text)
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def _korean_function_signature(value: object) -> str:
    """Collapse formatting and translated text, but not semantic synonyms."""

    text = _text(value).casefold()
    text = re.split(r"\(?\s*영문\s*\)?", text, maxsplit=1)[0]
    text = re.split(r"(?:\(\s*2\s*\)|②)\s*일일\s*섭취량", text, maxsplit=1)[0]
    text = re.sub(r"\(?\s*국문\s*\)?|기능성\s*내용\s*:", " ", text)
    text = re.sub(r"생리활성기능\s*\d등급|기타\s*[ⅠIⅡV]+", " ", text)
    return re.sub(r"[^0-9가-힣]+", "", text)


@dataclass(frozen=True)
class _ReferenceEvidence:
    category_names: tuple[str, ...]
    functions: tuple[str, ...]
    used_indirection: bool = False


@dataclass(frozen=True)
class _IngredientResolution:
    token: str
    status: str
    evidence: _ReferenceEvidence

    @property
    def safely_resolved(self) -> bool:
        return self.status in SAFE_RESOLUTION_STATUSES


class _ReferenceIndex:
    """Resolve only identities supported by exact or auditable MFDS evidence."""

    def __init__(self, references: pd.DataFrame) -> None:
        self._exact: dict[str, list[pd.Series]] = defaultdict(list)
        self._recognition: dict[str, list[pd.Series]] = defaultdict(list)
        self._base: dict[str, list[pd.Series]] = defaultdict(list)
        for _, row in references.iterrows():
            name = _text(row["category_reference_name"])
            if not name:
                continue
            self._exact[_key(name)].append(row)
            self._base[_reference_base_key(name)].append(row)
            recognition_number = _recognition_number(name)
            if recognition_number:
                self._recognition[recognition_number].append(row)

    def _functions_for_row(
        self,
        row: pd.Series,
        *,
        depth: int = 0,
    ) -> tuple[set[str], bool]:
        # NFKC changes `①` to bare `1`, which destroys the enumeration boundary
        # needed by the atomic-claim parser. Preserve the marker until parsing.
        function = _function_text(row["main_functionality"])
        if not function:
            return set(), False
        if depth >= 2 or not REFERENCE_INDIRECTION_RE.search(function):
            return {function}, False

        prefix_key = _key(re.split(r"에\s*따름|참조", function, maxsplit=1)[0])
        target_keys = [
            key for key in self._exact if key and prefix_key.endswith(key)
        ]
        if not target_keys:
            return set(), True
        target_rows = self._exact[max(target_keys, key=len)]
        functions: set[str] = set()
        for target_row in target_rows:
            target_functions, _ = self._functions_for_row(
                target_row,
                depth=depth + 1,
            )
            functions.update(target_functions)
        return functions, True

    def _evidence(self, rows: list[pd.Series]) -> _ReferenceEvidence:
        functions: set[str] = set()
        used_indirection = False
        for row in rows:
            row_functions, row_used_indirection = self._functions_for_row(row)
            functions.update(row_functions)
            used_indirection |= row_used_indirection
        return _ReferenceEvidence(
            category_names=tuple(
                sorted({_text(row["category_reference_name"]) for row in rows})
            ),
            functions=tuple(sorted(functions)),
            used_indirection=used_indirection,
        )

    def _has_one_function_signature(self, rows: list[pd.Series]) -> bool:
        signatures = {
            _function_key(function)
            for function in self._evidence(rows).functions
            if _function_key(function)
        }
        return len(signatures) == 1

    def resolve(self, value: object) -> _IngredientResolution:
        token = _text(value)
        if not token:
            return _IngredientResolution(
                token,
                "EMPTY",
                _ReferenceEvidence((), ()),
            )

        if rows := self._exact.get(_key(token)):
            return _IngredientResolution(token, "EXACT", self._evidence(rows))

        recognition_number = _recognition_number(token)
        if recognition_number and (rows := self._recognition.get(recognition_number)):
            if len({_key(row["category_reference_name"]) for row in rows}) == 1:
                return _IngredientResolution(
                    token,
                    "RECOGNITION_ID",
                    self._evidence(rows),
                )
            return _IngredientResolution(
                token,
                "AMBIGUOUS_REFERENCE",
                self._evidence(rows),
            )

        legacy_key = _generic_legacy_key(token)
        if legacy_key != _key(token) and (rows := self._exact.get(legacy_key)):
            return _IngredientResolution(
                token,
                "GENERIC_LEGACY_ALIAS",
                self._evidence(rows),
            )

        if rows := self._base.get(_reference_base_key(token)):
            if self._has_one_function_signature(rows):
                return _IngredientResolution(
                    token,
                    "FUNCTION_EQUIVALENT_ALIAS",
                    self._evidence(rows),
                )
            return _IngredientResolution(
                token,
                "AMBIGUOUS_REFERENCE",
                self._evidence(rows),
            )

        return _IngredientResolution(
            token,
            "UNMATCHED",
            _ReferenceEvidence((), ()),
        )


def _complete_mask(frame: pd.DataFrame, fields: Iterable[str]) -> pd.Series:
    masks = [frame[field].map(_text).ne("") for field in fields]
    result = pd.Series(True, index=frame.index)
    for mask in masks:
        result &= mask
    return result


def _quantiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    series = pd.Series(values, dtype=float)
    return {
        "min": round(float(series.min()), 6),
        "p10": round(float(series.quantile(0.10)), 6),
        "p25": round(float(series.quantile(0.25)), 6),
        "median": round(float(series.median()), 6),
        "p75": round(float(series.quantile(0.75)), 6),
        "p90": round(float(series.quantile(0.90)), 6),
        "max": round(float(series.max()), 6),
    }


def _structural_status(
    product: pd.Series,
    resolutions: list[_IngredientResolution],
) -> str:
    if any(not _text(product[field]) for field in CORE_PRODUCT_FIELDS):
        return "SOURCE_FIELDS_INCOMPLETE"
    if not resolutions:
        return "SOURCE_INGREDIENTS_EMPTY"
    statuses = {resolution.status for resolution in resolutions}
    if "AMBIGUOUS_REFERENCE" in statuses:
        return "REFERENCE_AMBIGUOUS"
    if "UNMATCHED" in statuses:
        return (
            "REFERENCE_PARTIAL"
            if any(resolution.safely_resolved for resolution in resolutions)
            else "REFERENCE_UNRESOLVED"
        )
    if any(not resolution.evidence.functions for resolution in resolutions):
        return "REFERENCE_FUNCTION_MISSING"
    return "STRUCTURED_RECONSTRUCTION_READY"


def _operational_status(product: pd.Series, record_type: str) -> str:
    if record_type == "INGREDIENT_MATERIAL_CANDIDATE":
        return "EXCLUDED_INGREDIENT_MATERIAL"
    if record_type != "FINISHED_PRODUCT_CANDIDATE":
        return "EXCLUDED_RECORD_TYPE_UNCERTAIN"
    if EXPORT_MARKER_RE.search(_text(product["name"])):
        return "EXCLUDED_EXPORT_MARKER"
    return "ELIGIBLE_FINISHED_PRODUCT"


def _approval_period(value: object) -> str:
    match = re.match(r"(\d{4})", _text(value))
    if not match:
        return "UNKNOWN"
    year = int(match.group(1))
    if year < 2010:
        return "BEFORE_2010"
    if year < 2015:
        return "2010_2014"
    if year < 2020:
        return "2015_2019"
    return "2020_OR_LATER"


def analyze_substitute_evidence(
    products: pd.DataFrame,
    references: pd.DataFrame,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return summary and diagnostics for MFDS evidence suitability."""

    required_product_columns = set(STRICT_PRODUCT_FIELDS) | {"source_product_id"}
    required_reference_columns = {
        "category_reference_name",
        "main_functionality",
        "ingredient_name",
    }
    if missing := sorted(required_product_columns - set(products.columns)):
        raise ValueError(f"I0030 frame missing columns: {', '.join(missing)}")
    if missing := sorted(required_reference_columns - set(references.columns)):
        raise ValueError(f"I2710 frame missing columns: {', '.join(missing)}")

    product_frame = products.fillna("").copy()
    reference_frame = references.fillna("").copy()
    core_complete = _complete_mask(product_frame, CORE_PRODUCT_FIELDS)
    strict_complete = _complete_mask(product_frame, STRICT_PRODUCT_FIELDS)
    reference_index = _ReferenceIndex(reference_frame)

    record_type_series = pd.Series(
        [classify_record_type(row)[0] for _, row in product_frame.iterrows()],
        index=product_frame.index,
    )
    operational_status = pd.Series(
        [
            _operational_status(product, record_type_series.loc[index])
            for index, product in product_frame.iterrows()
        ],
        index=product_frame.index,
    )

    type_resolutions = product_frame["product_type"].map(reference_index.resolve)
    type_exact_match = type_resolutions.map(lambda resolution: resolution.status == "EXACT")
    type_safe_match = type_resolutions.map(lambda resolution: resolution.safely_resolved)

    ingredient_parse_status: Counter[str] = Counter()
    ingredient_resolution_status: Counter[str] = Counter()
    product_resolutions: dict[int, list[_IngredientResolution]] = {}
    issue_accumulator: dict[tuple[str, str], dict[str, Any]] = {}
    for index, product in product_frame.iterrows():
        tokens, parse_status = split_ingredient_text(product["functional_ingredients"])
        ingredient_parse_status[parse_status] += 1
        resolutions = [reference_index.resolve(token) for token in tokens]
        product_resolutions[index] = resolutions
        for resolution in resolutions:
            ingredient_resolution_status[resolution.status] += 1
            if resolution.safely_resolved:
                continue
            issue_key = (resolution.status, resolution.token)
            issue = issue_accumulator.setdefault(
                issue_key,
                {
                    "resolution_status": resolution.status,
                    "ingredient_token": resolution.token,
                    "occurrence_count": 0,
                    "product_ids": [],
                    "candidate_reference_names": "|".join(
                        resolution.evidence.category_names
                    ),
                },
            )
            issue["occurrence_count"] += 1
            if len(issue["product_ids"]) < 5:
                issue["product_ids"].append(_text(product["source_product_id"]))
    ingredient_issue_rows: list[dict[str, Any]] = []
    for issue in issue_accumulator.values():
        product_ids = issue.pop("product_ids")
        ingredient_issue_rows.append(
            {**issue, "example_product_ids": "|".join(product_ids)}
        )
    ingredient_issues = pd.DataFrame(ingredient_issue_rows)
    if not ingredient_issues.empty:
        ingredient_issues = ingredient_issues.sort_values(
            ["resolution_status", "occurrence_count", "ingredient_token"],
            ascending=[True, False, True],
        )

    structural_status = pd.Series(
        [
            _structural_status(product, product_resolutions[index])
            for index, product in product_frame.iterrows()
        ],
        index=product_frame.index,
    )
    ingredient_any_safe = pd.Series(
        [
            any(
                resolution.safely_resolved
                for resolution in product_resolutions[index]
            )
            for index in product_frame.index
        ],
        index=product_frame.index,
    )
    structured_reference_match = type_safe_match | ingredient_any_safe

    comparison_rows: list[dict[str, Any]] = []
    function_scores: list[float] = []
    expected_function_counts: list[int] = []
    function_scores_by_approval_period: dict[str, list[float]] = defaultdict(list)
    products_with_indirect_reference_function = 0
    exact_function_matches = 0
    comparison_mask = (
        operational_status.eq("ELIGIBLE_FINISHED_PRODUCT")
        & structural_status.eq("STRUCTURED_RECONSTRUCTION_READY")
    )
    for index, product in product_frame.loc[comparison_mask].iterrows():
        expected_functions = sorted(
            {
                function
                for resolution in product_resolutions[index]
                for function in resolution.evidence.functions
                if _function_key(function)
            }
        )
        expected_function_counts.append(len(expected_functions))
        products_with_indirect_reference_function += int(
            any(
                resolution.evidence.used_indirection
                for resolution in product_resolutions[index]
            )
        )
        product_function = _text(product["main_functionality"])
        product_function_key = _function_key(product_function)
        expected_function_key = "".join(
            _function_key(function) for function in expected_functions
        )
        exact = product_function_key == expected_function_key
        exact_function_matches += int(exact)
        score = character_ngram_cosine_similarity(
            product_function_key,
            expected_function_key,
        )
        function_scores.append(score)
        function_scores_by_approval_period[_approval_period(
            product.get("approval_date", "")
        )].append(score)
        comparison_rows.append(
            {
                "source_product_id": product["source_product_id"],
                "product_name": product["name"],
                "product_type": product["product_type"],
                "functional_ingredients": product["functional_ingredients"],
                "product_functionality": product_function,
                "reconstructed_i2710_functionality": " | ".join(
                    expected_functions
                ),
                "reference_function_count": len(expected_functions),
                "character_bigram_similarity": score,
                "exact_normalized_match": exact,
            }
        )

    divergence = pd.DataFrame(comparison_rows)
    if not divergence.empty:
        divergence = divergence.sort_values(
            ["character_bigram_similarity", "source_product_id"],
            ascending=[True, True],
        ).head(200)

    unmatched_type_mask = ~type_safe_match
    unmatched_types = (
        product_frame.loc[unmatched_type_mask, "product_type"]
        .map(_text)
        .value_counts()
        .rename_axis("product_type")
        .reset_index(name="product_count")
    )
    unmatched_types = unmatched_types.loc[unmatched_types["product_type"].ne("")]

    multi_function_signal = product_frame["main_functionality"].map(
        lambda value: len(re.findall(r"도움|필요", _text(value))) >= 2
    )
    reference_multi_function_signal = reference_frame["main_functionality"].map(
        lambda value: len(re.findall(r"도움|필요", _text(value))) >= 2
    )
    korean_function_signature_counts = (
        reference_frame["main_functionality"]
        .map(_korean_function_signature)
        .loc[lambda values: values.ne("")]
        .value_counts()
    )
    finished_ready = core_complete & record_type_series.eq(
        "FINISHED_PRODUCT_CANDIDATE"
    )
    eligible_mask = operational_status.eq("ELIGIBLE_FINISHED_PRODUCT")
    ready_mask = structural_status.eq("STRUCTURED_RECONSTRUCTION_READY")
    product_type_counts = product_frame["product_type"].map(_text).value_counts()

    summary = {
        "schemaVersion": "mfds-substitute-evidence-analysis.v2",
        "i0030": {
            "rows": len(product_frame),
            "uniqueProductTypes": int(
                product_type_counts.index.to_series().ne("").sum()
            ),
            "coreEvidenceCompleteRows": int(core_complete.sum()),
            "strictEvidenceCompleteRows": int(strict_complete.sum()),
            "finishedCoreReadyRows": int(finished_ready.sum()),
            "recordTypeCandidateCounts": {
                str(key): int(value)
                for key, value in record_type_series.value_counts().items()
            },
            "operationalEligibilityCounts": {
                str(key): int(value)
                for key, value in operational_status.value_counts().items()
            },
            "multiFunctionWordingSignalRows": int(multi_function_signal.sum()),
            "missingByCoreField": {
                field: int(product_frame[field].map(_text).eq("").sum())
                for field in STRICT_PRODUCT_FIELDS
            },
            "topProductForms": {
                str(key): int(value)
                for key, value in product_frame["product_form"]
                .map(_text)
                .value_counts()
                .head(12)
                .items()
            },
        },
        "i2710": {
            "rows": len(reference_frame),
            "uniqueReferenceNames": int(
                reference_frame["category_reference_name"]
                .map(_text)
                .replace("", pd.NA)
                .nunique()
            ),
            "uniqueFunctionTexts": int(
                reference_frame["main_functionality"]
                .map(_text)
                .replace("", pd.NA)
                .nunique()
            ),
            "uniqueKoreanFunctionSignatures": len(
                korean_function_signature_counts
            ),
            "singletonKoreanFunctionSignatures": int(
                korean_function_signature_counts.eq(1).sum()
            ),
            "reusedKoreanFunctionSignatureGroups": int(
                korean_function_signature_counts.ge(2).sum()
            ),
            "rowsInReusedKoreanFunctionSignatureGroups": int(
                korean_function_signature_counts.loc[
                    korean_function_signature_counts.ge(2)
                ].sum()
            ),
            "multiFunctionWordingSignalRows": int(
                reference_multi_function_signal.sum()
            ),
            "indirectFunctionReferenceRows": int(
                reference_frame["main_functionality"]
                .map(lambda value: bool(REFERENCE_INDIRECTION_RE.search(_text(value))))
                .sum()
            ),
            "missingByField": {
                column: int(reference_frame[column].map(_text).eq("").sum())
                for column in reference_frame.columns
            },
        },
        "deterministicReferenceLinkage": {
            "productTypeExactMatchRows": int(type_exact_match.sum()),
            "productTypeSafeMatchRows": int(type_safe_match.sum()),
            "structuredReferenceMatchRows": int(structured_reference_match.sum()),
            "unmatchedProductTypeRows": int(unmatched_type_mask.sum()),
            "unmatchedUniqueProductTypes": len(unmatched_types),
            "ingredientParseStatusCounts": dict(ingredient_parse_status),
            "ingredientResolutionStatusCounts": dict(
                ingredient_resolution_status
            ),
            "ingredientTokens": int(sum(ingredient_resolution_status.values())),
            "safelyResolvedIngredientTokens": int(
                sum(
                    count
                    for status, count in ingredient_resolution_status.items()
                    if status in SAFE_RESOLUTION_STATUSES
                )
            ),
            "productsWithAnySafeIngredientMatch": int(ingredient_any_safe.sum()),
        },
        "structuredFunctionReconstruction": {
            "allProductStatusCounts": {
                str(key): int(value)
                for key, value in structural_status.value_counts().items()
            },
            "eligibleProductStatusCounts": {
                str(key): int(value)
                for key, value in structural_status.loc[
                    eligible_mask
                ].value_counts().items()
            },
            "eligibleProducts": int(eligible_mask.sum()),
            "eligibleReadyProducts": int((eligible_mask & ready_mask).sum()),
            "eligibleReadyRate": round(
                float((eligible_mask & ready_mask).sum() / eligible_mask.sum()),
                6,
            )
            if eligible_mask.any()
            else 0.0,
            "referenceFunctionsPerComparedProductQuantiles": _quantiles(
                [float(value) for value in expected_function_counts]
            ),
        },
        "declaredVsReconstructedFunctionText": {
            "scope": "eligible finished products with complete structured reconstruction",
            "comparedRows": len(function_scores),
            "exactNormalizedMatchRows": exact_function_matches,
            "similarityAtLeast090Rows": sum(
                score >= 0.90 for score in function_scores
            ),
            "similarityAtLeast075Rows": sum(
                score >= 0.75 for score in function_scores
            ),
            "similarityBelow050Rows": sum(
                score < 0.50 for score in function_scores
            ),
            "productsWithIndirectReferenceFunction": (
                products_with_indirect_reference_function
            ),
            "characterBigramSimilarityQuantiles": _quantiles(function_scores),
            "byApprovalPeriod": {
                period: {
                    "rows": len(scores),
                    "similarityBelow050Rows": sum(
                        score < 0.50 for score in scores
                    ),
                    "characterBigramSimilarityQuantiles": _quantiles(scores),
                }
                for period, scores in sorted(
                    function_scores_by_approval_period.items()
                )
            },
        },
        "methodNotes": [
            "Reference linkage is a deterministic coverage baseline, not a substitute label.",
            "Exact matching preserves recognition numbers; it does not collapse individually recognized ingredients into a generic name.",
            "Recognition-ID matching accepts notation differences only when the I2710 identity is unique.",
            "A no-ID alias shared by references with different functions is AMBIGUOUS_REFERENCE, not an automatic match.",
            "Operational eligibility is a heuristic: finished-product intake text and no export marker in the product name.",
            "Function-text similarity is a diagnostic queue only; a low score is not automatically a source conflict.",
            "A Korean function signature removes formatting and translation only; it does not merge semantic synonyms or split compound claims.",
            "Multi-function wording signal means two or more 도움/필요 occurrences; it is not a final function parser.",
        ],
    }
    return summary, unmatched_types, ingredient_issues, divergence

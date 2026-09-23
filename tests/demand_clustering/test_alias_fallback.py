"""A changes must preserve B-only operation and cannot silently corrupt targets."""

import csv
import json
from copy import deepcopy
from pathlib import Path

import pytest

from moongcheap_ai.demand_clustering.part_a_integration import build_part_b_parser
from moongcheap_ai.demand_constraints import DemandConstraintParser

ROOT = Path(__file__).resolve().parents[2]
TAXONOMY = json.loads((ROOT / "config/facet_taxonomy_v2_2.json").read_text())
PRIMARY = ROOT / "config/model1_aliases_reviewed_v2.json"
BASE = ROOT / "config/demand_constraint_aliases.json"
RULES = ROOT / "config/demand_constraint_rules.json"
CATEGORY = "health-functional-food:probiotics"
CASES_PATH = Path(__file__).parent / "fixtures/approved_alias_bindings_v2_2.csv"
with CASES_PATH.open(encoding="utf-8", newline="") as handle:
    APPROVED_CASES = list(csv.DictReader(handle))


def build(primary=PRIMARY, taxonomy=TAXONOMY):
    return build_part_b_parser(
        taxonomy, rules_path=RULES, aliases_path=primary, compatibility_aliases_path=BASE,
    )


def write_primary(tmp_path, payload):
    path = tmp_path / "a.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def primary_payload():
    return json.loads(PRIMARY.read_text(encoding="utf-8"))


def interpreted(parser, text, category=CATEGORY):
    result = parser.interpret(category, text, is_substitutable=True)
    return result.status, {(c.facet_name, c.value_code, c.constraint_type) for c in result.constraints}


@pytest.fixture(scope="module")
def parsers():
    original = deepcopy(TAXONOMY)
    result = {"with_a": build()[0], "b_only": build(None)[0]}
    assert TAXONOMY == original
    return result


@pytest.mark.parametrize("variant", ["with_a", "b_only"])
@pytest.mark.parametrize("text,expected", [
    ("하루 한 번 먹는 제품이면 좋겠어요.", ("daily_frequency", 1, "PREFER")),
    ("하루 두 번 먹는 제품이면 좋겠어요.", ("daily_frequency", 2, "PREFER")),
    ("프로바이오틱스와 아연이면 좋겠어요.", ("functional_ingredients", 4, "PREFER")),
])
def test_b_only_expressions_remain_available_even_when_a_is_loaded(parsers, variant, text, expected):
    assert interpreted(parsers[variant], text) == ("PARSED", {expected})


@pytest.mark.parametrize("variant", ["with_a", "b_only"])
@pytest.mark.parametrize(("category", "text", "expected"), [
    (
        "health-functional-food:probiotics",
        "프로바이오틱스 제품",
        ("functional_ingredients", 1, "PREFER"),
    ),
    (
        "health-functional-food:red_ginseng",
        "홍삼제품",
        ("functional_ingredients", 1, "PREFER"),
    ),
    (
        "health-functional-food:vitamin_mineral",
        "비타민D",
        ("functional_ingredients", 2, "PREFER"),
    ),
])
def test_deprecated_taxonomy_surfaces_resolve_to_canonical_values(
    parsers,
    variant,
    category,
    text,
    expected,
):
    assert interpreted(parsers[variant], text, category) == (
        "PARSED",
        {expected},
    )


@pytest.mark.parametrize("text,expected", [
    ("가루면 좋겠어요.", {("product_form", 1, "PREFER")}),
    ("알약 제품이면 좋겠어요.", {("product_form", 2, "PREFER")}),
    ("분말이면서 하루 한 번 먹는 제품이면 좋겠어요.", {
        ("product_form", 1, "PREFER"), ("daily_frequency", 1, "PREFER"),
    }),
])
def test_a_aliases_and_b_composite_conditions(parsers, text, expected):
    assert interpreted(parsers["with_a"], text) == ("PARSED", expected)


@pytest.mark.parametrize("variant", ["with_a", "b_only"])
def test_constraint_types_and_alternative_groups_survive(parsers, variant):
    parser = parsers[variant]
    assert interpreted(parser, "분말은 제외해주세요.") == (
        "PARSED", {("product_form", 1, "EXCLUDE")},
    )
    assert interpreted(parser, "반드시 분말 제품으로 부탁해요.") == (
        "PARSED", {("product_form", 1, "MUST")},
    )
    result = parser.interpret(CATEGORY, "분말 또는 캡슐도 괜찮아요.", is_substitutable=True)
    assert len(result.preference_groups) == 1
    assert result.preference_groups[0].operator == "ANY_OF"


def test_unconfigured_a_falls_back_with_observable_reason():
    parser, summary = build(None)
    assert summary["aliasMode"] == "B_ONLY"
    assert summary["primaryAliasLoadStatus"] == "NOT_CONFIGURED"
    assert summary["primaryAliasSha256"] is None
    assert summary["compatibilityAliasSha256"]
    assert interpreted(parser, "정제") == ("PARSED", {("product_form", 3, "PREFER")})


def test_configured_missing_a_is_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        build(tmp_path / "missing.json")


def test_a_b_overlap_metric_has_non_suppressive_name():
    _, summary = build()
    assert summary["compatibilityOverlapWithA"] > 0
    assert "compatibilitySuppressedByA" not in summary


@pytest.mark.parametrize("change", ["remove_rule", "remove_category", "empty_export"])
def test_removing_a_binding_intentionally_keeps_b_fallback(tmp_path, change):
    payload = primary_payload()
    tablet = next(r for r in payload["aliases"] if r["canonical_value"] == "tablet")
    if change == "remove_rule":
        payload["aliases"].remove(tablet)
    elif change == "remove_category":
        del tablet["category_local_values"][CATEGORY]
    else:
        payload["aliases"] = []
    parser, summary = build(write_primary(tmp_path, payload))
    assert summary["aliasMode"] == "A_AND_B"
    assert interpreted(parser, "정제") == ("PARSED", {("product_form", 3, "PREFER")})


def test_a_priority_is_category_local_and_also_overrides_taxonomy_aliases(tmp_path):
    payload = primary_payload()
    # A reviewed this expression only in one category. B's normal mapping
    # still applies to other categories that A did not cover.
    payload["aliases"] = [{
        "facet_name": "product_form", "canonical_value": "capsule",
        "surfaces": ["정제"],
        "category_local_values": {CATEGORY: {"code": 2, "value": "캡슐"}},
    }]
    taxonomy = deepcopy(TAXONOMY)
    cat = next(c for c in taxonomy["categories"] if c["category_id"] == CATEGORY)
    form = next(f for f in cat["facets"] if f["name"] == "product_form")
    next(v for v in form["values"] if v["value"] == "정")["aliases"] = ["정제"]
    parser, _ = build(write_primary(tmp_path, payload), taxonomy)
    assert interpreted(parser, "정제") == ("PARSED", {("product_form", 2, "PREFER")})
    assert interpreted(parser, "정제", "health-functional-food:protein") == (
        "PARSED", {("product_form", 2, "PREFER")},
    )  # protein category code 2 is 정, not 캡슐.
    assert next(v for v in form["values"] if v["value"] == "정")["aliases"] == ["정제"]


@pytest.mark.parametrize("change", [
    "wrong_version", "missing_version", "unknown_category", "unknown_facet",
    "unknown_code", "wrong_value", "boolean_code", "zero_code", "missing_local_map",
    "bad_surfaces", "rejected", "conflicting_targets", "literal_conflict",
])
def test_invalid_a_is_rejected_before_parser_construction(tmp_path, monkeypatch, change):
    payload = primary_payload()
    row = payload["aliases"][0]
    target = row["category_local_values"][CATEGORY]
    if change == "wrong_version":
        payload["taxonomy_version"] = "v2.3"
    elif change == "missing_version":
        del payload["taxonomy_version"]
    elif change == "unknown_category":
        row["category_local_values"]["unknown"] = target
    elif change == "unknown_facet":
        row["facet_name"] = "unknown"
    elif change == "unknown_code":
        target["code"] = 999
    elif change == "wrong_value":
        target["value"] = "캡슐"
    elif change == "boolean_code":
        target["code"] = True
    elif change == "zero_code":
        target["code"] = 0
    elif change == "missing_local_map":
        del row["category_local_values"]
    elif change == "bad_surfaces":
        row["surfaces"] = "가루"
    elif change == "rejected":
        row["review_status"] = "REJECTED"
    elif change == "conflicting_targets":
        conflict = deepcopy(row)
        conflict["surfaces"] = ["가루"]
        conflict["category_local_values"] = {CATEGORY: {"code": 2, "value": "캡슐"}}
        payload["aliases"].append(conflict)
    else:
        row["category_local_values"][CATEGORY] = {"code": 2, "value": "캡슐"}
    monkeypatch.setattr(DemandConstraintParser, "from_taxonomy", lambda *a, **kw: pytest.fail("invalid aliases reached parser"))
    with pytest.raises(ValueError, match="alias|primary"):
        build(write_primary(tmp_path, payload))


def test_unreadable_or_malformed_a_is_not_treated_as_absent(tmp_path, monkeypatch):
    malformed = tmp_path / "invalid.json"
    malformed.write_text("{broken")
    with pytest.raises(ValueError):
        build(malformed)
    with pytest.raises(IsADirectoryError):
        build(tmp_path)
    original = Path.read_bytes

    def read_bytes(path):
        if path == malformed:
            raise PermissionError("A registry unreadable")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    with pytest.raises(PermissionError):
        build(malformed)


def test_approved_export_coverage_requires_review_when_changed():
    actual = {
        (category, surface)
        for row in primary_payload()["aliases"]
        for category in row["category_local_values"] for surface in row["surfaces"]
    }
    expected = {(r["category_id"], r["surface"]) for r in APPROVED_CASES}
    assert actual == expected, "Review A alias additions/removals and update the fixed cases explicitly"


@pytest.mark.parametrize("case", APPROVED_CASES, ids=lambda c: c["category_id"] + "/" + c["surface"])
def test_each_reviewed_a_expression_keeps_its_expected_meaning(parsers, case):
    assert interpreted(parsers["with_a"], case["surface"], case["category_id"]) == (
        "PARSED", {(case["facet_name"], int(case["value_code"]), "PREFER")},
    )


@pytest.mark.parametrize("variant", ["with_a", "b_only"])
def test_frozen_v046_language_quality_survives_both_modes(parsers, variant):
    path = ROOT / "tests/demand_constraints/fixtures/v042_approved_eval.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    failures, unsafe = [], []
    for row in rows:
        actual = interpreted(parsers[variant], row["extra_requirement"], row["category_id"])
        expected = {(c["facet_name"], int(c["value_code"]), c["constraint_type"])
                    for c in json.loads(row["expected_constraints_json"])}
        correct = actual[0] == row["expected_status"] and (
            actual[1] == expected if row["expected_status"] == "PARSED" else True
        )
        if not correct:
            failures.append(row["sample_id"])
            if actual[0] == "PARSED":
                unsafe.append(row["sample_id"])
    assert len(rows) == 129
    assert failures == ["openai-NP-046-1", "openai-NP-048-1"]
    assert not unsafe

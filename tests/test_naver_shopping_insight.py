import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "facet" / "collect_naver_shopping_insight.py"
SPEC = importlib.util.spec_from_file_location("naver_shopping_insight", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_build_requests_requires_explicit_category_mapping():
    candidates = pd.DataFrame([
        {"category_key": "health-functional-food:probiotics", "facet_name": "제형", "facet_value": "캡슐"},
    ])

    requests = MODULE.build_requests(
        candidates,
        {"health-functional-food:probiotics": "50000000"},
        "2026-01-01",
        "2026-01-31",
        "month",
    )

    assert len(requests) == 1
    assert requests[0]["body"]["category"] == "50000000"
    assert requests[0]["body"]["keyword"][0]["param"] == ["캡슐"]


def test_build_requests_limits_api_keyword_pairs_to_five():
    candidates = pd.DataFrame([
        {"category_key": "cat", "facet_name": "성분", "facet_value": f"값{i}"}
        for i in range(6)
    ])

    requests = MODULE.build_requests(candidates, {"cat": "123"}, "2026-01-01", "2026-01-31", "month")

    assert len(requests) == 2
    assert [len(item["body"]["keyword"]) for item in requests] == [5, 1]


def test_flatten_response_marks_consumer_trend_evidence():
    rows = MODULE.flatten_response(
        {"category_key": "cat", "category_id": "123"},
        {"results": [{"title": "성분:값", "keyword": ["값"], "data": [{"period": "2026-01", "ratio": 42}]}]},
    )

    assert rows[0]["source_type"] == "CONSUMER_SEARCH_TREND"
    assert rows[0]["ratio"] == 42

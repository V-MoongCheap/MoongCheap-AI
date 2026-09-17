import pandas as pd

from scripts.demand.build_model2_evaluation_sets import build, split_frame


def _frame(rows=80):
    return pd.DataFrame([
        {
            "demand_id": f"d{i}", "catalog_id": f"c{i}", "category_id": f"cat{i % 2}",
            "scenario_type": ["SINGLE_FACET", "NO_EXTRA_REQUIREMENT"][i % 2],
            "expected_facet_profile": "{}", "profile_id": f"p{i}", "source_review_id": "private",
        }
        for i in range(rows)
    ])


def test_split_is_disjoint_and_deterministic():
    frame = _frame(800)
    first = split_frame(frame, 42)
    second = split_frame(frame, 42)
    assert {name: len(value) for name, value in first.items()} == {"dev": 300, "holdout": 150, "challenge": 150}
    assert all(first[name]["demand_id"].tolist() == second[name]["demand_id"].tolist() for name in first)
    ids = [set(value["demand_id"]) for value in first.values()]
    assert not ids[0] & ids[1] and not ids[0] & ids[2] and not ids[1] & ids[2]


def test_build_separates_runtime_input_from_gold(tmp_path):
    source = tmp_path / "demands.csv"
    _frame(800).to_csv(source, index=False, encoding="utf-8-sig")
    build(source, tmp_path / "out")
    runtime = pd.read_csv(tmp_path / "out/model2_dev_input.csv", dtype=str)
    gold = pd.read_csv(tmp_path / "out/model2_dev_gold_candidate.csv", dtype=str)
    assert "expected_facet_profile" not in runtime
    assert "expected_facet_profile" in gold
    assert len(pd.read_csv(tmp_path / "out/model2_human_review_queue.csv")) == 150

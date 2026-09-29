import pandas as pd

from scripts.evaluation.evaluate_model2_rule_baseline import _matches


def test_matches_ignores_expected_all_but_checks_selected_codes():
    assert _matches("1-0-2", '{"form":{"code":1},"sugar":{"code":0},"taste":{"code":2}}')
    assert not _matches("1-0-1", '{"form":{"code":1},"sugar":{"code":0},"taste":{"code":2}}')


def test_invalid_labels_do_not_match():
    assert not _matches("", pd.NA)
    assert not _matches("1-2", '{"form":{"code":1},"sugar":{"code":2},"taste":{"code":3}}')

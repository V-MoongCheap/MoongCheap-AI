from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.evaluation.evaluate_part_a_gold_v2_2 import (
    _constraints,
    _groups,
    _parser_mode,
    evaluate,
)


ROOT = Path(__file__).resolve().parents[2]


def test_finalized_gold_has_expected_partition_sizes() -> None:
    gold = ROOT / "data/evaluation/part_a_v2_2_gold"
    sizes = {
        partition: len(
            pd.read_csv(
                gold / f"part_a_v2_2_{partition.lower()}_gold.csv",
                dtype=str,
                keep_default_na=False,
                encoding="utf-8-sig",
            )
        )
        for partition in ("DEV", "HOLDOUT", "CHALLENGE")
    }
    assert sizes == {"DEV": 100, "HOLDOUT": 50, "CHALLENGE": 50}


def test_semantic_normalizers_ignore_runtime_proof_fields() -> None:
    constraints = _constraints(
        [
            {
                "facet_name": "product_form",
                "value_code": 1,
                "value": "캡슐",
                "constraint_type": "MUST",
                "evidence_clause": "캡슐 포함",
            }
        ]
    )
    assert constraints == [
        {
            "facet_name": "product_form",
            "value_code": 1,
            "value": "캡슐",
            "constraint_type": "MUST",
        }
    ]


def test_evaluator_writes_partitioned_summary(tmp_path: Path) -> None:
    summary = evaluate(
        ROOT / "data/evaluation/part_a_v2_2_gold",
        tmp_path,
        partition="DEV",
    )
    assert summary["total_rows"] == 100
    assert (tmp_path / "part_a_v2_2_gold_evaluation_results.csv").exists()
    assert (tmp_path / "part_a_v2_2_gold_evaluation_summary.json").exists()
    assert (tmp_path / "part_a_v2_2_gold_evaluation.md").exists()


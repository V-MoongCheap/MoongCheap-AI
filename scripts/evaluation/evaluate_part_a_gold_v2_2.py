"""Evaluate the Part A V2.2 demand parser against the finalized Gold splits."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from moongcheap_ai.demand_constraints.service import DemandConstraintParser  # noqa: E402


PARTITIONS = ("DEV", "HOLDOUT", "CHALLENGE")
CONSTRAINT_FIELDS = ("facet_name", "value_code", "value", "constraint_type")


def _json_value(raw: str, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _bool_value(raw: str) -> bool:
    normalized = str(raw).strip().casefold()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n", ""}:
        return False
    raise ValueError(f"invalid is_substitutable value: {raw!r}")


def _constraint(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item.get(key) for key in CONSTRAINT_FIELDS}


def _constraints(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [_constraint(item) for item in value if isinstance(item, dict)]


def _groups(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[dict[str, Any]] = []
    for group in value:
        if not isinstance(group, dict):
            continue
        result.append(
            {
                "operator": group.get("operator"),
                "aggregation": group.get("aggregation"),
                "members": _constraints(group.get("members", [])),
            }
        )
    return result


def _expected(row: pd.Series, field: str, corrected_field: str, default: Any) -> Any:
    corrected = str(row.get(corrected_field, ""))
    proposed = str(row.get(field, ""))
    return _json_value(corrected or proposed, default)


def _expected_text(row: pd.Series) -> str:
    corrected = str(row.get("corrected_expected_passthrough_text", ""))
    return corrected or str(row.get("expected_passthrough_text", ""))


def _expected_scalar(row: pd.Series, corrected_field: str, proposed_field: str) -> str:
    corrected = str(row.get(corrected_field, ""))
    return corrected or str(row.get(proposed_field, ""))


def _parser_mode(result: Any) -> str:
    if result.preference_groups:
        return "ANY_OF"
    types = {item.constraint_type for item in result.constraints}
    if not types:
        return "NONE"
    if len(types) > 1:
        return "MIXED"
    return next(iter(types))


def _actual_passthrough(result: Any) -> str:
    return " | ".join(str(item) for item in result.semantic_preferences)


def _evaluate_row(parser: DemandConstraintParser, row: pd.Series) -> dict[str, Any]:
    expected_constraints = _expected(
        row,
        "proposed_expected_constraints",
        "corrected_expected_constraints",
        [],
    )
    expected_groups = _expected(
        row,
        "proposed_expected_preference_groups",
        "corrected_expected_preference_groups",
        [],
    )
    expected = {
        "status": _expected_scalar(row, "corrected_expected_status", "proposed_expected_status"),
        "parser_mode": _expected_scalar(row, "corrected_expected_mode", "proposed_expected_mode"),
        "effective_requirement_mode": str(row.get("expected_effective_requirement_mode", "")),
        "constraints": _constraints(expected_constraints),
        "preference_groups": _groups(expected_groups),
        "passthrough_text": _expected_text(row),
    }
    result = parser.interpret(
        str(row["category_id"]),
        str(row["extra_requirement"]),
        is_substitutable=_bool_value(row["is_substitutable"]),
    )
    actual = {
        "status": result.status,
        "parser_mode": _parser_mode(result),
        "effective_requirement_mode": result.effective_requirement_mode,
        "constraints": [_constraint(asdict(item)) for item in result.constraints],
        "preference_groups": _groups([asdict(item) for item in result.preference_groups]),
        "passthrough_text": _actual_passthrough(result),
    }
    checks = {
        "status_match": expected["status"] == actual["status"],
        "parser_mode_match": expected["parser_mode"] == actual["parser_mode"],
        "effective_mode_match": expected["effective_requirement_mode"]
        == actual["effective_requirement_mode"],
        "constraints_match": expected["constraints"] == actual["constraints"],
        "preference_groups_match": expected["preference_groups"] == actual["preference_groups"],
        "passthrough_match": expected["passthrough_text"] == actual["passthrough_text"],
    }
    return {
        "case_id": row["case_id"],
        "partition": row["evaluation_partition_candidate"],
        "category_id": row["category_id"],
        "extra_requirement": row["extra_requirement"],
        "expected_json": json.dumps(expected, ensure_ascii=False, separators=(",", ":")),
        "actual_json": json.dumps(actual, ensure_ascii=False, separators=(",", ":")),
        **checks,
        "row_pass": all(checks.values()),
    }


def _load_parser() -> DemandConstraintParser:
    taxonomy = json.loads((ROOT / "config/facet_taxonomy_v2_2.json").read_text(encoding="utf-8"))
    return DemandConstraintParser.from_taxonomy(
        taxonomy,
        rules_path=ROOT / "config/demand_constraint_rules.json",
        aliases_path=ROOT / "config/model1_aliases_reviewed_v2.json",
    )


def _partition_frame(gold_dir: Path, partition: str) -> pd.DataFrame:
    path = gold_dir / f"part_a_v2_2_{partition.lower()}_gold.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def evaluate(gold_dir: Path, output_dir: Path, partition: str = "ALL") -> dict[str, Any]:
    parser = _load_parser()
    selected = PARTITIONS if partition == "ALL" else (partition,)
    frames = [_partition_frame(gold_dir, item) for item in selected]
    results: list[dict[str, Any]] = []
    for frame in frames:
        for _, row in frame.iterrows():
            try:
                results.append(_evaluate_row(parser, row))
            except Exception as exc:  # Keep one malformed case from hiding the rest.
                results.append(
                    {
                        "case_id": row.get("case_id", ""),
                        "partition": row.get("evaluation_partition_candidate", ""),
                        "category_id": row.get("category_id", ""),
                        "extra_requirement": row.get("extra_requirement", ""),
                        "expected_json": "",
                        "actual_json": "",
                        "status_match": False,
                        "parser_mode_match": False,
                        "effective_mode_match": False,
                        "constraints_match": False,
                        "preference_groups_match": False,
                        "passthrough_match": False,
                        "row_pass": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    result_frame = pd.DataFrame(results)
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "part_a_v2_2_gold_evaluation_results.csv"
    result_frame.to_csv(result_path, index=False, encoding="utf-8-sig")

    metric_columns = [
        "status_match",
        "parser_mode_match",
        "effective_mode_match",
        "constraints_match",
        "preference_groups_match",
        "passthrough_match",
        "row_pass",
    ]
    summary: dict[str, Any] = {"total_rows": len(result_frame), "result_path": str(result_path)}
    for name, group in result_frame.groupby("partition", sort=False):
        summary[name] = {
            "rows": len(group),
            **{
                metric: {
                    "count": int(group[metric].sum()),
                    "rate": round(float(group[metric].mean()), 4) if len(group) else 0.0,
                }
                for metric in metric_columns
            },
        }
    summary["overall"] = {
        metric: {
            "count": int(result_frame[metric].sum()),
            "rate": round(float(result_frame[metric].mean()), 4) if len(result_frame) else 0.0,
        }
        for metric in metric_columns
    }
    (output_dir / "part_a_v2_2_gold_evaluation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report_lines = [
        "# Part A V2.2 Gold 평가 결과",
        "",
        "이 평가는 finalized Gold의 기대값과 현재 수요 조건 파서의 결과를 비교한다.",
        "각 행은 status, parser-level mode, effective mode, constraints, preference groups, passthrough를 독립적으로 비교한다.",
        "",
        f"- 전체 행: {len(result_frame)}",
        f"- 전체 row pass: {int(result_frame['row_pass'].sum())}/{len(result_frame)}",
        "",
        "## 파티션별 결과",
        "",
        "| Partition | Rows | Status | Parser Mode | Effective Mode | Constraints | Groups | Passthrough | Row Pass |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in selected:
        data = summary.get(name, {"rows": 0})
        cells = [name, str(data.get("rows", 0))]
        for metric in metric_columns:
            if metric == "row_pass":
                continue
            cells.append(f"{data.get(metric, {}).get('count', 0)}/{data.get('rows', 0)}")
        cells.append(f"{data.get('row_pass', {}).get('count', 0)}/{data.get('rows', 0)}")
        report_lines.append("| " + " | ".join(cells) + " |")
    failures = result_frame.loc[~result_frame["row_pass"]]
    report_lines.extend(["", "## 실패 사례", ""])
    if failures.empty:
        report_lines.append("없음")
    else:
        report_lines.append("| Case | Partition | Mismatch | Input |")
        report_lines.append("|---|---|---|---|")
        for _, row in failures.iterrows():
            mismatch = ", ".join(
                metric
                for metric in metric_columns[:-1]
                if not bool(row[metric])
            )
            text = str(row["extra_requirement"]).replace("|", "\\|").replace("\n", " ")
            report_lines.append(f"| {row['case_id']} | {row['partition']} | {mismatch} | {text} |")
    report_lines.extend(
        [
            "",
            "## 산출물",
            "",
            f"- 상세 결과: `{result_path.as_posix()}`",
            f"- 요약 JSON: `{(output_dir / 'part_a_v2_2_gold_evaluation_summary.json').as_posix()}`",
            "",
            "참고: Gold의 expected 값은 정답 기준이며, 실패 행은 파서 또는 Gold 기대값의 추가 검토 대상이다. 자동으로 수정하지 않는다.",
        ]
    )
    report_path = output_dir / "part_a_v2_2_gold_evaluation.md"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    summary["report_path"] = str(report_path)
    return summary


def main() -> None:
    cli = argparse.ArgumentParser()
    cli.add_argument("--gold-dir", type=Path, default=ROOT / "data/evaluation/part_a_v2_2_gold")
    cli.add_argument("--output-dir", type=Path, default=ROOT / "reports/part_a_v2_2_gold")
    cli.add_argument("--partition", choices=("ALL", *PARTITIONS), default="ALL")
    args = cli.parse_args()
    print(json.dumps(evaluate(args.gold_dir, args.output_dir, args.partition), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

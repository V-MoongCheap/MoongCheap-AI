"""Evaluate the current Part A/Model 2 parser against the versioned Gold split.

The supported and out-of-taxonomy partitions are intentionally scored differently:
supported rows are constraint-accuracy cases, while out-of-taxonomy rows are
diagnostic/abstention cases and must not be mixed into the accuracy denominator.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from moongcheap_ai.data_foundation.labeling import load_taxonomy
from moongcheap_ai.demand_constraints import DemandConstraintParser, parse_demand_constraints
from moongcheap_ai.data_foundation.part_a_input_policy import PartAConstraintInputPolicy


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TAXONOMY = ROOT / "data/processed/model1_kanana_all_extended_16_fixed/human_reviewed_taxonomy_mapping_local/facet_taxonomy_v0_human_reviewed.json"
DEFAULT_GOLD_DIR = ROOT / "data/processed/model2_gold_v1"
DEFAULT_RULES = ROOT / "config/demand_constraint_rules.json"
DEFAULT_ALIASES = ROOT / "config/demand_constraint_aliases.json"


def _json(value: object) -> list[dict[str, Any]]:
    if not value or not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _constraint_atoms(value: object) -> tuple[tuple[str, str, str, str], ...]:
    atoms = []
    for item in _json(value):
        if not isinstance(item, dict):
            continue
        atoms.append(
            (
                str(item.get("facet_name", item.get("facetKey", ""))),
                str(item.get("value_code", item.get("valueCode", ""))),
                str(item.get("value", item.get("canonicalValue", ""))),
                str(item.get("constraint_type", item.get("constraintType", ""))),
            )
        )
    return tuple(sorted(atoms))


def _semantic_atoms(value: object) -> tuple[tuple[str, str, str], ...]:
    """Compare facet meaning without hiding a separate code-contract error."""
    return tuple(sorted((facet, value, kind) for facet, _code, value, kind in _constraint_atoms(value)))


def _build_parser(taxonomy_path: Path, rules_path: Path, aliases_path: Path) -> DemandConstraintParser:
    taxonomy = load_taxonomy(taxonomy_path)
    return DemandConstraintParser.from_taxonomy(
        taxonomy.taxonomy,
        rules_path=rules_path,
        aliases_path=aliases_path,
        policy_cls=PartAConstraintInputPolicy,
    )


def _evaluate_partition(
    frame: pd.DataFrame,
    parser: DemandConstraintParser,
    *,
    supported: bool,
    output_path: Path,
) -> dict[str, Any]:
    result = parse_demand_constraints(frame, parser)
    result.to_csv(output_path, index=False, encoding="utf-8-sig")

    status_counts = Counter(result["constraint_status"].astype(str))
    summary: dict[str, Any] = {
        "rows": len(result),
        "status_counts": dict(sorted(status_counts.items())),
        "output": str(output_path),
    }
    if supported:
        merged = frame[["demand_id", "corrected_expected_constraints"]].merge(
            result[["demand_id", "constraints", "constraint_status"]],
            on="demand_id",
            how="left",
        )
        merged["exact_match"] = merged.apply(
            lambda row: _constraint_atoms(row["corrected_expected_constraints"])
            == _constraint_atoms(row["constraints"]),
            axis=1,
        )
        merged["semantic_match"] = merged.apply(
            lambda row: _semantic_atoms(row["corrected_expected_constraints"])
            == _semantic_atoms(row["constraints"]),
            axis=1,
        )
        summary.update(
            {
                "evaluation": "supported_constraint_accuracy",
                "exact_matches": int(merged["exact_match"].sum()),
                "exact_match_rate": round(float(merged["exact_match"].mean()), 6),
                "semantic_matches": int(merged["semantic_match"].sum()),
                "semantic_match_rate": round(float(merged["semantic_match"].mean()), 6),
                "mismatch_ids": merged.loc[~merged["exact_match"], "demand_id"].tolist(),
                "code_only_mismatch_ids": merged.loc[
                    merged["semantic_match"] & ~merged["exact_match"], "demand_id"
                ].tolist(),
            }
        )
    else:
        summary["evaluation"] = "out_of_taxonomy_diagnostic_only"
        summary["accuracy_denominator_excluded"] = True
        summary["review_or_abstention_rows"] = int(
            result["constraint_status"].isin({"REVIEW", "PASSTHROUGH"}).sum()
        )
    return summary


def evaluate(
    *,
    gold_dir: Path = DEFAULT_GOLD_DIR,
    taxonomy_path: Path = DEFAULT_TAXONOMY,
    rules_path: Path = DEFAULT_RULES,
    aliases_path: Path = DEFAULT_ALIASES,
    output_dir: Path,
) -> dict[str, Any]:
    supported_path = gold_dir / "model2_gold_supported_v1.csv"
    challenge_path = gold_dir / "model2_gold_out_of_taxonomy_v1.csv"
    for path in (supported_path, challenge_path, taxonomy_path, rules_path, aliases_path):
        if not path.exists():
            raise FileNotFoundError(path)

    output_dir.mkdir(parents=True, exist_ok=True)
    parser = _build_parser(taxonomy_path, rules_path, aliases_path)
    supported = pd.read_csv(supported_path, dtype=str).fillna("")
    challenge = pd.read_csv(challenge_path, dtype=str).fillna("")
    summary = {
        "taxonomy": str(taxonomy_path),
        "taxonomy_version": "model1-human-reviewed-v1",
        "gold_split": {"supported_rows": len(supported), "out_of_taxonomy_rows": len(challenge)},
        "supported": _evaluate_partition(
            supported,
            parser,
            supported=True,
            output_path=output_dir / "model2_gold_supported_rule_first.csv",
        ),
        "out_of_taxonomy": _evaluate_partition(
            challenge,
            parser,
            supported=False,
            output_path=output_dir / "model2_gold_out_of_taxonomy_rule_first.csv",
        ),
        "stale_artifact_warning": (
            "Do not use data/processed/model2_gold_v1/human_taxonomy_v1 metrics as the "
            "current score; those artifacts use the superseded 39/46 partition."
        ),
    }
    (output_dir / "model2_gold_evaluation_v2.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--gold-dir", type=Path, default=DEFAULT_GOLD_DIR)
    cli.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    cli.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    cli.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES)
    cli.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_GOLD_DIR / "current_evaluation_v2",
    )
    args = cli.parse_args()
    print(
        json.dumps(
            evaluate(
                gold_dir=args.gold_dir,
                taxonomy_path=args.taxonomy,
                rules_path=args.rules,
                aliases_path=args.aliases,
                output_dir=args.output_dir,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

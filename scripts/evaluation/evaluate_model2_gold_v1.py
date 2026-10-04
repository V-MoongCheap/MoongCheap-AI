"""Evaluate the current Part A/Model 2 parser against the versioned Gold split.

The supported and out-of-taxonomy partitions are intentionally scored differently:
supported rows are constraint-accuracy cases, while out-of-taxonomy rows are
diagnostic/abstention cases and must not be mixed into the accuracy denominator.
"""

from __future__ import annotations

import argparse
import json
import hashlib
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from moongcheap_ai.data_foundation.labeling import load_taxonomy
from moongcheap_ai.demand_constraints import DemandConstraintParser, parse_demand_constraints
from moongcheap_ai.data_foundation.part_a_runtime import build_a_parser


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TAXONOMY = ROOT / "data/processed/model1_kanana_all_extended_16_fixed/human_reviewed_taxonomy_mapping_local/facet_taxonomy_v0_human_reviewed.json"
DEFAULT_GOLD_DIR = ROOT / "data/processed/model2_gold_v1"
DEFAULT_RULES = ROOT / "config/demand_constraint_rules.json"
DEFAULT_ALIASES = ROOT / "config/demand_constraint_aliases.json"


def _json(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("constraints must be an explicit JSON array, including []")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("constraints contain invalid JSON") from exc
    if not isinstance(parsed, list) or any(not isinstance(item, dict) for item in parsed):
        raise ValueError("constraints must be an array of objects")
    return parsed


def _constraint_atoms(value: object) -> tuple[tuple[str, str, str, str, str], ...]:
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
                str(item.get("facet_code", item.get("facetCode", ""))),
            )
        )
    return tuple(sorted(atoms))


def _semantic_atoms(value: object) -> tuple[tuple[str, str, str], ...]:
    """Compare facet meaning without hiding a separate code-contract error."""
    return tuple(sorted((facet, value, kind) for facet, _code, value, kind, _facet_code in _constraint_atoms(value)))


def _build_parser(taxonomy_path: Path, rules_path: Path, aliases_path: Path) -> DemandConstraintParser:
    taxonomy = load_taxonomy(taxonomy_path)
    return build_a_parser(
        taxonomy.taxonomy,
        rules_path=rules_path,
        alias_registry_path=aliases_path,
    )


def _evaluate_partition(
    frame: pd.DataFrame,
    parser: DemandConstraintParser,
    *,
    supported: bool,
    output_path: Path,
    taxonomy_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = parse_demand_constraints(frame, parser)
    # The parser's semantic constraints omit facetCode. Materialize the actual
    # contract code from the selected release, never from the expected Gold.
    if taxonomy_payload is not None:
        facets = {(str(category["category_id"]), str(facet["name"])):
                  str(facet.get("facet_id", facet.get("order", "")))
                  for category in taxonomy_payload.get("categories", [])
                  for facet in category.get("facets", [])}
        for index, row in result.iterrows():
            items = _json(row.get("constraints", ""))
            for item in items:
                item["facet_code"] = facets.get((str(row.get("category_id", "")),
                                                 str(item.get("facet_name", ""))), "")
            result.at[index, "constraints"] = json.dumps(items, ensure_ascii=False)
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
        "evaluation_scope": "A_TYPED_PARSER_COMPONENT_NOT_FINAL_LABEL_OR_LIVE_LLM",
        "compared_fields": ["facet_name", "facet_code", "value_code", "value", "constraint_type"],
        "taxonomy": str(taxonomy_path),
        "taxonomy_sha256": hashlib.sha256(taxonomy_path.read_bytes()).hexdigest(),
        "taxonomy_version": load_taxonomy(taxonomy_path).taxonomy.get("version", ""),
        "gold_split": {"supported_rows": len(supported), "out_of_taxonomy_rows": len(challenge)},
        "supported": _evaluate_partition(
            supported,
            parser,
            supported=True,
            output_path=output_dir / "model2_gold_supported_rule_first.csv",
            taxonomy_payload=load_taxonomy(taxonomy_path).taxonomy,
        ),
        "out_of_taxonomy": _evaluate_partition(
            challenge,
            parser,
            supported=False,
            output_path=output_dir / "model2_gold_out_of_taxonomy_rule_first.csv",
            taxonomy_payload=load_taxonomy(taxonomy_path).taxonomy,
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


def align_gold_codes(gold_dir: Path, taxonomy_path: Path, output_dir: Path) -> Path:
    """Export a release-bound numeric-code copy without changing human semantics.

    Never overwrite a reviewed source. Resolve only exact canonical meanings;
    absent or ambiguous meanings fail instead of manufacturing a Gold answer.
    """
    if gold_dir.resolve() == output_dir.resolve():
        raise ValueError("aligned Gold must be a separate directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    names = ("model2_gold_supported_v1.csv", "model2_gold_out_of_taxonomy_v1.csv")
    if any((output_dir / name).exists() for name in names):
        raise ValueError("aligned Gold output already exists; use a new release directory")
    taxonomy = load_taxonomy(taxonomy_path).taxonomy
    facets = {(str(category["category_id"]), str(facet["name"])): facet
              for category in taxonomy.get("categories", [])
              for facet in category.get("facets", [])}
    frame = pd.read_csv(gold_dir / names[0], dtype=str, keep_default_na=False, encoding="utf-8-sig")
    changes = []
    for index, row in frame.iterrows():
        raw = row["corrected_expected_constraints"]
        try:
            items = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Gold constraints must be valid JSON") from exc
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError("Gold constraints must be an array of objects")
        for item in items:
            key = str(item.get("facetKey", item.get("facet_name", "")))
            facet = facets.get((str(row["category_id"]), key))
            value = str(item.get("canonicalValue", item.get("value", "")))
            values = [] if facet is None else [entry for entry in facet.get("values", [])
                if str(entry["value"]) == value and str(entry.get("status", "")).upper() != "DEPRECATED"]
            if len(values) != 1:
                raise ValueError(f"Gold meaning is absent/ambiguous in release: {row['demand_id']} / {key}")
            fields = {"facetCode" if "facetKey" in item else "facet_code": int(facet.get("facet_id", facet.get("order", 0))),
                      "valueCode" if "facetKey" in item else "value_code": int(values[0]["code"])}
            for field, code in fields.items():
                if str(item.get(field, "")) != str(code):
                    changes.append({"demand_id": row["demand_id"], "facet": key, "field": field,
                                    "before": item.get(field), "after": code})
                    item[field] = code
        frame.at[index, "corrected_expected_constraints"] = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    # Validate all inputs before exporting either partition.
    challenge = gold_dir / names[1]
    challenge_bytes = challenge.read_bytes()
    source_hashes = {name: hashlib.sha256((gold_dir / name).read_bytes()).hexdigest() for name in names}
    frame.to_csv(output_dir / names[0], index=False, encoding="utf-8-sig")
    shutil.copyfile(challenge, output_dir / names[1])
    assert (output_dir / names[1]).read_bytes() == challenge_bytes
    manifest = {"scope": "NUMERIC_RELEASE_REBIND_ONLY_NOT_NEW_HUMAN_APPROVAL_OR_MODEL_IMPROVEMENT",
                "taxonomy_version": taxonomy.get("version", ""),
                "taxonomy_sha256": hashlib.sha256(taxonomy_path.read_bytes()).hexdigest(),
                "source_sha256": source_hashes, "changes": changes}
    (output_dir / "gold_code_alignment_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_dir


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--gold-dir", type=Path, default=DEFAULT_GOLD_DIR)
    cli.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    cli.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    cli.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES)
    cli.add_argument("--align-gold-codes", action="store_true", help="Export a separate numeric-code-aligned evaluation copy")
    cli.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_GOLD_DIR / "current_evaluation_v2",
    )
    args = cli.parse_args()
    gold_dir = (align_gold_codes(args.gold_dir, args.taxonomy, args.output_dir / "aligned_gold")
                if args.align_gold_codes else args.gold_dir)
    print(
        json.dumps(
            evaluate(
                gold_dir=gold_dir,
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

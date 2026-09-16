"""Compare B/A/A+B aliases on checked-in cases and optional v0.46 archives.

Gold scores describe a historical development set, not real-user accuracy.
This offline reporting tool does not access models, the DB or Backend APIs.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from importlib.metadata import version
from pathlib import Path

from moongcheap_ai.demand_clustering.part_a_integration import build_part_b_parser, file_digest
from moongcheap_ai.demand_constraints import DemandConstraintParser


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"evaluation input must be nonempty: {path}")
    return rows


def category_code_contract(taxonomy):
    return {
        category["category_id"]: sorted(
            (int(facet["order"]), facet["name"], sorted(
                (int(value["code"]), value["value"]) for value in facet["values"]
            ))
            for facet in category["facets"]
        )
        for category in taxonomy["categories"]
    }


def atoms(items):
    return sorted({(c["facet_name"], int(c["value_code"]), c["constraint_type"]) for c in items})


def meaning(payload):
    """Compare decisions, including semantic fallback and equivalent codes."""
    return {
        "status": payload["status"], "mode": payload["effective_requirement_mode"],
        "constraints": atoms(payload["constraints"]),
        "preferenceGroups": sorted(
            (g["operator"], g["aggregation"], atoms(g["members"]))
            for g in payload["preference_groups"]
        ),
        "semanticPreferences": list(payload["semantic_preferences"]),
        # asdict() retains tuples; archived CSV JSON contains arrays.
        "taxonomyEquivalences": json.loads(json.dumps(payload["taxonomy_equivalences"])),
    }


def archived_meaning(row):
    return meaning({
        "status": row["constraint_status"],
        "effective_requirement_mode": row["effective_constraint_mode"],
        "constraints": json.loads(row["constraints"]),
        "preference_groups": json.loads(row["preference_groups"]),
        "semantic_preferences": json.loads(row["free_text_preferences"]),
        "taxonomy_equivalences": json.loads(row["taxonomy_equivalences"]),
    })


def condition_set(result):
    return set(result["constraints"]) | {
        item for _, _, members in result["preferenceGroups"] for item in members
    }


def interpret(parser, row):
    consent = row.get("is_substitutable", "true").strip().lower()
    if consent not in {"true", "false"}:
        raise ValueError("evaluation input requires true/false is_substitutable")
    return parser.interpret(
        row["category_id"], row["extra_requirement"], is_substitutable=consent == "true",
    ).to_dict()


def evaluate_gold(parser, rows, *, service):
    failures, statuses = [], Counter()
    parsed = parsed_correct = 0
    for row in rows:
        result = interpret(parser, row) if service else parser.parse(
            row["category_id"], row["extra_requirement"],
        ).to_dict()
        expected = atoms(json.loads(row["expected_constraints_json"]))
        correct = result["status"] == row["expected_status"]
        if row["expected_status"] == "PARSED" or result["status"] == "PARSED":
            correct = correct and atoms(result["constraints"]) == expected
        statuses[result["status"]] += 1
        parsed += result["status"] == "PARSED"
        parsed_correct += result["status"] == "PARSED" and correct
        if not correct:
            failures.append({"sampleId": row["sample_id"], "text": row["extra_requirement"],
                             "expectedStatus": row["expected_status"], "expectedConstraints": expected,
                             "actual": result})
    return {
        "rows": len(rows), "correct": len(rows) - len(failures),
        "parsed": parsed, "parsedCorrect": parsed_correct,
        "incorrectAutomaticInterpretations": parsed - parsed_correct,
        "statusCounts": dict(statuses), "failures": failures,
    }


def compare(parsers, rows, archived=None):
    summaries = {name: {
        "statusCounts": Counter(), "modeCounts": Counter(),
        "changedFromBefore": 0, "lostConditionRows": 0,
        **({"differentFromV046Archive": 0} if archived is not None else {}),
    } for name in parsers}
    changes = []
    for index, row in enumerate(rows):
        case = {name: meaning(interpret(parser, row)) for name, parser in parsers.items()}
        baseline = case["before"]
        original = archived_meaning(archived[row["demand_id"]]) if archived is not None else baseline
        for name, result in case.items():
            summary = summaries[name]
            summary["statusCounts"][result["status"]] += 1
            summary["modeCounts"][result["mode"]] += 1
            summary["changedFromBefore"] += result != baseline
            summary["lostConditionRows"] += bool(condition_set(baseline) - condition_set(result))
            if archived is not None:
                summary["differentFromV046Archive"] += result != original
        if any(result != baseline for result in case.values()) or baseline != original:
            changes.append({
                "caseId": row.get("demand_id", row.get("sample_id", row.get("case_id", str(index)))),
                "categoryId": row["category_id"], "text": row["extra_requirement"],
                **({"archived": original} if archived is not None else {}), **case,
            })
    return {"rows": len(rows), "variants": summaries, "changedCases": changes}


def load_service_archive(input_path, archive_path):
    rows, archive_rows = read_rows(input_path), read_rows(archive_path)
    archived = {row["demand_id"]: row for row in archive_rows}
    ids = [row["demand_id"] for row in rows]
    if len(set(ids)) != len(ids) or len(archived) != len(archive_rows) or set(ids) != set(archived):
        raise ValueError("service input/archive must have matching unique demand IDs")
    for row in rows:
        consent = row["is_substitutable"].strip().lower()
        if consent not in {"true", "false"}:
            raise ValueError("service input requires explicit true/false consent")
        old = archived[row["demand_id"]]
        if row["category_id"] != old["category_id"] or (
            consent == "true" and row["extra_requirement"] != old["extra_requirement"]
        ):
            raise ValueError("archived category/eligible requirement differs from input")
    return rows, archived


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--baseline-taxonomy", type=Path, default=Path("tests/demand_constraints/fixtures/v042_taxonomy.json"))
    cli.add_argument("--gold", type=Path, default=Path("tests/demand_constraints/fixtures/v042_approved_eval.csv"))
    cli.add_argument("--input", nargs="+", type=Path, default=[Path("tests/demand_clustering/fixtures/v22_alias_migration.csv")])
    cli.add_argument("--service-input", type=Path, help="Optional historical service CSV; requires --archived-service-output")
    cli.add_argument("--archived-service-output", type=Path)
    cli.add_argument("--taxonomy", type=Path, default=Path("config/facet_taxonomy_v2_2.json"))
    cli.add_argument("--rules", type=Path, default=Path("config/demand_constraint_rules.json"))
    cli.add_argument("--aliases", type=Path, default=Path("config/model1_aliases_reviewed_v2.json"))
    cli.add_argument("--compatibility-aliases", type=Path, default=Path("config/demand_constraint_aliases.json"))
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    if bool(args.service_input) != bool(args.archived_service_output):
        cli.error("--service-input and --archived-service-output must be supplied together")
    before_taxonomy = json.loads(args.baseline_taxonomy.read_text(encoding="utf-8"))
    taxonomy = json.loads(args.taxonomy.read_text(encoding="utf-8"))
    gold_rows = read_rows(args.gold)
    comparison_rows = gold_rows + [row for path in args.input for row in read_rows(path)]
    service_data = load_service_archive(args.service_input, args.archived_service_output) if args.service_input else None
    parsers = {
        "before": DemandConstraintParser.from_taxonomy(
            before_taxonomy, rules_path=args.rules, aliases_path=args.compatibility_aliases,
        ),
        "aOnly": build_part_b_parser(taxonomy, rules_path=args.rules, aliases_path=args.aliases)[0],
        "after": build_part_b_parser(
            taxonomy, rules_path=args.rules, aliases_path=args.aliases,
            compatibility_aliases_path=args.compatibility_aliases,
        )[0],
    }
    gold = {}
    for name, parser in parsers.items():
        gold[name] = {"languageOnly": evaluate_gold(parser, gold_rows, service=False),
                      "servicePolicy": evaluate_gold(parser, gold_rows, service=True)}
        print(json.dumps({"variant": name, "languageCorrect": gold[name]["languageOnly"]["correct"]}), flush=True)
    inputs = {name: {"path": str(path), "sha256": file_digest(path)}
              for name, path in vars(args).items() if isinstance(path, Path) and name != "output"}
    inputs["comparisonCases"] = [{"path": str(path), "sha256": file_digest(path)} for path in args.input]
    report = {
        "scope": "DEVELOPMENT_REGRESSION_NOT_REAL_USER_ACCURACY",
        "externalLlmCalls": 0, "kiwipiepyVersion": version("kiwipiepy"),
        "rulesVersion": json.loads(args.rules.read_text(encoding="utf-8"))["version"],
        "categoryCodeContractIdentical": category_code_contract(before_taxonomy) == category_code_contract(taxonomy),
        "inputs": inputs, "gold": gold, "comparison": compare(parsers, comparison_rows),
    }
    if service_data is not None:
        rows, archived = service_data
        report["service"] = compare(parsers, rows, archived)
        report["service"]["consentingNonemptyRows"] = sum(
            row["is_substitutable"].strip().lower() == "true" and bool(row["extra_requirement"].strip()) for row in rows
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["comparison"]["variants"], ensure_ascii=False, indent=2))
    if "service" in report:
        print(json.dumps(report["service"]["variants"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

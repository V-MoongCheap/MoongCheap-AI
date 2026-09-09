from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from moongcheap_ai.demand_clustering.evaluation.llm_function_relation_review import (
    adjudications_to_status_frame,
    build_adjudication_prompt,
    request_openai_adjudication,
    text_fingerprint,
)


DEFAULT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Adjudicate Claude/Gemini function-review conflicts"
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(
            "data/reports/function_relation_pilot_v1/llm_consensus_v1/"
            "review_status.csv"
        ),
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=Path(
            "data/reports/function_relation_pilot_v1/llm_consensus_v1/"
            "manifest.json"
        ),
    )
    parser.add_argument("--model", default="gpt-5.5-2026-04-23")
    parser.add_argument(
        "--rubric-version",
        choices=("v1", "v2", "v2.1", "v2.2", "v3"),
        default="v1",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "data/reports/function_relation_pilot_v1/llm_consensus_v1"
        ),
    )
    args = parser.parse_args()

    output_paths = {
        "status": args.output_dir / "adjudicated_review_status.csv",
        "summary": args.output_dir / "adjudication_summary.json",
        "raw": args.output_dir / "raw_openai_adjudication.json",
        "manifest": args.output_dir / "adjudication_manifest.json",
    }
    existing = [str(path) for path in output_paths.values() if path.exists()]
    if existing:
        raise RuntimeError(
            "refusing to overwrite existing adjudication outputs: "
            + ", ".join(existing)
        )

    load_dotenv(args.env_file, override=False)
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("missing required environment variable: OPENAI_API_KEY")
    status = pd.read_csv(args.input, dtype=str, keep_default_na=False)
    conflict_ids = status.loc[
        status["agreement_status"].eq("ADJUDICATION_REQUIRED"),
        "direction_id",
    ].astype(str).tolist()
    prompt = build_adjudication_prompt(
        status,
        rubric_version=args.rubric_version,
    )
    raw_text, metadata = request_openai_adjudication(
        prompt,
        api_key=api_key,
        model=args.model,
        direction_ids=conflict_ids,
        rubric_version=args.rubric_version,
    )
    adjudicated = adjudications_to_status_frame(
        status,
        raw_text,
        adjudicator_id=f"openai:{metadata['model']}",
        rubric_version=args.rubric_version,
    )

    unfinished = adjudicated["final_coverage_label"].eq("")
    if unfinished.any():
        raise RuntimeError(
            "adjudication did not produce a final label for: "
            + ", ".join(adjudicated.loc[unfinished, "direction_id"])
        )
    status_counts = Counter(adjudicated["agreement_status"])
    label_counts = Counter(adjudicated["final_coverage_label"])
    reviewer_label_agreement = int(
        status["reviewer_a_label"].eq(status["reviewer_b_label"]).sum()
    )
    reviewer_label_and_reason_agreement = int((
        status["reviewer_a_label"].eq(status["reviewer_b_label"])
        & status["reviewer_a_reason_code"].eq(status["reviewer_b_reason_code"])
    ).sum())
    summary = {
        "schemaVersion": "mfds-function-relation-llm-adjudication.v1",
        "rubricVersion": args.rubric_version,
        "totalQuestions": len(adjudicated),
        "directLabelAndReasonAgreements": reviewer_label_and_reason_agreement,
        "acceptedLabelAgreements": int(status_counts["AGREEMENT"]),
        "adjudicatedQuestions": int(status_counts["ADJUDICATED"]),
        "reviewerLabelAgreementCount": reviewer_label_agreement,
        "reviewerLabelAgreementRate": round(
            reviewer_label_agreement / len(status), 6
        ),
        "reviewerLabelAndReasonAgreementRate": round(
            reviewer_label_and_reason_agreement / len(status), 6
        ),
        "finalLabelCounts": dict(sorted(label_counts.items())),
        "finalComplete": True,
        "goldStatus": (
            "LLM_CONSENSUS_CANDIDATE_ONLY: not human or regulatory-domain gold."
        ),
    }
    source_manifest_text = args.source_manifest.read_text(encoding="utf-8")
    manifest = {
        "schemaVersion": "mfds-function-relation-llm-adjudication-run.v1",
        "rubricVersion": args.rubric_version,
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "adjudicator": metadata,
        "conflictCount": len(conflict_ids),
        "conflictDirectionIds": conflict_ids,
        "sourceManifestFingerprintSha256": text_fingerprint(
            source_manifest_text
        ),
        "promptFingerprintSha256": text_fingerprint(prompt),
        "responseFingerprintSha256": text_fingerprint(raw_text),
        "structuredOutput": "Responses API strict JSON schema",
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    adjudicated.to_csv(output_paths["status"], index=False, encoding="utf-8-sig")
    output_paths["summary"].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    output_paths["raw"].write_text(
        json.dumps(
            {"metadata": metadata, "responseText": raw_text},
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    output_paths["manifest"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"manifest": manifest, "summary": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()

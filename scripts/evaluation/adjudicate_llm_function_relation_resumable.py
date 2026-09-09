from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from moongcheap_ai.demand_clustering.evaluation.llm_function_relation_review import (
    adjudications_to_status_frame,
    build_adjudication_prompt,
    request_openai_adjudication,
    text_fingerprint,
)


DEFAULT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
MAX_BATCH_ATTEMPTS = 3


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _status_fingerprint(status: pd.DataFrame) -> str:
    columns = [
        "direction_id",
        "source_claim_text",
        "candidate_claim_text",
        "reviewer_a_label",
        "reviewer_a_reason_code",
        "reviewer_b_label",
        "reviewer_b_reason_code",
        "agreement_status",
    ]
    if missing := sorted(set(columns) - set(status.columns)):
        raise ValueError(f"status missing columns: {', '.join(missing)}")
    payload = json.dumps(
        status.loc[:, columns].fillna("").astype(str).sort_values(
            "direction_id",
            kind="stable",
        ).to_dict("records"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return text_fingerprint(payload)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Adjudicate relation conflicts with resumable OpenAI batches"
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.5-2026-04-23")
    parser.add_argument(
        "--rubric-version",
        choices=("v1", "v2", "v2.1", "v2.2", "v3"),
        default="v3",
    )
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.batch_size <= 0:
        raise ValueError("batch-size must be positive")

    status = pd.read_csv(args.input, dtype=str, keep_default_na=False)
    if status["direction_id"].duplicated().any():
        raise ValueError("status direction IDs must be unique")
    conflicts = status.loc[
        status["agreement_status"].eq("ADJUDICATION_REQUIRED")
    ].sort_values("direction_id", kind="stable").reset_index(drop=True)
    if conflicts.empty:
        raise ValueError("status has no conflicts to adjudicate")
    source_manifest_text = args.source_manifest.read_text(encoding="utf-8")
    config = {
        "schemaVersion": "mfds-function-relation-resumable-adjudication.v1",
        "inputPath": str(args.input),
        "inputFingerprintSha256": _status_fingerprint(status),
        "sourceManifestFingerprintSha256": text_fingerprint(
            source_manifest_text
        ),
        "model": args.model,
        "rubricVersion": args.rubric_version,
        "conflictCount": len(conflicts),
        "batchSize": args.batch_size,
        "maxOutputTokens": 16384,
    }

    final_paths = {
        "status": args.output_dir / "adjudicated_review_status.csv",
        "summary": args.output_dir / "adjudication_summary.json",
        "raw": args.output_dir / "raw_openai_adjudication.json",
        "manifest": args.output_dir / "adjudication_manifest.json",
    }
    if existing := [str(path) for path in final_paths.values() if path.exists()]:
        raise RuntimeError("final adjudication outputs already exist: " + ", ".join(existing))
    state_path = args.output_dir / "adjudication_checkpoint_manifest.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("config") != config:
            raise RuntimeError("adjudication checkpoint does not match this run")
    else:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "config": config,
            "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "RUNNING",
        }
        _atomic_json(state_path, state)

    load_dotenv(args.env_file, override=False)
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("missing required environment variable: OPENAI_API_KEY")

    total_batches = (len(conflicts) + args.batch_size - 1) // args.batch_size
    adjudicated_batches: list[pd.DataFrame] = []
    raw_batches: list[dict[str, Any]] = []
    prompts: list[str] = []
    for batch_number, start in enumerate(
        range(0, len(conflicts), args.batch_size),
        start=1,
    ):
        batch = conflicts.iloc[start:start + args.batch_size].copy()
        prompt = build_adjudication_prompt(
            batch,
            rubric_version=args.rubric_version,
        )
        prompt_fingerprint = text_fingerprint(prompt)
        direction_ids = batch["direction_id"].astype(str).tolist()
        checkpoint_path = (
            args.output_dir
            / "adjudication_checkpoints"
            / f"batch_{batch_number:04d}.json"
        )
        cached = checkpoint_path.exists()
        if cached:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if checkpoint.get("directionIds") != direction_ids:
                raise RuntimeError(
                    f"checkpoint direction IDs do not match batch {batch_number}"
                )
            if checkpoint.get("promptFingerprintSha256") != prompt_fingerprint:
                raise RuntimeError(
                    f"checkpoint prompt does not match batch {batch_number}"
                )
            raw_text = str(checkpoint["responseText"])
            metadata = checkpoint["metadata"]
            adjudicated = adjudications_to_status_frame(
                batch,
                raw_text,
                adjudicator_id=f"openai:{metadata['model']}",
                rubric_version=args.rubric_version,
            )
        else:
            for attempt in range(1, MAX_BATCH_ATTEMPTS + 1):
                raw_text = ""
                metadata: dict[str, Any] = {}
                try:
                    raw_text, metadata = request_openai_adjudication(
                        prompt,
                        api_key=api_key,
                        model=args.model,
                        direction_ids=direction_ids,
                        rubric_version=args.rubric_version,
                        max_output_tokens=16384,
                    )
                    adjudicated = adjudications_to_status_frame(
                        batch,
                        raw_text,
                        adjudicator_id=f"openai:{metadata['model']}",
                        rubric_version=args.rubric_version,
                    )
                    break
                except Exception as error:
                    _atomic_json(
                        args.output_dir
                        / "adjudication_failures"
                        / f"batch_{batch_number:04d}_attempt_{attempt}.json",
                        {
                            "batchNumber": batch_number,
                            "attempt": attempt,
                            "directionIds": direction_ids,
                            "promptFingerprintSha256": prompt_fingerprint,
                            "errorType": type(error).__name__,
                            "errorMessage": str(error),
                            "metadata": metadata,
                            "responseText": raw_text,
                        },
                    )
                    print(json.dumps({
                        "batch": batch_number,
                        "attempt": attempt,
                        "error": str(error),
                        "retrying": attempt < MAX_BATCH_ATTEMPTS,
                    }), flush=True)
                    if attempt == MAX_BATCH_ATTEMPTS:
                        raise
            _atomic_json(checkpoint_path, {
                "batchNumber": batch_number,
                "directionIds": direction_ids,
                "promptFingerprintSha256": prompt_fingerprint,
                "metadata": metadata,
                "responseText": raw_text,
            })
        adjudicated_batches.append(adjudicated)
        raw_batches.append({
            "batchNumber": batch_number,
            "metadata": metadata,
            "responseText": raw_text,
        })
        prompts.append(prompt)
        print(json.dumps({
            "batch": batch_number,
            "totalBatches": total_batches,
            "cached": cached,
        }), flush=True)

    conflict_results = pd.concat(adjudicated_batches, ignore_index=True)
    non_conflicts = status.loc[
        ~status["agreement_status"].eq("ADJUDICATION_REQUIRED")
    ].copy()
    output = pd.concat([non_conflicts, conflict_results], ignore_index=True).sort_values(
        "direction_id",
        kind="stable",
    ).reset_index(drop=True)
    if len(output) != len(status) or output["direction_id"].duplicated().any():
        raise RuntimeError("adjudication merge did not preserve every direction")
    if output["final_coverage_label"].eq("").any():
        raise RuntimeError("adjudication output contains unfinished final labels")

    label_counts = Counter(output["final_coverage_label"])
    label_equal = status["reviewer_a_label"].eq(status["reviewer_b_label"])
    reason_equal = (
        status["reviewer_a_reason_code"].ne("")
        & status["reviewer_a_reason_code"].eq(status["reviewer_b_reason_code"])
    )
    summary = {
        "schemaVersion": "mfds-function-relation-llm-adjudication.v1",
        "rubricVersion": args.rubric_version,
        "totalQuestions": len(output),
        "acceptedLabelAgreements": int(label_equal.sum()),
        "directLabelAndReasonAgreements": int((label_equal & reason_equal).sum()),
        "adjudicatedQuestions": len(conflicts),
        "reviewerLabelAgreementRate": round(float(label_equal.mean()), 6),
        "finalLabelCounts": dict(sorted(label_counts.items())),
        "finalComplete": True,
        "goldStatus": (
            "LLM_CONSENSUS_CANDIDATE_ONLY: not human or regulatory-domain gold."
        ),
    }
    manifest = {
        "schemaVersion": "mfds-function-relation-llm-adjudication-run.v1",
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runConfig": config,
        "batches": [batch["metadata"] for batch in raw_batches],
        "conflictDirectionIds": conflicts["direction_id"].tolist(),
        "promptFingerprintSha256": text_fingerprint("\n".join(prompts)),
        "responseFingerprintSha256": text_fingerprint("\n".join(
            str(batch["responseText"]) for batch in raw_batches
        )),
        "checkpointPolicy": (
            "Each validated adjudication batch is atomically stored and reused "
            "when an identical run is resumed."
        ),
        "structuredOutput": "Responses API strict JSON schema",
    }
    output.to_csv(final_paths["status"], index=False, encoding="utf-8-sig")
    _atomic_json(final_paths["summary"], summary)
    _atomic_json(final_paths["raw"], {"batches": raw_batches})
    _atomic_json(final_paths["manifest"], manifest)
    state["status"] = "COMPLETE"
    state["completedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _atomic_json(state_path, state)
    print(json.dumps({"manifest": manifest, "summary": summary}), flush=True)


if __name__ == "__main__":
    main()

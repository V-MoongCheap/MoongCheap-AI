from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from moongcheap_ai.demand_clustering.evaluation.function_relation_annotation import (
    compile_function_relation_reviews,
)
from moongcheap_ai.demand_clustering.evaluation.llm_function_relation_review import (
    build_review_prompt,
    decisions_to_review_frame,
    request_anthropic_review,
    request_gemini_review,
    text_fingerprint,
)


DEFAULT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
EVIDENCE_COLUMNS = (
    "direction_id",
    "source_claim_id",
    "source_claim_text",
    "candidate_claim_id",
    "candidate_claim_text",
)
MAX_BATCH_ATTEMPTS = 3


def _required_secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _review_fingerprint(review: pd.DataFrame) -> str:
    missing = sorted(set(EVIDENCE_COLUMNS) - set(review.columns))
    if missing:
        raise ValueError(f"review input missing columns: {', '.join(missing)}")
    payload = json.dumps(
        review.loc[:, EVIDENCE_COLUMNS].fillna("").astype(str).to_dict("records"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return text_fingerprint(payload)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run two independent function-relation reviewers with per-provider "
            "batch checkpoints and automatic resume"
        )
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--reviewer-a", type=Path, required=True)
    parser.add_argument("--reviewer-b", type=Path, required=True)
    parser.add_argument("--anthropic-model", default="claude-sonnet-4-6")
    parser.add_argument("--gemini-model", default="gemini-3.1-pro-preview")
    parser.add_argument(
        "--rubric-version",
        choices=("v1", "v2", "v2.1", "v2.2", "v3"),
        default="v3",
    )
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument(
        "--adjudication-scope",
        choices=("label-and-reason", "label-only"),
        default="label-only",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.batch_size <= 0:
        raise ValueError("batch-size must be positive")

    reviewer_a = pd.read_csv(args.reviewer_a, dtype=str, keep_default_na=False)
    reviewer_b = pd.read_csv(args.reviewer_b, dtype=str, keep_default_na=False)
    config = {
        "schemaVersion": "mfds-function-relation-resumable-review.v1",
        "reviewerAPath": str(args.reviewer_a),
        "reviewerBPath": str(args.reviewer_b),
        "reviewerAFingerprintSha256": _review_fingerprint(reviewer_a),
        "reviewerBFingerprintSha256": _review_fingerprint(reviewer_b),
        "questionCount": len(reviewer_a),
        "anthropicModel": args.anthropic_model,
        "geminiModel": args.gemini_model,
        "rubricVersion": args.rubric_version,
        "adjudicationScope": args.adjudication_scope,
        "batchSize": args.batch_size,
    }
    if len(reviewer_a) != len(reviewer_b):
        raise ValueError("reviewer inputs must contain the same question count")
    if set(reviewer_a["direction_id"]) != set(reviewer_b["direction_id"]):
        raise ValueError("reviewer inputs must contain the same direction IDs")

    state_path = args.output_dir / "checkpoint_manifest.json"
    final_paths = {
        "reviewerA": args.output_dir / "reviewer_a_claude.csv",
        "reviewerB": args.output_dir / "reviewer_b_gemini.csv",
        "status": args.output_dir / "review_status.csv",
        "summary": args.output_dir / "review_status_summary.json",
        "rawA": args.output_dir / "raw_anthropic.json",
        "rawB": args.output_dir / "raw_gemini.json",
        "manifest": args.output_dir / "manifest.json",
    }
    existing_final = [str(path) for path in final_paths.values() if path.exists()]
    if existing_final:
        raise RuntimeError(
            "final review outputs already exist: " + ", ".join(existing_final)
        )
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("config") != config:
            raise RuntimeError("checkpoint configuration does not match this run")
    else:
        if args.output_dir.exists() and any(args.output_dir.iterdir()):
            raise RuntimeError(
                "output directory is nonempty but has no checkpoint manifest"
            )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "config": config,
            "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "RUNNING",
        }
        _atomic_json(state_path, state)

    load_dotenv(args.env_file, override=False)
    provider_specs = {
        "anthropic": {
            "review": reviewer_a,
            "model": args.anthropic_model,
            "apiKey": _required_secret("ANTHROPIC_API_KEY"),
        },
        "google": {
            "review": reviewer_b,
            "model": args.gemini_model,
            "apiKey": _required_secret("GEMINI_API_KEY"),
        },
    }
    stop = Event()

    def run_provider(
        provider: str,
        spec: dict[str, Any],
    ) -> tuple[pd.DataFrame, list[dict[str, Any]], list[str]]:
        review = spec["review"]
        total_batches = (len(review) + args.batch_size - 1) // args.batch_size
        filled_batches: list[pd.DataFrame] = []
        raw_batches: list[dict[str, Any]] = []
        prompts: list[str] = []
        for batch_number, start in enumerate(
            range(0, len(review), args.batch_size),
            start=1,
        ):
            if stop.is_set():
                raise RuntimeError(f"{provider} stopped because its peer failed")
            batch = review.iloc[start:start + args.batch_size].copy()
            prompt = build_review_prompt(
                batch,
                rubric_version=args.rubric_version,
            )
            prompt_fingerprint = text_fingerprint(prompt)
            direction_ids = batch["direction_id"].astype(str).tolist()
            checkpoint_path = (
                args.output_dir
                / "checkpoints"
                / provider
                / f"batch_{batch_number:04d}.json"
            )
            cached = checkpoint_path.exists()
            if cached:
                checkpoint = json.loads(
                    checkpoint_path.read_text(encoding="utf-8")
                )
                if checkpoint.get("directionIds") != direction_ids:
                    raise RuntimeError(
                        f"{provider} checkpoint direction IDs do not match "
                        f"batch {batch_number}"
                    )
                if checkpoint.get("promptFingerprintSha256") != prompt_fingerprint:
                    raise RuntimeError(
                        f"{provider} checkpoint prompt does not match batch "
                        f"{batch_number}"
                    )
                raw_text = str(checkpoint["responseText"])
                metadata = checkpoint["metadata"]
                filled = decisions_to_review_frame(
                    batch,
                    raw_text,
                    reviewer_id=f"{provider}:{metadata['model']}",
                    rubric_version=args.rubric_version,
                    adjudication_scope=args.adjudication_scope,
                )
            else:
                for attempt in range(1, MAX_BATCH_ATTEMPTS + 1):
                    raw_text = ""
                    metadata: dict[str, Any] = {}
                    try:
                        if provider == "anthropic":
                            raw_text, metadata = request_anthropic_review(
                                prompt,
                                api_key=spec["apiKey"],
                                model=spec["model"],
                            )
                        else:
                            raw_text, metadata = request_gemini_review(
                                prompt,
                                api_key=spec["apiKey"],
                                model=spec["model"],
                            )
                        filled = decisions_to_review_frame(
                            batch,
                            raw_text,
                            reviewer_id=f"{provider}:{metadata['model']}",
                            rubric_version=args.rubric_version,
                            adjudication_scope=args.adjudication_scope,
                        )
                        break
                    except Exception as error:
                        failure_path = (
                            args.output_dir
                            / "failures"
                            / provider
                            / (
                                f"batch_{batch_number:04d}_"
                                f"attempt_{attempt}.json"
                            )
                        )
                        _atomic_json(failure_path, {
                            "batchNumber": batch_number,
                            "attempt": attempt,
                            "directionIds": direction_ids,
                            "promptFingerprintSha256": prompt_fingerprint,
                            "errorType": type(error).__name__,
                            "errorMessage": str(error),
                            "metadata": metadata,
                            "responseText": raw_text,
                        })
                        print(json.dumps({
                            "provider": provider,
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
            filled_batches.append(filled)
            raw_batches.append({
                "batchNumber": batch_number,
                "metadata": metadata,
                "responseText": raw_text,
            })
            prompts.append(prompt)
            print(json.dumps({
                "provider": provider,
                "batch": batch_number,
                "totalBatches": total_batches,
                "cached": cached,
            }), flush=True)
        return pd.concat(filled_batches, ignore_index=True), raw_batches, prompts

    results: dict[str, tuple[pd.DataFrame, list[dict[str, Any]], list[str]]] = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(run_provider, provider, spec): provider
            for provider, spec in provider_specs.items()
        }
        try:
            for future in as_completed(futures):
                provider = futures[future]
                results[provider] = future.result()
        except Exception:
            stop.set()
            for future in futures:
                future.cancel()
            raise

    filled_a, raw_a, prompts_a = results["anthropic"]
    filled_b, raw_b, prompts_b = results["google"]
    status, summary = compile_function_relation_reviews(
        filled_a,
        filled_b,
        rubric_version=args.rubric_version,
        adjudication_scope=args.adjudication_scope,
    )
    manifest = {
        "schemaVersion": "mfds-function-relation-llm-review.v1",
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runConfig": config,
        "reviewers": [
            {
                "provider": "anthropic",
                "requestedModel": args.anthropic_model,
                "batches": [batch["metadata"] for batch in raw_a],
            },
            {
                "provider": "google",
                "requestedModel": args.gemini_model,
                "batches": [batch["metadata"] for batch in raw_b],
            },
        ],
        "promptFingerprintA": text_fingerprint("\n".join(prompts_a)),
        "promptFingerprintB": text_fingerprint("\n".join(prompts_b)),
        "responseFingerprintA": text_fingerprint("\n".join(
            str(batch["responseText"]) for batch in raw_a
        )),
        "responseFingerprintB": text_fingerprint("\n".join(
            str(batch["responseText"]) for batch in raw_b
        )),
        "checkpointPolicy": (
            "Each validated provider batch is atomically stored and reused "
            "when an identical run is resumed."
        ),
        "runtimePolicy": (
            "External reviewers are offline-only and are not production "
            "dependencies."
        ),
        "goldStatus": (
            "LLM_CONSENSUS_CANDIDATE_ONLY: not human or regulatory-domain gold."
        ),
    }
    filled_a.to_csv(final_paths["reviewerA"], index=False, encoding="utf-8-sig")
    filled_b.to_csv(final_paths["reviewerB"], index=False, encoding="utf-8-sig")
    status.to_csv(final_paths["status"], index=False, encoding="utf-8-sig")
    _atomic_json(final_paths["summary"], summary)
    _atomic_json(final_paths["rawA"], {"batches": raw_a})
    _atomic_json(final_paths["rawB"], {"batches": raw_b})
    _atomic_json(final_paths["manifest"], manifest)
    state["status"] = "COMPLETE"
    state["completedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _atomic_json(state_path, state)
    print(json.dumps({"manifest": manifest, "summary": summary}), flush=True)


if __name__ == "__main__":
    main()

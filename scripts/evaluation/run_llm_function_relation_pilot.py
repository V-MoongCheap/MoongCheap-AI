from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

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


def _required_secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run two independent external LLMs on the function pilot"
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument(
        "--reviewer-a",
        type=Path,
        default=Path("data/reports/function_relation_pilot_v1/reviewer_a.csv"),
    )
    parser.add_argument(
        "--reviewer-b",
        type=Path,
        default=Path("data/reports/function_relation_pilot_v1/reviewer_b.csv"),
    )
    parser.add_argument("--anthropic-model", default="claude-sonnet-4-6")
    parser.add_argument("--gemini-model", default="gemini-3.1-pro-preview")
    parser.add_argument(
        "--rubric-version",
        choices=("v1", "v2", "v2.1", "v2.2", "v3"),
        default="v1",
    )
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument(
        "--adjudication-scope",
        choices=("label-and-reason", "label-only"),
        default="label-and-reason",
        help="Whether reason-only disagreements require adjudication",
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
        "reviewerA": args.output_dir / "reviewer_a_claude.csv",
        "reviewerB": args.output_dir / "reviewer_b_gemini.csv",
        "status": args.output_dir / "review_status.csv",
        "summary": args.output_dir / "review_status_summary.json",
        "rawA": args.output_dir / "raw_anthropic.json",
        "rawB": args.output_dir / "raw_gemini.json",
        "manifest": args.output_dir / "manifest.json",
    }
    existing = [str(path) for path in output_paths.values() if path.exists()]
    if existing:
        raise RuntimeError(
            "refusing to overwrite existing LLM review outputs: "
            + ", ".join(existing)
        )

    load_dotenv(args.env_file, override=False)
    if args.batch_size <= 0:
        raise ValueError("batch-size must be positive")
    anthropic_key = _required_secret("ANTHROPIC_API_KEY")
    gemini_key = _required_secret("GEMINI_API_KEY")
    reviewer_a = pd.read_csv(args.reviewer_a, dtype=str, keep_default_na=False)
    reviewer_b = pd.read_csv(args.reviewer_b, dtype=str, keep_default_na=False)

    def run_batches(
        review: pd.DataFrame,
        *,
        provider: str,
        model: str,
    ) -> tuple[pd.DataFrame, list[dict[str, object]], list[str]]:
        filled_batches: list[pd.DataFrame] = []
        raw_batches: list[dict[str, object]] = []
        prompts: list[str] = []
        for start in range(0, len(review), args.batch_size):
            batch = review.iloc[start:start + args.batch_size].copy()
            prompt = build_review_prompt(
                batch,
                rubric_version=args.rubric_version,
            )
            if provider == "anthropic":
                raw_text, metadata = request_anthropic_review(
                    prompt,
                    api_key=anthropic_key,
                    model=model,
                )
            else:
                raw_text, metadata = request_gemini_review(
                    prompt,
                    api_key=gemini_key,
                    model=model,
                )
            filled_batches.append(decisions_to_review_frame(
                batch,
                raw_text,
                reviewer_id=f"{provider}:{metadata['model']}",
                rubric_version=args.rubric_version,
                adjudication_scope=args.adjudication_scope,
            ))
            raw_batches.append({
                "batchNumber": len(raw_batches) + 1,
                "metadata": metadata,
                "responseText": raw_text,
            })
            prompts.append(prompt)
        reviewer_ids = {
            reviewer_id
            for frame in filled_batches
            for reviewer_id in frame["reviewer_id"]
        }
        if len(reviewer_ids) != 1:
            raise RuntimeError(
                f"{provider} returned inconsistent model identifiers: "
                f"{sorted(reviewer_ids)}"
            )
        return (
            pd.concat(filled_batches, ignore_index=True),
            raw_batches,
            prompts,
        )

    filled_a, raw_batches_a, prompts_a = run_batches(
        reviewer_a,
        provider="anthropic",
        model=args.anthropic_model,
    )
    filled_b, raw_batches_b, prompts_b = run_batches(
        reviewer_b,
        provider="google",
        model=args.gemini_model,
    )
    status, summary = compile_function_relation_reviews(
        filled_a,
        filled_b,
        rubric_version=args.rubric_version,
        adjudication_scope=args.adjudication_scope,
    )

    args.output_dir.mkdir(parents=True, exist_ok=False)
    filled_a.to_csv(output_paths["reviewerA"], index=False, encoding="utf-8-sig")
    filled_b.to_csv(output_paths["reviewerB"], index=False, encoding="utf-8-sig")
    status.to_csv(output_paths["status"], index=False, encoding="utf-8-sig")
    output_paths["summary"].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    output_paths["rawA"].write_text(
        json.dumps(
            {"batches": raw_batches_a},
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    output_paths["rawB"].write_text(
        json.dumps(
            {"batches": raw_batches_b},
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schemaVersion": "mfds-function-relation-llm-pilot.v1",
        "rubricVersion": args.rubric_version,
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "questionCount": len(status),
        "reviewers": [
            {
                "provider": "anthropic",
                "requestedModel": args.anthropic_model,
                "batches": [batch["metadata"] for batch in raw_batches_a],
            },
            {
                "provider": "google",
                "requestedModel": args.gemini_model,
                "batches": [batch["metadata"] for batch in raw_batches_b],
            },
        ],
        "batchSize": args.batch_size,
        "adjudicationScope": args.adjudication_scope,
        "generationSettings": {
            "anthropic": (
                "provider default; temperature omitted"
            ),
            "google": "temperature=0",
        },
        "promptFingerprintA": text_fingerprint("\n".join(prompts_a)),
        "promptFingerprintB": text_fingerprint("\n".join(prompts_b)),
        "responseFingerprintA": text_fingerprint("\n".join(
            str(batch["responseText"]) for batch in raw_batches_a
        )),
        "responseFingerprintB": text_fingerprint("\n".join(
            str(batch["responseText"]) for batch in raw_batches_b
        )),
        "independence": (
            "Each provider received only its own ordered question set and the "
            "shared rubric; neither response was included in the other prompt."
        ),
        "evidenceVisibility": (
            "Claim IDs and official function texts only; ingredient/reference "
            "names, strata, and similarity scores were omitted."
        ),
        "goldStatus": (
            "LLM_CONSENSUS_CANDIDATE_ONLY: this is not independent human or "
            "regulatory-domain gold."
        ),
    }
    output_paths["manifest"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"manifest": manifest, "summary": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()

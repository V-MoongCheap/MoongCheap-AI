from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from moongcheap_ai.demand_clustering.evaluation.product_proposal_quality import (
    CLUSTERING_SCOPE_REASON_CODES,
    CLUSTERING_SCOPE_PRODUCT_REVIEW_SYSTEM_PROMPT,
    build_clustering_scope_product_proposal_review_prompt,
    decisions_to_product_proposal_review,
    request_anthropic_product_proposal_review,
    request_gemini_product_proposal_review,
)


DEFAULT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
MAX_ATTEMPTS = 3


def _fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def _metrics(reviewed: pd.DataFrame) -> dict[str, Any]:
    labels = Counter(reviewed["review_label"])
    reasons = Counter(reviewed["review_reason_code"])
    pair_label_counts = reviewed.groupby("pair_id")["review_label"].nunique()
    return {
        "schemaVersion": "single-llm-actual-proposal-evaluation.v1",
        "proposalCount": len(reviewed),
        "uniquePairCount": int(reviewed["pair_id"].nunique()),
        "judgeItemCount": int(reviewed["pair_id"].nunique()),
        "labelCounts": dict(sorted(labels.items())),
        "labelRates": {
            label: round(count / len(reviewed), 6)
            for label, count in sorted(labels.items())
        },
        "reasonCodeCounts": dict(sorted(reasons.items())),
        "automaticContractPassedCount": int(
            reviewed["automatic_contract_status"].eq("PASSED").sum()
        ),
        "automaticContractFailedCount": int(
            reviewed["automatic_contract_status"].eq("FAILED").sum()
        ),
        "repeatedPairLabelInconsistencyCount": int(pair_label_counts.gt(1).sum()),
        "pairLabelsProjectedToProposalRows": True,
        "runtimeReviewRows": 0,
        "interpretation": (
            "One temperature-zero LLM Judge is an offline semantic quality "
            "proxy, not human ground truth, domain approval, or observed user "
            "acceptance. Runtime does not call this Judge."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one offline LLM Judge over actual board proposals"
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(
            "data/reports/actual_board_proposal_review_set/"
            "actual_proposal_review_set.csv"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "data/reports/actual_board_proposal_llm_judge_clustering_scope"
        ),
    )
    parser.add_argument(
        "--provider",
        choices=("anthropic", "gemini"),
        default="anthropic",
    )
    parser.add_argument("--model")
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()
    if args.batch_size < 1:
        raise ValueError("batch-size must be positive")
    model = args.model or (
        "claude-sonnet-4-6"
        if args.provider == "anthropic"
        else "gemini-3.1-pro-preview"
    )
    review = pd.read_csv(args.input, dtype=str, keep_default_na=False)
    if review.empty or review["proposal_id"].duplicated().any():
        raise ValueError("input must contain unique proposal rows")
    if not review["automatic_contract_status"].eq("PASSED").all():
        raise RuntimeError("refusing semantic review with contract audit failures")
    judge_input = (
        review.sort_values(["pair_id", "proposal_id"], kind="stable")
        .drop_duplicates("pair_id", keep="first")
        .reset_index(drop=True)
    )

    config = {
        "schemaVersion": "single-product-proposal-judge-run.v1",
        "inputPath": str(args.input),
        "inputSha256": _fingerprint(args.input),
        "proposalCount": len(review),
        "judgeItemCount": len(judge_input),
        "deduplicationPolicy": "JUDGE_EACH_PAIR_ONCE_THEN_PROJECT_TO_PROPOSALS",
        "evaluationScope": "OFFICIAL_FUNCTION_PRESERVATION_ONLY",
        "provider": args.provider,
        "model": model,
        "batchSize": args.batch_size,
    }
    state_path = args.output_dir / "checkpoint_manifest.json"
    final_paths = {
        "evaluated": args.output_dir / "evaluated_proposals.csv",
        "metrics": args.output_dir / "metrics.json",
        "manifest": args.output_dir / "manifest.json",
    }
    if any(path.exists() for path in final_paths.values()):
        raise RuntimeError("final Judge outputs already exist")
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("config") != config:
            raise RuntimeError("checkpoint configuration differs from this run")
    else:
        if args.output_dir.exists() and any(args.output_dir.iterdir()):
            raise RuntimeError("nonempty output directory has no checkpoint")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "config": config,
            "status": "RUNNING",
            "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _atomic_json(state_path, state)

    load_dotenv(args.env_file, override=False)
    api_key = _secret(
        "ANTHROPIC_API_KEY" if args.provider == "anthropic" else "GEMINI_API_KEY"
    )
    completed: list[pd.DataFrame] = []
    metadata_rows: list[dict[str, Any]] = []
    total_batches = (len(judge_input) + args.batch_size - 1) // args.batch_size
    for batch_number, start in enumerate(
        range(0, len(judge_input), args.batch_size), 1
    ):
        batch = judge_input.iloc[start:start + args.batch_size].copy()
        prompt = build_clustering_scope_product_proposal_review_prompt(batch)
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        proposal_ids = batch["proposal_id"].tolist()
        checkpoint = args.output_dir / "checkpoints" / f"batch_{batch_number:04d}.json"
        if checkpoint.exists():
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            if payload["proposalIds"] != proposal_ids:
                raise RuntimeError("checkpoint proposal IDs differ")
            if payload["promptSha256"] != prompt_hash:
                raise RuntimeError("checkpoint prompt differs")
            response_text = payload["responseText"]
            metadata = payload["metadata"]
            filled = decisions_to_product_proposal_review(
                batch,
                response_text,
                reviewer_id=f"{args.provider}:{metadata['model']}",
                reason_codes=CLUSTERING_SCOPE_REASON_CODES,
            )
        else:
            last_error: Exception | None = None
            for attempt in range(1, MAX_ATTEMPTS + 1):
                response_text = ""
                metadata = {}
                try:
                    if args.provider == "anthropic":
                        response_text, metadata = (
                            request_anthropic_product_proposal_review(
                                prompt,
                                api_key=api_key,
                                model=model,
                                system_prompt=(
                                    CLUSTERING_SCOPE_PRODUCT_REVIEW_SYSTEM_PROMPT
                                ),
                            )
                        )
                    else:
                        response_text, metadata = (
                            request_gemini_product_proposal_review(
                                prompt,
                                api_key=api_key,
                                model=model,
                                system_prompt=(
                                    CLUSTERING_SCOPE_PRODUCT_REVIEW_SYSTEM_PROMPT
                                ),
                            )
                        )
                    filled = decisions_to_product_proposal_review(
                        batch,
                        response_text,
                        reviewer_id=f"{args.provider}:{metadata['model']}",
                        reason_codes=CLUSTERING_SCOPE_REASON_CODES,
                    )
                    break
                except Exception as error:
                    last_error = error
                    _atomic_json(
                        args.output_dir / "failures"
                        / f"batch_{batch_number:04d}_attempt_{attempt}.json",
                        {
                            "errorType": type(error).__name__,
                            "errorMessage": str(error),
                            "proposalIds": proposal_ids,
                            "responseText": response_text,
                            "metadata": metadata,
                        },
                    )
            else:
                assert last_error is not None
                raise last_error
            _atomic_json(checkpoint, {
                "batchNumber": batch_number,
                "proposalIds": proposal_ids,
                "promptSha256": prompt_hash,
                "responseText": response_text,
                "metadata": metadata,
            })
        completed.append(filled)
        metadata_rows.append(metadata)
        print(json.dumps({
            "batch": batch_number,
            "totalBatches": total_batches,
            "provider": args.provider,
        }), flush=True)

    judged_pairs = pd.concat(completed, ignore_index=True)
    pair_results = judged_pairs[[
        "pair_id",
        "reviewer_id",
        "review_label",
        "review_reason_code",
        "review_note",
    ]]
    evaluated = review.merge(
        pair_results,
        on="pair_id",
        how="left",
        validate="many_to_one",
    )
    if (
        evaluated["review_label"].eq("").any()
        or evaluated["review_label"].isna().any()
    ):
        raise RuntimeError("not all proposal rows received a projected pair label")
    metrics = _metrics(evaluated)
    evaluated.to_csv(
        final_paths["evaluated"],
        index=False,
        encoding="utf-8-sig",
    )
    _atomic_json(final_paths["metrics"], metrics)
    completed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _atomic_json(final_paths["manifest"], {
        **config,
        "completedAt": completed_at,
        "sampling": "temperature=0",
        "runtimeUse": "FORBIDDEN_OFFLINE_EVALUATION_ONLY",
        "judgeBatches": metadata_rows,
        "resultPaths": {key: str(value) for key, value in final_paths.items()},
    })
    state["status"] = "COMPLETED"
    state["completedAt"] = completed_at
    _atomic_json(state_path, state)
    print(json.dumps(metrics, ensure_ascii=False))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.function_relation_embedding import (
    load_sentence_transformer,
    sentence_transformer_embeddings,
    tfidf_embeddings,
)
from moongcheap_ai.demand_clustering.evaluation.function_relation_retrieval_evaluation import (
    evaluate_function_relation_retrieval,
)
from moongcheap_ai.demand_clustering.evaluation.function_relation_review import (
    build_function_claim_index,
)


def _fingerprint(frame: pd.DataFrame, columns: list[str]) -> str:
    rows = frame.loc[:, columns].fillna("").astype(str).sort_values(
        columns,
        kind="stable",
    )
    payload = "\n".join(
        "\x1f".join(row) for row in rows.itertuples(index=False, name=None)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_gold(paths: list[Path]) -> pd.DataFrame:
    if not paths:
        raise ValueError("at least one --gold file is required")
    frames = [pd.read_csv(path, dtype=str, keep_default_na=False) for path in paths]
    gold = pd.concat(frames, ignore_index=True)
    required = {
        "direction_id",
        "source_claim_id",
        "source_claim_text",
        "candidate_claim_id",
        "candidate_claim_text",
        "final_coverage_label",
    }
    if missing := sorted(required - set(gold.columns)):
        raise ValueError(f"gold files missing columns: {', '.join(missing)}")
    if gold["direction_id"].duplicated().any():
        raise ValueError("gold files contain duplicate direction IDs")
    return gold


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark offline retrieval of MFDS function relations"
    )
    parser.add_argument("--gold", action="append", type=Path, default=[])
    parser.add_argument(
        "--claims",
        type=Path,
        default=Path("data/reports/mfds_function_claim_candidates_v1.csv"),
    )
    parser.add_argument(
        "--backend",
        choices=("tfidf", "sentence-transformer"),
        required=True,
    )
    parser.add_argument("--model-id")
    parser.add_argument("--revision")
    parser.add_argument(
        "--input-mode",
        choices=("plain", "e5-retrieval"),
        default="plain",
    )
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.batch_size <= 0:
        raise ValueError("batch-size must be positive")
    if args.backend == "sentence-transformer" and not args.model_id:
        raise ValueError("--model-id is required for sentence-transformer")
    if args.backend == "tfidf" and args.model_id:
        raise ValueError("--model-id is not used by the TF-IDF backend")
    if args.output_dir.exists():
        raise RuntimeError(f"refusing to overwrite output directory: {args.output_dir}")

    gold = _load_gold(args.gold)
    claims = build_function_claim_index(
        pd.read_csv(args.claims, dtype=str, keep_default_na=False)
    )
    claim_text_by_id = claims.set_index("claim_id")["claim_text"].to_dict()
    gold_claim_ids = set(gold["source_claim_id"]) | set(gold["candidate_claim_id"])
    if missing_claim_ids := sorted(gold_claim_ids - set(claim_text_by_id)):
        raise ValueError(
            "gold claim IDs missing from claim index: " + ", ".join(missing_claim_ids)
        )
    for side in ("source", "candidate"):
        expected = gold[f"{side}_claim_id"].map(claim_text_by_id)
        if not expected.eq(gold[f"{side}_claim_text"]).all():
            raise ValueError(f"gold {side} claim text does not match claim index")

    claim_ids = claims["claim_id"].tolist()
    claim_texts = claims["claim_text"].tolist()
    if args.backend == "tfidf":
        query_embeddings = tfidf_embeddings(claim_texts)
        candidate_embeddings = query_embeddings
        resolved_model = "char-tfidf-2-4gram"
        package_versions = {
            "scikit-learn": importlib.metadata.version("scikit-learn"),
        }
    else:
        query_prefix = "query: " if args.input_mode == "e5-retrieval" else ""
        candidate_prefix = (
            "passage: " if args.input_mode == "e5-retrieval" else ""
        )
        model = load_sentence_transformer(args.model_id, args.revision)
        query_embeddings = sentence_transformer_embeddings(
            model,
            claim_texts,
            prefix=query_prefix,
            batch_size=args.batch_size,
        )
        candidate_embeddings = (
            sentence_transformer_embeddings(
                model,
                claim_texts,
                prefix=candidate_prefix,
                batch_size=args.batch_size,
            )
            if candidate_prefix != query_prefix
            else query_embeddings
        )
        resolved_model = args.model_id
        package_versions = {
            "sentence-transformers": importlib.metadata.version(
                "sentence-transformers"
            ),
            "torch": importlib.metadata.version("torch"),
            "transformers": importlib.metadata.version("transformers"),
        }

    similarities = query_embeddings @ candidate_embeddings.T
    claim_position = {claim_id: index for index, claim_id in enumerate(claim_ids)}
    source_ids = sorted(set(gold["source_claim_id"]))
    score_rows = [
        {
            "source_claim_id": source_id,
            "candidate_claim_id": candidate_id,
            "score": float(similarities[
                claim_position[source_id],
                claim_position[candidate_id],
            ]),
        }
        for source_id in source_ids
        for candidate_id in claim_ids
        if candidate_id != source_id
    ]
    candidate_scores = pd.DataFrame(score_rows)
    metrics, positive_ranks = evaluate_function_relation_retrieval(
        gold,
        candidate_scores,
    )
    judged_scores = gold.merge(
        candidate_scores,
        on=["source_claim_id", "candidate_claim_id"],
        how="left",
        validate="one_to_one",
    )
    manifest = {
        "schemaVersion": "mfds-function-relation-retrieval-run.v1",
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "backend": args.backend,
        "modelId": resolved_model,
        "requestedRevision": args.revision,
        "inputMode": args.input_mode,
        "device": "cpu",
        "claimCount": len(claims),
        "goldFiles": [str(path) for path in args.gold],
        "goldFingerprintSha256": _fingerprint(
            gold,
            ["direction_id", "final_coverage_label", "final_reason_code"],
        ),
        "claimFingerprintSha256": _fingerprint(
            claims,
            ["claim_id", "claim_text"],
        ),
        "packageVersions": package_versions,
        "runtimePolicy": (
            "External LLMs remain offline-only. A validated CPU embedding model "
            "may be used for production ranking; static embeddings should be "
            "precomputed when practical."
        ),
    }
    args.output_dir.mkdir(parents=True)
    judged_scores.to_csv(
        args.output_dir / "judged_direction_scores.csv",
        index=False,
        encoding="utf-8-sig",
    )
    positive_ranks.to_csv(
        args.output_dir / "known_positive_ranks.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"manifest": manifest, "metrics": metrics}, ensure_ascii=False))


if __name__ == "__main__":
    main()

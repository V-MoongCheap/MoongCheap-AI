from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from moongcheap_ai.demand_clustering.function_relation_embedding import (
    load_sentence_transformer,
    sentence_transformer_embeddings,
    tfidf_embeddings,
)
from moongcheap_ai.demand_clustering.evaluation.function_relation_retrieval_evaluation import (
    build_function_relation_candidate_set,
)
from moongcheap_ai.demand_clustering.evaluation.function_relation_review import (
    build_function_claim_index,
)


DEFAULT_E5_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_E5_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"


def _fingerprint(frame: pd.DataFrame, columns: list[str]) -> str:
    rows = frame.loc[:, columns].fillna("").astype(str).sort_values(
        columns,
        kind="stable",
    )
    payload = "\n".join(
        "\x1f".join(row) for row in rows.itertuples(index=False, name=None)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _all_direction_scores(
    claim_ids: list[str],
    query_embeddings: np.ndarray,
    candidate_embeddings: np.ndarray,
) -> pd.DataFrame:
    if query_embeddings.shape[0] != len(claim_ids):
        raise ValueError("query embedding count does not match claims")
    if candidate_embeddings.shape[0] != len(claim_ids):
        raise ValueError("candidate embedding count does not match claims")
    similarities = query_embeddings @ candidate_embeddings.T
    return pd.DataFrame([
        {
            "source_claim_id": source_id,
            "candidate_claim_id": candidate_id,
            "score": float(similarities[source_index, candidate_index]),
        }
        for source_index, source_id in enumerate(claim_ids)
        for candidate_index, candidate_id in enumerate(claim_ids)
        if source_id != candidate_id
    ])


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build the bounded TF-IDF and CPU E5 union for offline function "
            "relation review"
        )
    )
    parser.add_argument(
        "--claims",
        type=Path,
        default=Path("data/reports/mfds_function_claim_candidates_v1.csv"),
    )
    parser.add_argument(
        "--known-relations",
        type=Path,
        default=Path(
            "data/reports/function_relation_positive_safety_audit_v1/"
            "approved_relation_status_all.csv"
        ),
    )
    parser.add_argument("--e5-model", default=DEFAULT_E5_MODEL)
    parser.add_argument("--e5-revision", default=DEFAULT_E5_REVISION)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.batch_size <= 0:
        raise ValueError("batch-size must be positive")
    if args.output_dir.exists():
        raise RuntimeError(f"refusing to overwrite output directory: {args.output_dir}")

    claims = build_function_claim_index(
        pd.read_csv(args.claims, dtype=str, keep_default_na=False)
    )
    known = pd.read_csv(args.known_relations, dtype=str, keep_default_na=False)
    claim_ids = claims["claim_id"].tolist()
    claim_texts = claims["claim_text"].tolist()

    tfidf = tfidf_embeddings(claim_texts)
    tfidf_scores = _all_direction_scores(claim_ids, tfidf, tfidf)

    model = load_sentence_transformer(args.e5_model, args.e5_revision)
    e5_queries = sentence_transformer_embeddings(
        model,
        claim_texts,
        prefix="query: ",
        batch_size=args.batch_size,
    )
    e5_candidates = sentence_transformer_embeddings(
        model,
        claim_texts,
        prefix="passage: ",
        batch_size=args.batch_size,
    )
    e5_scores = _all_direction_scores(claim_ids, e5_queries, e5_candidates)

    candidates, positive_recovery, summary = build_function_relation_candidate_set(
        claims,
        {"tfidf": tfidf_scores, "e5": e5_scores},
        known,
        top_k=args.top_k,
    )
    manifest = {
        "schemaVersion": "mfds-function-relation-candidate-set-run.v1",
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "claimSource": str(args.claims),
        "knownRelationSource": str(args.known_relations),
        "claimFingerprintSha256": _fingerprint(
            claims,
            ["claim_id", "claim_text"],
        ),
        "knownRelationFingerprintSha256": _fingerprint(
            known,
            [
                "direction_id",
                "final_coverage_label",
                "final_reason_code",
                "safety_audit_status",
            ],
        ),
        "retrievers": {
            "tfidf": {
                "configuration": "character 2-4 gram, sublinear tf, L2 norm",
                "packageVersion": importlib.metadata.version("scikit-learn"),
            },
            "e5": {
                "modelId": args.e5_model,
                "revision": args.e5_revision,
                "inputMode": "query/passage",
                "device": "cpu",
                "packageVersions": {
                    "sentence-transformers": importlib.metadata.version(
                        "sentence-transformers"
                    ),
                    "torch": importlib.metadata.version("torch"),
                    "transformers": importlib.metadata.version("transformers"),
                },
            },
        },
        "topKPerRetriever": args.top_k,
        "reviewRuleVersion": "v3",
        "policy": (
            "External LLMs are offline reviewers only. CPU retrieval does not "
            "approve coverage; production requires an approved directional "
            "relation and otherwise makes no proposal."
        ),
    }

    args.output_dir.mkdir(parents=True)
    candidates.to_csv(
        args.output_dir / "relation_candidates.csv",
        index=False,
        encoding="utf-8-sig",
    )
    positive_recovery.to_csv(
        args.output_dir / "known_positive_recovery.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"manifest": manifest, "summary": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()

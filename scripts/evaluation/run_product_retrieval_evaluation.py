from __future__ import annotations

import argparse
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from moongcheap_ai.demand_clustering.function_relation_embedding import (
    sentence_transformer_embeddings,
    tfidf_embeddings,
)
from moongcheap_ai.demand_clustering.evaluation.product_retrieval_evaluation import (
    build_product_retrieval_texts,
    evaluate_product_retrieval,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate bounded CPU product retrieval before the hard gate"
    )
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--eligible-pairs", type=Path, required=True)
    parser.add_argument(
        "--backend",
        choices=("tfidf", "sentence-transformer"),
        required=True,
    )
    parser.add_argument(
        "--text-mode",
        choices=("FUNCTION_ONLY", "FUNCTION_INGREDIENT_FORM"),
        required=True,
    )
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--model-id")
    parser.add_argument("--model-revision")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise RuntimeError(
            f"refusing to overwrite output directory: {args.output_dir}"
        )
    if args.backend == "sentence-transformer" and args.model_path is None:
        raise ValueError("--model-path is required for sentence-transformer")
    if args.backend == "tfidf" and args.model_path is not None:
        raise ValueError("--model-path is not used by TF-IDF")

    profiles = pd.read_csv(args.profiles, dtype=str, keep_default_na=False)
    retrieval_profiles = build_product_retrieval_texts(
        profiles,
        text_mode=args.text_mode,
    )
    texts = retrieval_profiles["retrieval_text"].tolist()
    if args.backend == "tfidf":
        query_embeddings = tfidf_embeddings(texts)
        candidate_embeddings = query_embeddings
        resolved_model_id = "char-tfidf-2-4gram"
        package_versions = {
            "scikit-learn": importlib.metadata.version("scikit-learn"),
        }
    else:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(str(args.model_path), device="cpu")
        query_embeddings = sentence_transformer_embeddings(
            model,
            texts,
            prefix="query: ",
            batch_size=args.batch_size,
        )
        candidate_embeddings = sentence_transformer_embeddings(
            model,
            texts,
            prefix="passage: ",
            batch_size=args.batch_size,
        )
        resolved_model_id = args.model_id or str(args.model_path)
        package_versions = {
            "sentence-transformers": importlib.metadata.version(
                "sentence-transformers"
            ),
            "torch": importlib.metadata.version("torch"),
            "transformers": importlib.metadata.version("transformers"),
        }

    similarities = np.asarray(query_embeddings @ candidate_embeddings.T)
    ids = retrieval_profiles["catalog_id"].tolist()
    categories = retrieval_profiles["service_category_id"].tolist()
    score_rows = [
        {
            "source_catalog_id": source_id,
            "candidate_catalog_id": candidate_id,
            "score": float(similarities[source_index, candidate_index]),
        }
        for source_index, source_id in enumerate(ids)
        for candidate_index, candidate_id in enumerate(ids)
        if source_id != candidate_id
        and categories[source_index] == categories[candidate_index]
    ]
    top_candidates, source_summary, metrics = evaluate_product_retrieval(
        retrieval_profiles,
        pd.read_csv(
            args.eligible_pairs,
            dtype=str,
            keep_default_na=False,
        ),
        pd.DataFrame(score_rows),
    )
    manifest = {
        "schemaVersion": "product-retrieval-run.v1",
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "backend": args.backend,
        "textMode": args.text_mode,
        "modelId": resolved_model_id,
        "modelRevision": args.model_revision,
        "device": "cpu",
        "profileRows": len(retrieval_profiles),
        "packageVersions": package_versions,
        "sourcePaths": {
            "profiles": str(args.profiles),
            "eligiblePairs": str(args.eligible_pairs),
            "modelPath": str(args.model_path) if args.model_path else None,
        },
        "metricsFile": "metrics.json",
        "topCandidatesFile": "top_candidates.csv",
        "sourceSummaryFile": "source_retrieval_summary.csv",
    }
    args.output_dir.mkdir(parents=True)
    top_candidates.to_csv(
        args.output_dir / "top_candidates.csv",
        index=False,
        encoding="utf-8-sig",
    )
    source_summary.to_csv(
        args.output_dir / "source_retrieval_summary.csv",
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

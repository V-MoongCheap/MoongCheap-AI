"""Shared CPU embedding helpers for runtime scoring and offline retrieval.

Optional model dependencies are loaded only when their helpers are called.
"""

from __future__ import annotations

import numpy as np


def tfidf_embeddings(texts: list[str]) -> np.ndarray:
    """Return normalized character 2-4 gram TF-IDF vectors."""

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError as error:
        raise RuntimeError(
            "TF-IDF retrieval requires scikit-learn in the evaluation or "
            "serving environment"
        ) from error
    vectorizer = TfidfVectorizer(
        analyzer="char",
        ngram_range=(2, 4),
        lowercase=True,
        sublinear_tf=True,
        norm="l2",
    )
    return vectorizer.fit_transform(texts).toarray().astype(np.float32)


def load_sentence_transformer(model_id: str, revision: str | None):
    """Load a sentence-transformers model on CPU only."""

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise RuntimeError(
            "embedding retrieval requires sentence-transformers in the "
            "evaluation or serving environment"
        ) from error
    return SentenceTransformer(model_id, revision=revision, device="cpu")


def sentence_transformer_embeddings(
    model,
    texts: list[str],
    *,
    prefix: str,
    batch_size: int,
    show_progress_bar: bool = True,
) -> np.ndarray:
    """Return normalized CPU sentence embeddings with an optional prefix."""

    inputs = [f"{prefix}{text}" for text in texts]
    return model.encode(
        inputs,
        batch_size=batch_size,
        show_progress_bar=show_progress_bar,
        convert_to_numpy=True,
        normalize_embeddings=True,
    ).astype(np.float32)

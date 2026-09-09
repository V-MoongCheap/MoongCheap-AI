"""Lazy, CPU-only E5 scorer for PASSTHROUGH demand preferences."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .function_relation_embedding import (
    load_sentence_transformer,
    sentence_transformer_embeddings,
)


ModelLoader = Callable[[str, str | None], Any]
EmbeddingBuilder = Callable[..., np.ndarray]

E5_MODEL_PATH_ENV = "E5_MODEL_PATH"
E5_MODEL_REVISION_ENV = "E5_MODEL_REVISION"
E5_BATCH_SIZE_ENV = "E5_BATCH_SIZE"
DEFAULT_E5_BATCH_SIZE = 32


@dataclass(frozen=True, slots=True)
class E5RuntimeScorerConfig:
    model_path: Path
    model_revision: str | None = None
    batch_size: int = 32

    def __post_init__(self) -> None:
        if not str(self.model_path).strip():
            raise ValueError("model_path must not be empty")
        if self.batch_size < 1:
            raise ValueError("batch_size must be positive")

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> E5RuntimeScorerConfig:
        source = os.environ if environ is None else environ
        model_path = source.get(E5_MODEL_PATH_ENV, "").strip()
        if not model_path:
            raise ValueError(f"{E5_MODEL_PATH_ENV} must not be empty")

        raw_batch_size = source.get(
            E5_BATCH_SIZE_ENV,
            str(DEFAULT_E5_BATCH_SIZE),
        ).strip()
        try:
            batch_size = int(raw_batch_size)
        except ValueError as error:
            raise ValueError(
                f"{E5_BATCH_SIZE_ENV} must be an integer"
            ) from error
        revision = source.get(E5_MODEL_REVISION_ENV, "").strip() or None
        return cls(
            model_path=Path(model_path),
            model_revision=revision,
            batch_size=batch_size,
        )


class E5RuntimeTextSimilarityScorer:
    """Cache normalized query and passage embeddings for one batch process."""

    def __init__(
        self,
        config: E5RuntimeScorerConfig,
        *,
        model_loader: ModelLoader = load_sentence_transformer,
        embedding_builder: EmbeddingBuilder = sentence_transformer_embeddings,
    ) -> None:
        self._config = config
        self._model_loader = model_loader
        self._embedding_builder = embedding_builder
        self._model: Any | None = None
        self._query_vectors: dict[str, np.ndarray] = {}
        self._passage_vectors: dict[str, np.ndarray] = {}

    @property
    def model_loaded(self) -> bool:
        return self._model is not None

    @property
    def cache_summary(self) -> dict[str, int | bool]:
        return {
            "modelLoaded": self.model_loaded,
            "queryCount": len(self._query_vectors),
            "passageCount": len(self._passage_vectors),
        }

    def _load_model(self) -> Any:
        if self._model is None:
            self._model = self._model_loader(
                str(self._config.model_path),
                self._config.model_revision,
            )
        return self._model

    def _embed(
        self,
        texts: tuple[str, ...],
        *,
        prefix: str,
    ) -> np.ndarray:
        vectors = np.asarray(self._embedding_builder(
            self._load_model(),
            list(texts),
            prefix=prefix,
            batch_size=self._config.batch_size,
            show_progress_bar=False,
        ))
        if vectors.ndim != 2 or vectors.shape[0] != len(texts):
            raise ValueError("embedding builder returned an invalid shape")
        if not np.isfinite(vectors).all():
            raise ValueError("embedding builder returned a non-finite value")
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if np.any(norms == 0):
            raise ValueError("embedding builder returned a zero vector")
        return vectors / norms

    def prepare(
        self,
        query_texts: Iterable[str],
        passage_texts: Iterable[str],
    ) -> None:
        """Embed all cache misses in two CPU batches."""

        queries = tuple(sorted({
            str(value).strip()
            for value in query_texts
            if str(value).strip()
        } - set(self._query_vectors)))
        passages = tuple(sorted({
            str(value).strip()
            for value in passage_texts
            if str(value).strip()
        } - set(self._passage_vectors)))
        if queries:
            vectors = self._embed(queries, prefix="query: ")
            self._query_vectors.update(zip(queries, vectors, strict=True))
        if passages:
            vectors = self._embed(passages, prefix="passage: ")
            self._passage_vectors.update(zip(passages, vectors, strict=True))

    def __call__(self, query_text: str, passage_text: str) -> float:
        query = str(query_text).strip()
        passage = str(passage_text).strip()
        if not query or not passage:
            return 0.0
        self.prepare((query,), (passage,))
        cosine = float(np.dot(
            self._query_vectors[query],
            self._passage_vectors[passage],
        ))
        return round(max(0.0, min(1.0, (cosine + 1.0) / 2.0)), 6)

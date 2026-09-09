from pathlib import Path

import numpy as np
import pytest

from moongcheap_ai.demand_clustering.e5_runtime_scorer import (
    E5RuntimeScorerConfig,
    E5RuntimeTextSimilarityScorer,
)


def test_loads_config_from_environment() -> None:
    config = E5RuntimeScorerConfig.from_environment({
        "E5_MODEL_PATH": "/models/e5",
        "E5_MODEL_REVISION": " revision-1 ",
        "E5_BATCH_SIZE": "16",
    })

    assert config == E5RuntimeScorerConfig(
        Path("/models/e5"),
        "revision-1",
        16,
    )


def test_environment_requires_model_path() -> None:
    with pytest.raises(ValueError, match="E5_MODEL_PATH"):
        E5RuntimeScorerConfig.from_environment({})


def test_lazily_loads_model_and_batches_cache_misses() -> None:
    calls: list[object] = []

    def load_model(path: str, revision: str | None) -> object:
        calls.append(("load", path, revision))
        return object()

    def embed(
        model: object,
        texts: list[str],
        *,
        prefix: str,
        batch_size: int,
        show_progress_bar: bool,
    ) -> np.ndarray:
        calls.append(("embed", tuple(texts), prefix, batch_size))
        values = {
            "query: 딸기맛": (1.0, 0.0),
            "passage: 딸기맛 제품": (0.8, 0.6),
            "passage: 일반 제품": (0.0, 1.0),
        }
        return np.asarray([values[prefix + text] for text in texts])

    scorer = E5RuntimeTextSimilarityScorer(
        E5RuntimeScorerConfig(Path("/models/e5"), "revision-1", 16),
        model_loader=load_model,
        embedding_builder=embed,
    )
    assert scorer.model_loaded is False

    scorer.prepare(
        ["딸기맛", "딸기맛"],
        ["딸기맛 제품", "일반 제품"],
    )

    assert scorer.model_loaded is True
    assert scorer.cache_summary == {
        "modelLoaded": True,
        "queryCount": 1,
        "passageCount": 2,
    }
    assert scorer("딸기맛", "딸기맛 제품") == 0.9
    assert scorer("딸기맛", "일반 제품") == 0.5
    assert [call[0] for call in calls] == ["load", "embed", "embed"]


def test_empty_text_does_not_load_model() -> None:
    scorer = E5RuntimeTextSimilarityScorer(
        E5RuntimeScorerConfig(Path("/models/e5")),
        model_loader=lambda *args: pytest.fail("must not load"),
    )

    assert scorer("", "candidate") == 0.0
    assert scorer.model_loaded is False


def test_rejects_invalid_embedding_shape() -> None:
    scorer = E5RuntimeTextSimilarityScorer(
        E5RuntimeScorerConfig(Path("/models/e5")),
        model_loader=lambda *args: object(),
        embedding_builder=lambda *args, **kwargs: np.asarray([1.0, 0.0]),
    )

    with pytest.raises(ValueError, match="shape"):
        scorer.prepare(["query"], ["passage"])


def test_rejects_zero_embedding_vector() -> None:
    scorer = E5RuntimeTextSimilarityScorer(
        E5RuntimeScorerConfig(Path("/models/e5")),
        model_loader=lambda *args: object(),
        embedding_builder=lambda *args, **kwargs: np.asarray([[0.0, 0.0]]),
    )

    with pytest.raises(ValueError, match="zero vector"):
        scorer.prepare(["query"], [])

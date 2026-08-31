import pandas as pd

from moongcheap_ai.parts.aihub.model_benchmark import run_benchmark


def test_benchmark_returns_all_baselines() -> None:
    frame = pd.DataFrame(
        {
            "barcode": ["880000000001", "880000000001", "880000000002", "880000000002", "880000000003", "880000000003"],
            "product_name_normalized": ["사과 1kg", "사과 1 kg", "우유 900ml", "우유 900 ml", "칫솔 일반", "칫솔 일반"],
            "kan_code": ["A", "A", "A", "A", "B", "B"],
        }
    )
    metrics, report = run_benchmark(frame)
    assert set(metrics["model"]) == {"exact_normalized_name", "word_tfidf", "char_tfidf_2_4gram", "hybrid_word_char"}
    assert report["status"] == "COMPLETED"
    assert report["test_queries"] >= 1

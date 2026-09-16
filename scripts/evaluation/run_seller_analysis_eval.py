"""고정 평가셋으로 현재 구현을 채점한다.

구현은 `moongcheap_ai.seller_analysis.evaluation.runner` 에 있다.
이 파일은 진입점만 맡는다.

    python scripts/evaluation/run_seller_analysis_eval.py

「AI 평가 데이터셋 및 평가 지표 정의서」 21절 「Seller Analysis 목표 지표」 기준으로
판정하고, 결과를 `data/reports/seller_analysis_eval/<실행시각>/report.json` 에 남긴다.
"""

from __future__ import annotations

import sys
from pathlib import Path

# 저장소 관례. `pyproject.toml` 의 pythonpath 는 pytest 설정이라 일반 실행에는 적용되지
# 않는다. `scripts/evaluation/report_demand_labeling_metrics.py` 와 같은 방식이다.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from moongcheap_ai.seller_analysis.evaluation.runner import main

if __name__ == "__main__":
    sys.exit(main())

"""영역 2 고정 평가셋 100건을 생성한다.

구현은 `moongcheap_ai.seller_analysis.evaluation.eval_set` 에 있다.
이 파일은 진입점만 맡는다.

    python scripts/evaluation/build_seller_analysis_eval_set.py

⛔ 생성기는 `bid_guide` 를 부르지 않는다. 정답을 구현이 만들면 채점이 순환한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

# 저장소 관례. `pyproject.toml` 의 pythonpath 는 pytest 설정이라 일반 실행에는 적용되지
# 않는다. `scripts/evaluation/report_demand_labeling_metrics.py` 와 같은 방식이다.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from moongcheap_ai.seller_analysis.evaluation.eval_set import main

if __name__ == "__main__":
    main()

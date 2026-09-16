# 영역 2 오프라인 평가

「AI 평가 데이터셋 및 평가 지표 정의서」 의 **영역 2 — 판매자용 소비자 수요 분석** 평가다.

| 모듈 | 역할 |
|---|---|
| `eval_set` | 고정 평가셋 100건 생성. 17절 구성표를 따른다 |
| `runner` | 그 평가셋으로 현재 구현을 채점. 21절 목표 지표로 판정 |

⛔ **운영 경로(`api` · `bid_guide`)는 이 패키지를 부르지 않는다.**
`demand_clustering.evaluation` 과 같은 경계다.

⛔ **생성기는 구현을 부르지 않는다.** 정답을 구현이 만들면 채점이 순환한다.
16절이 적은 산식을 `eval_set` 에서 다시 세우고, 반올림이 필요한 비율은 아예 거절한다 —
그래야 정답이 반올림 정책에 기대지 않는다.

## 실행

```bash
python scripts/evaluation/build_seller_analysis_eval_set.py   # 평가셋 생성
python scripts/evaluation/run_seller_analysis_eval.py          # 채점
```

평가셋은 `data/evaluation/seller_analysis/` 에 고정해 둔다. 26절이
*"동일한 Version 의 Evaluation Dataset 을 사용한다"* 고 정하기 때문이다.
채점 결과는 재생성 가능하므로 `data/reports/` 에 남기고 저장소에 담지 않는다.

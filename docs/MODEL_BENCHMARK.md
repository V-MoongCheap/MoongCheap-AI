# AI-Hub 상품명 매칭 기준 모델

현재 패키지에는 다음 네 가지 경량 기준 모델이 있습니다.

- `exact_normalized_name`: 정규화 상품명 정확일치
- `word_tfidf`: 단어 TF-IDF 코사인 유사도
- `char_tfidf_2_4gram`: 문자 2~4 gram TF-IDF 코사인 유사도
- `hybrid_word_char`: 단어/문자 점수 50:50 혼합

실행:

```powershell
$env:PYTHONPATH = "src"
python scripts/evaluation/run_aihub_model_benchmark.py --max-rows 97910
```

결과는 `data/evaluation/matching/aihub_model_comparison.csv`와
`data/evaluation/matching/aihub_model_benchmark.json`에 저장됩니다.

평가 대상은 동일 바코드가 여러 번 관측된 AI-Hub 행이며, 같은 KAN 안에서 다른 바코드 행을 음성 후보로 사용합니다. 따라서 결과는 검증된 정답셋의 정확도가 아니라 **바코드 중복 기반 검색 프록시 평가**입니다. 현재 결과의 운영 후보는 정확일치 우선이며, 불일치 상품명에 문자 TF-IDF를 보조 점수로 사용할 수 있습니다. 한국어 의미 임베딩 모델은 별도 모델 패키지와 검증셋을 준비한 뒤 비교 대상으로 추가합니다.

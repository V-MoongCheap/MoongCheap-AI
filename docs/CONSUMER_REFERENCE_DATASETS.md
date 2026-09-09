# Consumer Reference Dataset 운영 기준

## 현재 확보 상태

- `data/datasets/esci`: 로컬에 이미 존재하는 Amazon ESCI 데이터. 검색어와 상품 관계의 표현 참고용이다.
- `data/raw/consumer_reference/xpqa`: Amazon Science 공식 저장소에서 받은 xPQA 원본. 한국어 질문 split이 포함되어 있으나 일반 상품 Q&A이므로 표현 참고용으로만 사용한다.
- `data/datasets/wands`: 로컬에 존재하지만 일반 상품 검색 데이터라 건강기능식품 수요 정답으로 사용하지 않는다.
- KuaiSearch: 전체 다운로드하지 않는다. 필요할 때 Lite 파일만 별도 검토 후 받는다.

## 프로젝트 데이터와의 연결

실제 건강기능식품 근거는 다음 로컬 산출물에서 가져온다.

1. MFDS I0030 상품 전처리 데이터
2. `service_category_tree_v2_1.csv`
3. `product_service_category_mapping_v2_1.csv`
4. 승인된 Facet taxonomy와 alias

Consumer reference 데이터의 문장은 위 근거와 매칭될 때만 synthetic demand seed로 승격한다. 매칭되지 않는 요구는 `UNRESOLVED` 또는 `OTHER_REQUIREMENT`로 보류하며 임의의 Facet을 만들지 않는다.

## 재현

```powershell
python scripts/collect/consumer_reference_inventory.py
python scripts/collect/consumer_reference_inventory.py --clone-xpqa
python scripts/demand/generate_grounded_demands.py --count 100
```

점검 결과는 `data/reports/consumer_reference/DATASET_STATUS.md`와 `dataset_inventory.json`에 생성된다. `data/raw/`와 `data/reports/`는 Git 제외 대상이다.

생성 결과는 `data/synthetic/consumer_reference/grounded_demand_v1.csv`에 저장된다. 이 파일은 실제 사용자 요청이 아니라 테스트용 Synthetic Demand이며, 생성 후 기존 Labeling을 실행해야 한다.

Labeling 결과를 클러스터링 입력으로 펼치려면 다음 명령을 실행한다.

```powershell
$env:PYTHONPATH="src"
python scripts/facet/build_facet_codebook.py
```

`data/processed/facet_codebook_v2_1/` 아래에 Category별 Codebook과 Facet별 숫자 코드 컬럼을 가진 `clustering_input_v2_1.csv`가 생성된다. 클러스터링 비교는 `facet_values` 또는 Facet 코드 컬럼을 사용하고, `facet_label`은 압축 키로 사용한다.

# B 이미지에 포함할 실행 자료

저장소를 checkout한 뒤 기존 Dockerfile을 빌드하면 이 자료와 E5가 이미지에 포함된다.
인프라 담당자가 CSV·모델을 선택하거나 PVC를 만들고 파일을 채울 필요는 없다.
모델·상품 자료의 선택과 갱신은 B 담당자가 관리하며 이미지 태그로 함께 배포한다.

| 파일 | 역할 |
| --- | --- |
| `catalog_profiles.csv.gz` | MFDS 상품 profile 45,996건의 결정적 gzip; 빌드 때 CSV로 복원 |
| `taxonomy.json` | 해당 profile과 함께 검증한 A V2.2 분류표 |
| `catalog.json` | release, 행 수, 압축/원본/분류표 SHA256, 생성 근거 |
| `model.json` | E5 저장소·고정 revision·다운로드할 파일별 SHA256 |

이미지 경로는 `/artifacts/catalog_profiles.csv`, `/artifacts/taxonomy.json`,
`/models/multilingual-e5-small`이다. `/artifacts/manifest.json`과 모델 디렉터리의
`image-model-manifest.json`으로 이미지 안에서도 버전·해시를 확인할 수 있다.
E5는 빌드 중에만 다운로드하며 모델 가중치를 Git에 넣지 않는다. 원재료·비밀 값·
로컬 Hugging Face cache는 빌드 입력에 포함하지 않는다.

현재 release는 `v2_2_20260921_image`다. 기존 생성기의 원재료와 최신 저장소 taxonomy로
재생성했으며 profile CSV 내용은 2026-09-11 release와 동일하다. `catalog_id`는
기존 MFDS source product ID를 보존한다. 이미지에 포함하는 변경은 Backend ID로
변환하는 작업이 아니며, 실제 DB 입력도 이 ID 계약과 일치해야 한다.

## 자료 갱신

[V2.2 연계 안내](../../../docs/PART_B_V22_INTEGRATION.md)의 생성기로 새 release를 만든다.
생성·의미 검증을 마친 뒤 저장소 루트에서 다음처럼 압축본과 manifest를 갱신한다.

```bash
python scripts/deployment/prepare_demand_clustering_assets.py pack \
  --release data/reports/b_profile_releases/<new-release> \
  --assets packaging/demand-clustering/runtime-assets
tools/verify_kubernetes_manifests.sh
docker build -f docker/Dockerfile.demand-clustering -t demand-clustering-job:local .
```

`catalog_profiles.csv.gz`, `taxonomy.json`, `catalog.json`을 함께 커밋한다.
빌드 단계는 압축본·복원 CSV·분류표의 해시, 버전, 카테고리, ID 중복과 행 수를 검사한다.
분류표를 변경할 때는 원본 `config/facet_taxonomy_v2_2.json`과 별칭도 함께 검증한다.
E5 변경은 `model.json`의 전체 revision과 파일별 SHA256을 갱신하고 컨테이너의 오프라인
임베딩 검증까지 수행한다. 런타임 다운로드나 PVC 공급 절차를 추가하지 않는다.

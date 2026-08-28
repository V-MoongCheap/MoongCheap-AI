# A 담당 Data / Facet Discovery V1

## Sources

- AI-Hub: 국내 상품 데이터. 로그인/신청/다운로드는 사용자가 직접 수행합니다.
- KAN: 공식 Codebook이 있으면 우선 사용하고, 없으면 AI-Hub에서 실제 관찰된 코드만 `observed_only=true`로 다룹니다.
- 식품안전나라 MFDS I0030/I2710: 건강기능식품 Product Fact와 Reference입니다.

Naver Shopping, GobizKorea, Open Icecat, K-FIND, Domeggook은 현재 방향에서 사용하지 않습니다.

## 실행

```powershell
Copy-Item .env.example .env
$env:MFDS_API_KEY = "..."
./run_data_pipeline.ps1
```

AI-Hub 원본은 다음 위치에 직접 넣습니다.

```text
data/raw/aihub/logistics_product/
data/raw/aihub/product_image/
data/raw/kan/                 # 선택: 공식 KAN 파일
data/raw/mfds/I0030/
data/raw/mfds/I2710/
```

AI-Hub 원본이 없으면 Catalog Stage는 `SKIPPED`입니다. MFDS API Key가 없으면 MFDS Stage는 실행하지 않습니다. 어느 경우에도 Mock 데이터로 성공을 위조하지 않습니다.

## 출력 원칙

- `raw`: 원본 보존, 수정 금지
- `interim`: 표준화·검사 중간 산출물
- `processed`: 검수 가능한 seed·catalog·Facet 초안
- `reports`: row count, null rate, conflict, coverage 및 skip 사유

상품명 숫자·용량·모델명·수량은 삭제하지 않습니다. Barcode는 문자열로 보존하고, 이름만 같은 상품은 자동 병합하지 않습니다. Facet Taxonomy는 Human Review 전 초안이며 Backend DB에 자동 반영하지 않습니다.

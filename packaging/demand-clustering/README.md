# B파트 개발·배포 패키징

수요 클러스터링 배치에 필요한 Python 버전, 의존성, lockfile과 빌드·검증 설정을
이 디렉터리에서 관리한다. 루트의 공통 `pyproject.toml`과 `requirements.txt`는
기존 Python 3.11 이상 설치 경로를 유지한다. B파트는 Python 3.12 이상이 필요하며,
컨테이너 검증 환경은 Python 3.13.12 / Linux amd64다.

## 설치와 검증

다음 명령은 **저장소 루트**에서 실행한다. 기본 가상환경은
`packaging/demand-clustering/.venv`이며, `UV_PROJECT_ENVIRONMENT`로 변경할 수 있다.

```bash
uv sync --project packaging/demand-clustering --locked --extra data --extra dev
uv run --project packaging/demand-clustering --no-sync pytest -c packaging/demand-clustering/pyproject.toml
tools/verify_kubernetes_manifests.sh
```

`data`와 `dev`는 공통 데이터 테스트와 B파트 테스트에 필요한 의존성을 함께
설치한다. 공통 `requirements.txt`만으로 B파트 전체 테스트 의존성이 설치되지는
않는다. Kubernetes 검증에는 `kubectl`도 필요하며 클러스터에는 접속하지 않는다.

CPU E5를 로컬에서 실행하려면 같은 설치 명령에 `--extra embeddings`를 추가한다.
PyTorch는 CPU 전용 index에서 설치하며 모델 파일은 별도로 준비한다.

```bash
uv sync --project packaging/demand-clustering --locked --extra data --extra dev --extra embeddings
uv run --project packaging/demand-clustering --no-sync demand-clustering-batch --help
```

Ruff 검사는 B파트 설정과 검사할 경로를 명시한다.

```bash
uv run --project packaging/demand-clustering --no-sync ruff check --config packaging/demand-clustering/pyproject.toml src/moongcheap_ai/demand_clustering
```

## 소스와 이미지 빌드

패키지는 저장소의 `src/moongcheap_ai`를 사용한다. 이 디렉터리만 복사하지 말고
소스를 포함한 저장소에서 빌드한다. 로컬 editable 설치도 같은 소스를 참조한다.
Dockerfile은 이 프로젝트의 lockfile로 의존성을 설치하고 non-editable 패키지를
빌드한다. 프로젝트 밖의 소스 변경도 반영하도록 `uv sync`마다 앱 패키지를 다시
빌드하며, 외부 의존성 캐시는 재사용한다. Dockerfile 전용 ignore로 빌드 입력을 정한다.

```bash
docker build -f docker/Dockerfile.demand-clustering -t demand-clustering-job:local .
```

실행 계약과 마운트 설정은 [컨테이너 안내](../../docs/DEMAND_CLUSTERING_CONTAINER.md),
인프라 전달 값은 [B파트 인계서](../../docs/ci-cd-demand-clustering-handoff.yml)를 참고한다.

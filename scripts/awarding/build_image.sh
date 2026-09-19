#!/usr/bin/env bash
# 저장소 루트 전체 대신 명시한 파일만 Docker에 보낸다. BuildKit 유무와 무관하다.
set -euo pipefail
cd -- "$(dirname -- "$0")/../.."
image_tag="${1:-moongcheap/ai-awarding:local}"
target_platform="${2:-linux/amd64}"
files=(
  docker/Dockerfile.awarding
  packaging/awarding/requirements.txt
  src/moongcheap_ai/__init__.py
  src/moongcheap_ai/seller_matching/__init__.py
  src/moongcheap_ai/seller_matching/offer_ranking.py
  src/moongcheap_ai/seller_matching/awarding_batch.py
  scripts/awarding/run_awarding_test_drive.py
  scripts/awarding/mock_backend.py
  scripts/awarding/container_smoke.py
  scripts/awarding/sample_pending.json
)
for path in "${files[@]}"; do
  if [[ ! -f "$path" || -L "$path" ]]; then
    printf 'Missing regular build input: %s\n' "$path" >&2
    exit 1
  fi
done
# 허용된 파일만 담는다. 로컬 키/원천 데이터는 컨텍스트에 보내지 않는다.
COPYFILE_DISABLE=1 tar --no-xattrs --no-acls -czf - "${files[@]}" |
  DOCKER_BUILDKIT="${DOCKER_BUILDKIT:-0}" docker build \
    --platform "$target_platform" -f docker/Dockerfile.awarding -t "$image_tag" -

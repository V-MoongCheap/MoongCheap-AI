#!/usr/bin/env bash
set -euo pipefail

if ! command -v kubectl >/dev/null 2>&1; then
    echo "kubectl is required for offline Kustomize validation." >&2
    exit 1
fi

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$repository_root"
uv run --project packaging/demand-clustering --no-sync \
  pytest -c packaging/demand-clustering/pyproject.toml -q tests/deployment

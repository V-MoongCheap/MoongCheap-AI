#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
WITH_MODEL1_HF="${WITH_MODEL1_HF:-0}"

if [ ! -x ".venv/bin/python" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt

if [ "$WITH_MODEL1_HF" = "1" ]; then
  .venv/bin/python -m pip install -r requirements-model1-hf.txt
fi

.venv/bin/python -m pip check
echo "Environment ready. Activate with: source .venv/bin/activate"

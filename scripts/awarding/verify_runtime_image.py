"""Check actual runtime files; pipe this script to Python inside the image.

This script is deliberately not copied into the deployment image.
No network calls, writes, or application imports are performed.
"""
from __future__ import annotations

import json
from pathlib import Path

REQUIRED = (
    "src/moongcheap_ai/seller_matching/awarding_batch.py",
    "src/moongcheap_ai/seller_matching/offer_ranking.py",
    "scripts/awarding/run_awarding_test_drive.py",
    "scripts/awarding/sample_pending.json",
)
FORBIDDEN = frozenset({"mock_backend.py", "container_smoke.py"})


def verify(root: Path) -> dict:
    missing = [name for name in REQUIRED if not (root / name).is_file()]
    leaked = sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.name in FORBIDDEN)
    if missing or leaked:
        raise RuntimeError(f"runtime image boundary failed: missing={missing}, forbidden={leaked}")
    return {"status": "PASS", "scope": "runtime file boundary", "requiredFiles": len(REQUIRED)}


if __name__ == "__main__":
    print(json.dumps(verify(Path("/app"))))

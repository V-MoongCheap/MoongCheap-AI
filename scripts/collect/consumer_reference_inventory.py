"""Inspect and optionally acquire approved consumer-reference datasets.

Raw files are intentionally stored below data/raw, which is ignored by Git.
The script never downloads AI-Hub data or the full KuaiSearch corpus.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = ROOT / "data" / "raw" / "consumer_reference"
REPORT_ROOT = ROOT / "data" / "reports" / "consumer_reference"
XPQA_URL = "https://github.com/amazon-science/contextual-product-qa.git"

SOURCES = {
    "esci": {
        "local_path": "data/datasets/esci",
        "source_type": "SEARCH",
        "license": "Amazon dataset terms; see local LICENSE/NOTICE",
        "role": "expression_reference_only",
        "status_if_present": "available_local",
    },
    "wands": {
        "local_path": "data/datasets/wands",
        "source_type": "SEARCH",
        "license": "See local LICENSE",
        "role": "expression_reference_only",
        "status_if_present": "available_local_non_health",
    },
    "xpqa": {
        "local_path": "data/raw/consumer_reference/xpqa",
        "source_type": "QA",
        "license": "CDLA-Sharing-1.0; see raw repository LICENSE",
        "role": "expression_reference_only",
        "status_if_present": "available_local",
        "source_url": XPQA_URL,
    },
    "kuaisearch": {
        "local_path": "data/raw/consumer_reference/kuaisearch",
        "source_type": "SEARCH",
        "license": "MIT; verify dataset card before redistribution",
        "role": "not_acquired",
        "status_if_present": "available_local_unreviewed",
        "source_url": "https://huggingface.co/datasets/benchen4395/KuaiSearch",
        "note": "Full corpus is too large for an implicit download. Acquire only Lite files after review.",
    },
}


def _file_count(path: Path) -> int:
    return sum(1 for item in path.rglob("*") if item.is_file() and ".git" not in item.parts)


def collect_inventory() -> dict:
    records = []
    for name, metadata in SOURCES.items():
        path = ROOT / metadata["local_path"]
        exists = path.exists()
        record = {
            "dataset": name,
            **metadata,
            "exists": exists,
            "file_count": _file_count(path) if exists else 0,
        }
        records.append(record)
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "raw_policy": "Raw/licensed files stay local and are never committed.",
        "aihub_policy": "AI-Hub path from external instructions is ignored; use local data only.",
        "datasets": records,
    }


def write_report(inventory: dict) -> tuple[Path, Path]:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_ROOT / "dataset_inventory.json"
    md_path = REPORT_ROOT / "DATASET_STATUS.md"
    json_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Consumer Reference 데이터 상태",
        "",
        "외부 지시문의 AI-Hub 경로는 사용하지 않고, 프로젝트 로컬 `data/`만 기준으로 점검했다.",
        "원본·라이선스 데이터는 `data/raw/`에 두며 Git에 커밋하지 않는다.",
        "",
        "| Dataset | 상태 | 유형 | 역할 | 로컬 경로 | 파일 수 |",
        "|---|---|---|---|---|---:|",
    ]
    for item in inventory["datasets"]:
        status = item["status_if_present"] if item["exists"] else "not_available"
        lines.append(
            f"| {item['dataset']} | {status} | {item['source_type']} | "
            f"{item['role']} | `{item['local_path']}` | {item['file_count']} |"
        )
    lines += [
        "",
        "## 사용 제한",
        "",
        "- ESCI, WANDS, xPQA는 건강기능식품 수요의 정답이나 Facet 근거로 사용하지 않는다.",
        "- 이 데이터들은 자연어 표현과 질문 형식 참고용이다. 최종 요구사항은 로컬 MFDS 상품·Category·Facet taxonomy에 근거해야 한다.",
        "- 의료 진단·치료·개인 건강정보 표현은 생성 입력에서 제외하거나 `REVIEW`로 보류한다.",
        "- KuaiSearch 전체 다운로드는 수행하지 않았다. 필요 시 Lite 파일만 별도 라이선스 검토 후 받는다.",
        "",
        "## 재현 명령",
        "",
        "```powershell",
        "python scripts/collect/consumer_reference_inventory.py",
        "python scripts/collect/consumer_reference_inventory.py --clone-xpqa",
        "```",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def clone_xpqa() -> None:
    target = RAW_ROOT / "xpqa"
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--depth", "1", XPQA_URL, str(target)], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clone-xpqa", action="store_true", help="Clone the official xPQA repository if absent")
    args = parser.parse_args()
    if args.clone_xpqa:
        clone_xpqa()
    json_path, md_path = write_report(collect_inventory())
    print(json.dumps({"inventory": str(json_path), "report": str(md_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

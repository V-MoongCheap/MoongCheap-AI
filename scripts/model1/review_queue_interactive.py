"""Review Model 1 candidates one row at a time and save a resumable CSV.

The input queue is never modified.  Each decision is written immediately to a
separate output CSV so the review can be interrupted and resumed safely.
"""

from __future__ import annotations

import argparse
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


DECISION_COLUMNS = {
    "human_decision": "",
    "human_value": "",
    "human_corrected_facet": "",
    "human_note": "",
    "reviewed_at": "",
}


def _value(row: pd.Series, *names: str) -> str:
    for name in names:
        value = str(row.get(name, "") or "").strip()
        if value:
            return value
    return ""


def _preview(value: str, width: int = 100, limit: int = 500) -> str:
    value = str(value or "").strip()
    if len(value) > limit:
        value = value[:limit] + "..."
    return "\n".join(textwrap.wrap(value, width=width)) or "(없음)"


def display_row(row: pd.Series, position: int, total: int) -> None:
    print("\n" + "=" * 100)
    print(f"[{position}/{total}] {_value(row, 'review_id', 'case_id')}")
    print(f"카테고리: {_value(row, 'category_name', 'category_key', 'category_id')}")
    print(f"Facet 후보: {_value(row, 'facet_name', 'facet_candidate', 'facet_id')}")
    print(f"Value 후보: {_value(row, 'facet_value', 'value_candidate', 'value')}")
    print(f"모델: {_value(row, 'model')}")
    print(f"검수 상태: {_value(row, 'review_status', 'reviewer_status')}")
    print(f"검수 사유: {_preview(_value(row, 'review_reason', 'review_reasons'))}")
    print(f"모델 설명: {_preview(_value(row, 'model_reason', 'selection_reason'))}")
    print(f"관찰 근거: {_preview(_value(row, 'observed_data_reason', 'value_reason'))}")
    print(f"근거 상품/문서: {_preview(_value(row, 'source_product_ids', 'source_document_id'), limit=300)}")
    current = _value(row, "human_decision") or "미검수"
    print(f"현재 결정: {current}")
    print("\n[a] 승인  [e] 수정  [r] 반려  [u] 보류  [s] 건너뛰기  [q] 저장 후 종료")


def _ensure_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column, default in DECISION_COLUMNS.items():
        if column not in result.columns:
            result[column] = default
    return result


def apply_decision(
    frame: pd.DataFrame,
    index: int,
    decision: str,
    *,
    value: str = "",
    facet: str = "",
    note: str = "",
    reviewed_at: str = "reviewed",
) -> pd.DataFrame:
    """Apply one normalized decision without prompting; useful for tests."""

    result = _ensure_columns(frame)
    if decision not in {"APPROVE", "EDIT", "REJECT", "UNCERTAIN"}:
        raise ValueError(f"unsupported decision: {decision}")
    result.at[index, "human_decision"] = decision
    result.at[index, "human_value"] = value.strip()
    result.at[index, "human_corrected_facet"] = facet.strip()
    result.at[index, "human_note"] = note.strip()
    result.at[index, "reviewed_at"] = reviewed_at
    return result


def save(frame: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False, encoding="utf-8-sig")


def _ask_edit(row: pd.Series) -> tuple[str, str, str]:
    old_facet = _value(row, "facet_name", "facet_candidate", "facet_id")
    old_value = _value(row, "facet_value", "value_candidate", "value")
    facet = input(f"수정할 Facet [{old_facet}]: ").strip() or old_facet
    value = input(f"수정할 Value [{old_value}]: ").strip()
    note = input("수정 사유: ").strip()
    if not value:
        raise ValueError("수정 시 Value는 비워둘 수 없습니다.")
    return facet, value, note


def review_queue(queue: pd.DataFrame, output: Path, *, include_reviewed: bool = False) -> pd.DataFrame:
    frame = _ensure_columns(queue)
    pending = [
        index
        for index in frame.index
        if include_reviewed or not str(frame.at[index, "human_decision"]).strip()
    ]
    cursor = 0
    while cursor < len(pending):
        index = pending[cursor]
        display_row(frame.loc[index], cursor + 1, len(pending))
        command = input("선택: ").strip().lower()
        if command == "q":
            save(frame, output)
            print(f"저장 완료: {output}")
            return frame
        if command == "s":
            cursor += 1
            continue
        if command not in {"a", "e", "r", "u"}:
            print("a/e/r/u/s/q 중 하나를 입력하세요.")
            continue

        now = datetime.now(timezone.utc).isoformat()
        if command == "a":
            decision = "APPROVE"
            value = _value(frame.loc[index], "facet_value", "value_candidate", "value")
            facet = _value(frame.loc[index], "facet_name", "facet_candidate", "facet_id")
            note = input("메모(없으면 Enter): ").strip()
        elif command == "e":
            try:
                facet, value, note = _ask_edit(frame.loc[index])
            except ValueError as exc:
                print(exc)
                continue
            decision = "EDIT"
        elif command == "r":
            decision = "REJECT"
            value = ""
            facet = ""
            note = input("반려 사유: ").strip()
            if not note:
                print("반려 사유를 입력하세요.")
                continue
        else:
            decision = "UNCERTAIN"
            value = ""
            facet = ""
            note = input("보류 사유(없으면 Enter): ").strip()
        frame = apply_decision(
            frame,
            index,
            decision,
            value=value,
            facet=facet,
            note=note,
            reviewed_at=now,
        )
        save(frame, output)
        cursor += 1
    save(frame, output)
    print(f"전체 검수 완료 및 저장: {output}")
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description="Model 1 Facet 후보 대화형 검수")
    parser.add_argument("--queue", type=Path, required=True, help="원본 review queue CSV")
    parser.add_argument("--output", type=Path, required=True, help="검수 결과 CSV")
    parser.add_argument("--include-reviewed", action="store_true", help="기존 결정 행도 다시 표시")
    parser.add_argument("--restart", action="store_true", help="기존 결과를 무시하고 원본 queue에서 다시 시작")
    args = parser.parse_args()
    source = args.queue
    if args.output.exists() and not args.restart:
        source = args.output
        print(f"기존 검수 결과에서 재개: {source}")
    queue = pd.read_csv(source, dtype=str, encoding="utf-8-sig").fillna("")
    review_queue(queue, args.output, include_reviewed=args.include_reviewed)


if __name__ == "__main__":
    main()

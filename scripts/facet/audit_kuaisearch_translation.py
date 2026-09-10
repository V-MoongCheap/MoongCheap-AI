"""Reproducible screening, not gold labels or translation accuracy scoring."""

import argparse
import hashlib
import json
import re
from pathlib import Path

import pandas as pd


DOMAIN_PATTERNS = {
    "PET": r"猫粮|狗粮|犬粮|宠物|鸽药|猫砂|鱼缸",
    "COSMETIC_DEVICE": r"美瞳|面膜|口红|指甲油|避孕套|口罩",
    "MEDICINE": r"处方|特效药|他达拉非|西地那非|塞来昔布",
    "OTHER": r"穿搭|手机壳|烟草|莫合烟",
}
SUPPLEMENT = r"维生素|益生菌|鱼油|蛋白粉|胶原蛋白|钙片|褪黑素|膳食纤维|辅酶"


def numeric_tokens(value):
    normalized = str(value).translate(str.maketrans("零〇一二三四五六七八九", "00123456789"))
    return {str(int(token)) for token in re.findall(r"\d+", normalized)}


def screen(raw, translated):
    flags = []
    if not translated.strip():
        flags.append("EMPTY")
    elif not re.search(r"[\w]", translated):
        flags.append("PLACEHOLDER")
    if re.search(r"[\u4e00-\u9fff]", translated):
        flags.append("CJK_REMAINS")
    if raw.strip() == translated.strip():
        flags.append("UNCHANGED")
    if not re.search(r"[가-힣]", translated):
        flags.append("NO_HANGUL")
    if re.search(r"</?think>|Okay,|Let's|let's", translated):
        flags.append("EXPLANATION")
    raw_digits = set(re.findall(r"\d+", raw))
    translated_digits = set(re.findall(r"\d+", translated))
    if raw_digits - translated_digits:
        # Chinese digit words can be mixed with Arabic digits, e.g. 四00三.
        # Use the normalized comparison only for that mixed-number case.
        mixed_number_ok = bool(re.search(r"[零〇一二三四五六七八九].*\d|\d.*[零〇一二三四五六七八九]", raw)) and numeric_tokens(raw).issubset(numeric_tokens(translated))
        if not mixed_number_ok:
            flags.append("NUMBER_MISSING")
    domains = [key for key, pattern in DOMAIN_PATTERNS.items() if re.search(pattern, raw)]
    supplement = bool(re.search(SUPPLEMENT, raw))
    scope = "MIXED_REVIEW" if domains and supplement else "OUT_OF_SCOPE_CANDIDATE" if domains else "SUPPLEMENT_CANDIDATE" if supplement else "UNKNOWN_REVIEW"
    return "|".join(flags), scope, "|".join(domains)


def is_source_nontranslatable(raw):
    value = str(raw).strip()
    return bool(value) and not re.search(r"[\u4e00-\u9fff]", value) and not re.search(r"[\uac00-\ud7a3]", value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/interim/facet_evidence/kuaiseach_health_queries_ko.parquet"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/kuaisearch_translation_audit_v1"))
    args = parser.parse_args()
    frame = pd.read_parquet(args.input).fillna("")
    results = []
    for row in frame.itertuples():
        flags, scope, evidence = screen(str(row.query_raw), str(row.query_translated))
        if is_source_nontranslatable(row.query_raw):
            flags = "|".join(flag for flag in flags.split("|") if flag not in {"NO_HANGUL", "UNCHANGED", "PLACEHOLDER"})
        results.append((flags, scope, evidence))
    frame[["translation_flags", "scope_candidate", "scope_evidence"]] = pd.DataFrame(results, index=frame.index)
    args.output.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output / "query_audit_v1.csv", index=False, encoding="utf-8-sig")
    review = frame[frame.translation_flags.ne("") | frame.scope_candidate.ne("SUPPLEMENT_CANDIDATE")]
    review.to_csv(args.output / "review_queue_v1.csv", index=False, encoding="utf-8-sig")
    frame.sample(min(100, len(frame)), random_state=42).to_csv(args.output / "random_sample_100_v1.csv", index=False, encoding="utf-8-sig")
    flags = frame.translation_flags.str.split("|").explode()
    report = {"audit_version": "v1", "source": "KuaiSearch Lite, local Korean translation layer", "input": str(args.input), "input_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(), "rows": len(frame), "nonempty": int(frame.query_translated.str.strip().ne("").sum()), "flagged_translation_rows": int(frame.translation_flags.ne("").sum()), "translation_flags": flags[flags.ne("")].value_counts().to_dict(), "scope_candidates": frame.scope_candidate.value_counts().to_dict(), "behavior": frame.behavior_evidence.value_counts().to_dict(), "review_rows": len(review), "sampling_seed": 42, "accuracy": None}
    (args.output / "audit_summary_v1.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# KuaiSearch 번역·도메인 점검 V1", "", "원본 및 번역 데이터는 변경하지 않았습니다. 이 보고서는 규칙 기반 검토 후보이며 정답 라벨이 아닙니다.", "", "## 전수 집계", "", f"- 전체: {len(frame):,}건", f"- 번역 검토 신호: {report['flagged_translation_rows']:,}건", "- 번역 정확도: 미측정. 검토 신호가 없다고 정확한 번역은 아닙니다.", "- 한자 잔존과 숫자 누락은 브랜드 표기 등에서도 발생할 수 있습니다.", ""]
    for key in ("translation_flags", "scope_candidates", "behavior"):
        lines.extend([f"## {key}", "", *[f"- {name}: {count:,}" for name, count in report[key].items()], ""])
    lines.extend(["## 선별 원인과 적용 조건", "", "build_kuaisearch는 건강 키워드에 매칭된 상품과 구매·클릭·노출 이력이 연결되면 검색어를 포함합니다. 노출은 검색어 자체가 건강기능식품이라는 근거가 아닙니다.", "상품 제목과 카테고리에 대한 넓은 키워드 검색도 혼입 원인이 될 수 있습니다. 추가로 건강 키워드만 맞고 연결 상품이 없는 행에도 IMRESSION 계열 상태를 부여하는 코드를 확인했습니다.", "SUPPLEMENT_CANDIDATE는 원문 키워드 후보일 뿐 국내 규제상 건강기능식품 판정이 아닙니다. UNKNOWN_REVIEW를 자동 제외하지 않습니다.", "번역문과 중국어 상품 제목을 합쳐 파셋을 추출하므로 상품 속성이 사용자의 요구로 해석되지 않도록 출처 분리가 필요합니다.", "", "## 표본에서 확인한 오역", "", "| 원문 | 저장된 번역 | 검토 근거 |", "|---|---|---|", "| 菠萝圈软糖 | 바나나 소프트 글루 | 菠萝는 파인애플, 软糖는 젤리류 |", "| 宝宝米饼6个月以上 | 아이 밀가루 6개월 이상 | 米饼는 쌀과자이며 밀가루로 바뀜 |", "| 防晒口罩 | 방향제 마스크 | 防晒는 자외선 차단 |", "| 明月鸽药 | 명월 고양이 약 | 鸽는 비둘기이며 동물 종류가 바뀜 |", "", "위 표본은 오류 설명용이며 전체 정확도 추정에 사용하지 않습니다. random_sample_100_v1.csv는 추가 검토용으로 추출했으며 100건 전체 검토를 완료했다는 의미가 아닙니다.", ""])
    (args.output / "audit_report_v1.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()

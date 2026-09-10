"""Build review-expression candidates from the public Naver shopping corpus.

The corpus is an expression reference only. It is never treated as HFF review
evidence, and candidates remain pending human review.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

import pandas as pd


FACET_SEEDS = {
    "ingredient_inclusion": ["성분", "원료", "함량", "영양"],
    "intake_convenience": ["먹기 편", "복용하기 편", "간편하게 먹", "챙겨 먹"],
    "odor": ["비린내", "냄새", "향"],
    "packaging": ["개별 포장", "한 포씩", "스틱 포장", "포장"],
    "product_form": ["캡슐", "알약", "정제", "액상", "분말", "가루"],
    "swallowability": ["목넘김", "삼키기", "넘기기"],
    "tablet_size": ["알이 작", "알이 크", "작은 알", "큰 알", "사이즈"],
    "taste": ["쓴맛", "단맛", "뒷맛", "맛"],
}

# These are expression patterns, not HFF labels. They are intentionally
# conservative so a reviewer can see the exact sentence that produced them.
CANDIDATE_PATTERNS = {
    "ingredient_inclusion": ["성분이 좋", "원료가 좋", "함량이 높", "영양성분"],
    "intake_convenience": ["먹기 편", "복용하기 편", "간편하게 먹", "챙겨 먹기", "간편히"],
    "odor": ["비린내", "냄새가 나", "냄새가 없", "냄새가 안", "향이"],
    "packaging": ["개별 포장", "한 포씩", "스틱 포장", "포장이", "포장도"],
    "product_form": ["캡슐", "알약", "정제", "액상", "분말", "가루"],
    "swallowability": ["목넘김", "삼키기", "넘기기"],
    "tablet_size": ["알이 작", "알이 크", "작은 알", "큰 알", "사이즈가"],
    "taste": ["쓴맛", "단맛", "뒷맛", "맛이", "맛은"],
}

MEDICAL_EXPRESSION = re.compile(r"효과|효능|치료|개선|완화|질환|증상|혈압|혈당|콜레스테롤|면역|관절|간건강|눈건강")
UNRELATED_CONTEXT = re.compile(r"옷|신발|의자|가구|휴대폰|노트북|노트북|게임|자동차|강아지|고양이|화장품|립|샴푸|마스크|충전|이어폰")


def _similarity(seed: str, candidate: str) -> float:
    seed_chars = set(seed.replace(" ", ""))
    candidate_chars = set(candidate.replace(" ", ""))
    if not seed_chars or not candidate_chars:
        return 0.0
    return round(len(seed_chars & candidate_chars) / len(seed_chars | candidate_chars), 3)


def _sentence_context(text: str, phrase: str, width: int = 100) -> str:
    index = text.find(phrase)
    if index < 0:
        return text[: width * 2]
    start = max(0, index - width)
    end = min(len(text), index + len(phrase) + width)
    return text[start:end].strip()


def _load_corpus(path: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    frame = pd.read_csv(path, sep="\t", header=None, names=["rating", "review_text"], encoding="utf-8", dtype=str, keep_default_na=False)
    text = frame["review_text"].astype(str)
    audit = {
        "filename": path.name,
        "file_size_bytes": path.stat().st_size,
        "sha256": sha256,
        "encoding": "utf-8",
        "delimiter": "tab",
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "columns": list(frame.columns),
        "rating_values": sorted(frame["rating"].unique().tolist()),
        "null_rating": int(frame["rating"].eq("").sum()),
        "null_review_text": int(text.eq("").sum()),
        "duplicate_rows": int(frame.duplicated().sum()),
        "duplicate_review_text": int(text.duplicated().sum()),
        "review_length_chars": {
            "min": int(text.str.len().min()),
            "median": float(text.str.len().median()),
            "max": int(text.str.len().max()),
        },
    }
    return frame, audit


def _supported_facets(queue_path: Path) -> list[tuple[str, str]]:
    queue = pd.read_csv(queue_path, dtype=str).fillna("")
    count = pd.to_numeric(queue.get("review_source_count", 0), errors="coerce").fillna(0)
    selected = queue[count.gt(0)][["facet_candidate", "value_candidate"]].drop_duplicates()
    return [(str(row.facet_candidate), str(row.value_candidate)) for row in selected.itertuples()]


def build_candidates(corpus: pd.DataFrame, supported: list[tuple[str, str]]) -> tuple[pd.DataFrame, dict[str, dict[str, int]]]:
    rows: list[dict[str, object]] = []
    summary: dict[str, dict[str, int]] = {}
    for facet_id, value_candidate in supported:
        seeds = FACET_SEEDS.get(facet_id, [facet_id])
        patterns = CANDIDATE_PATTERNS.get(facet_id, seeds)
        facet_rows: dict[str, dict[str, object]] = {}
        relevant_sentences = 0
        for item in corpus.itertuples(index=False):
            text = str(item.review_text).strip()
            if not text or MEDICAL_EXPRESSION.search(text) or UNRELATED_CONTEXT.search(text):
                continue
            matched_seeds = [seed for seed in seeds if seed in text]
            if not matched_seeds:
                continue
            relevant_sentences += 1
            for phrase in patterns:
                if phrase not in text:
                    continue
                key = phrase
                if key not in facet_rows:
                    facet_rows[key] = {
                        "facet_id": facet_id,
                        "seed_expression": matched_seeds[0],
                        "candidate_expression": phrase,
                        "example_sentence": _sentence_context(text, phrase),
                        "occurrence_count": 0,
                        "semantic_similarity": _similarity(matched_seeds[0], phrase),
                        "proposed_alias": "",
                        "reviewer_decision": "PENDING_REVIEW",
                    }
                facet_rows[key]["occurrence_count"] = int(facet_rows[key]["occurrence_count"]) + 1
        for row in facet_rows.values():
            row["value_candidate"] = value_candidate
            rows.append(row)
        summary[f"{facet_id}:{value_candidate}"] = {
            "seed_expression_count": len(seeds),
            "candidate_alias_count": len(facet_rows),
            "related_sentence_count": relevant_sentences,
            "review_queue_count": len(facet_rows),
        }
    columns = ["facet_id", "value_candidate", "seed_expression", "candidate_expression", "example_sentence", "occurrence_count", "semantic_similarity", "proposed_alias", "reviewer_decision"]
    return pd.DataFrame(rows, columns=columns), summary


def build_report(audit: dict[str, object], summary: dict[str, dict[str, int]], output: Path, raw_path: Path) -> None:
    lines = [
        "# Naver Shopping Expression Reference",
        "",
        "이 자료는 한국 쇼핑 리뷰 표현과 Alias 후보를 탐색하기 위한 참고 데이터다. 건강기능식품 리뷰로 분류하지 않으며 HFF Facet Consumer Salience Count에 포함하지 않는다.",
        "",
        "## Raw Audit",
        f"- source_type: `KOREAN_SHOPPING_REVIEW_EXPRESSION_REFERENCE`",
        f"- raw_path: `{raw_path}`",
        f"- row_count: {audit['row_count']}",
        f"- columns: `{audit['columns']}`",
        f"- encoding: `{audit['encoding']}` / delimiter: `{audit['delimiter']}`",
        f"- rating_values: `{audit['rating_values']}`",
        f"- duplicate_rows: {audit['duplicate_rows']}",
        f"- duplicate_review_text: {audit['duplicate_review_text']}",
        f"- null_rating: {audit['null_rating']}",
        f"- null_review_text: {audit['null_review_text']}",
        f"- review_length_chars: `{audit['review_length_chars']}`",
        f"- sha256: `{audit['sha256']}`",
        "",
        "## Interpretation Rules",
        "- Nutrime의 Review-supported Facet seed에서 관련 문장을 먼저 검색했다.",
        "- 검색된 문장에서 보수적인 표현 패턴을 추출했으며 단순 전체 빈도 순위로 Alias를 만들지 않았다.",
        "- 의료 효능 표현과 명백한 무관 상품 문맥은 후보에서 제외했다.",
        "- `proposed_alias`는 비워 두고 `reviewer_decision=PENDING_REVIEW`로 유지했다.",
        "- 기존 Facet Taxonomy에는 자동 반영하지 않았다.",
        "",
        "## Facet Summary",
        "| facet_id:value | seed expressions | candidate aliases | related sentences | review queue |",
        "|---|---:|---:|---:|---:|",
    ]
    for key, values in summary.items():
        lines.append(f"| {key} | {values['seed_expression_count']} | {values['candidate_alias_count']} | {values['related_sentence_count']} | {values['review_queue_count']} |")
    lines += [
        "",
        "## Limitations",
        "- 원본에는 Product ID, Product Name, Category, Brand, Review Date가 없으므로 HFF 여부나 상품별 대표성을 판단할 수 없다.",
        "- 표현 후보는 사람이 검수하기 전까지 Alias가 아니다.",
        "- Naver Corpus에서의 출현 빈도는 건강기능식품 소비자 중요도의 근거가 아니다.",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--review-queue", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/processed/expression_reference/naver_shopping_facet_alias_candidates.csv"))
    parser.add_argument("--report", type=Path, default=Path("reports/naver_shopping_expression_reference.md"))
    args = parser.parse_args()
    corpus, audit = _load_corpus(args.input)
    supported = _supported_facets(args.review_queue)
    candidates, summary = build_candidates(corpus, supported)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(args.output, index=False, encoding="utf-8-sig")
    build_report(audit, summary, args.report, args.input)
    print({"status": "COMPLETED", "rows": audit["row_count"], "usable_rows": int(corpus.review_text.astype(str).str.strip().ne("").sum()), "supported_facet_count": len(supported), "candidate_count": len(candidates), "output": str(args.output), "report": str(args.report)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from pathlib import Path

from scripts.reviews.build_hff_review_source_report import SOURCES, build_report
from scripts.reviews.pilot_nutrime_reviews import run_pilot
from scripts.reviews.pilot_chongkundang_reviews import run_pilot as run_chongkundang_pilot


def test_source_preflight_has_at_least_ten_candidates() -> None:
    assert len(SOURCES) >= 10
    assert all(row["decision"] == "GREEN" or row["decision"].startswith("BLOCKED") for row in SOURCES)


def test_blocked_esther_is_not_pilotable() -> None:
    esther = next(row for row in SOURCES if row["source"] == "esthermall")
    assert esther["decision"] == "BLOCKED_AUTOMATION_TERMS"
    assert esther["pilot_possible"] == "NO"


def test_report_contains_required_fields(tmp_path: Path) -> None:
    output = tmp_path / "sources.md"
    build_report(output)
    text = output.read_text(encoding="utf-8")
    for field in ("source", "review_exists", "robots_status", "terms_status", "pilot_possible", "decision"):
        assert field in text


def test_pilot_limit_is_optional_and_positive(tmp_path: Path) -> None:
    try:
        run_pilot(tmp_path / "reviews.jsonl", limit=0)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("pilot must reject non-positive limits")


def test_chongkundang_pilot_limit_is_capped_at_one_hundred(tmp_path: Path) -> None:
    try:
        run_chongkundang_pilot(tmp_path / "reviews.jsonl", limit=101)
    except ValueError as exc:
        assert "between 1 and 100" in str(exc)
    else:
        raise AssertionError("chongkundang pilot must reject limits above 100")

"""Jenkinsfile change detection for the C (awarding · seller analysis) images.

Reads the change-detection closures in the repository Jenkinsfile and evaluates
them in Python. Never contacts Jenkins.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JENKINSFILE = (ROOT / "Jenkinsfile").read_text(encoding="utf-8")


def _detection_rules(flag: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (prefixes, exact paths) from `env.<flag> = files.any { ... }`."""
    match = re.search(
        rf"env\.{flag}\s*=\s*files\.any\s*\{{(?P<body>.*?)\}}\s*\?\s*'true'\s*:\s*'false'",
        JENKINSFILE,
        re.DOTALL,
    )
    assert match, f"{flag} change detection block not found"
    body = match.group("body")
    prefixes = tuple(re.findall(r"file\.startsWith\(\s*'([^']+)'\s*\)", body))
    exact = tuple(re.findall(r"file\s*==\s*'([^']+)'", body))
    assert prefixes or exact, f"{flag} change detection block has no rules"
    return prefixes, exact


def _selects(flag: str, path: str) -> bool:
    prefixes, exact = _detection_rules(flag)
    return path in exact or any(path.startswith(prefix) for prefix in prefixes)


@pytest.mark.parametrize(
    "flag, path",
    [
        ("BUILD_AWARDING", "tests/seller_matching/test_awarding_batch.py"),
        ("BUILD_AWARDING", "tests/seller_matching/test_awarding_runtime_image.py"),
        ("BUILD_SELLER_ANALYSIS", "tests/seller_analysis/test_bid_guide.py"),
        ("BUILD_SELLER_ANALYSIS", "tests/seller_analysis/test_api_http.py"),
    ],
)
def test_test_only_change_runs_the_c_stage(flag, path):
    """A test-only change must still run the stage that executes those tests."""
    assert _selects(flag, path)


@pytest.mark.parametrize(
    "flag, path",
    [
        ("BUILD_AWARDING", "src/moongcheap_ai/seller_matching/awarding_batch.py"),
        ("BUILD_AWARDING", "packaging/awarding/requirements.txt"),
        ("BUILD_SELLER_ANALYSIS", "requirements-api.txt"),
        ("BUILD_SELLER_ANALYSIS", "docker/Dockerfile.seller-analysis"),
    ],
)
def test_existing_source_triggers_are_kept(flag, path):
    assert _selects(flag, path)


@pytest.mark.parametrize(
    "path",
    [
        "tests/demand_clustering/test_runtime_job.py",
        "tests/seller_analysis/test_bid_guide.py",
    ],
)
def test_other_parts_tests_do_not_rebuild_the_awarding_image(path):
    assert not _selects("BUILD_AWARDING", path)

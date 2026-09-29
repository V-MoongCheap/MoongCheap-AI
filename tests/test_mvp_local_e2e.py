"""Local B -> C smoke: exact results on the committed synthetic samples.

This is not an integrated E2E. The Part A parser and the A -> B input generator
are not run. Clusters are identified by their demand ID set, never by the hashed
cluster_id or by row order.
"""

import ast
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples" / "e2e"
DEMANDS = SAMPLES / "demands_sample.csv"
OFFERS = SAMPLES / "offers_sample.csv"
OUTPUTS = (
    "demand_clusters_v0.csv",
    "demand_cluster_summary_v0.csv",
    "seller_offer_matches_v0.csv",
    "seller_demand_analysis_v0.csv",
)

GINSENG = frozenset({"D001", "D002", "D003"})
VITAMIN_C = frozenset({"D004", "D005"})
VITAMIN_C_FIXED = frozenset({"D006"})

# demand IDs -> participant_count, total_quantity, catalog_count, substitutable
EXPECTED_CLUSTERS = {
    GINSENG: (3, 10, 2, True),
    VITAMIN_C: (2, 5, 1, True),
    VITAMIN_C_FIXED: (1, 2, 1, False),
}

# (demand IDs, offer) -> match_status, score, category_match, moq_ok, price_available
# Derived by hand from seller_matching.baseline: category 50 + MOQ <= quantity 25 + price > 0 25,
# and CANDIDATE only when all three pass.
EXPECTED_MATCHES = {
    (GINSENG, "O-1001"): ("CANDIDATE", 100, True, True, True),
    (GINSENG, "O-1002"): ("REVIEW", 75, True, False, True),
    (GINSENG, "O-1003"): ("REVIEW", 50, False, True, True),
    (GINSENG, "O-1004"): ("REVIEW", 50, False, True, True),
    (VITAMIN_C, "O-1001"): ("REVIEW", 50, False, True, True),
    (VITAMIN_C, "O-1002"): ("REVIEW", 25, False, False, True),
    (VITAMIN_C, "O-1003"): ("CANDIDATE", 100, True, True, True),
    (VITAMIN_C, "O-1004"): ("REVIEW", 50, False, True, True),
    (VITAMIN_C_FIXED, "O-1001"): ("REVIEW", 25, False, False, True),
    (VITAMIN_C_FIXED, "O-1002"): ("REVIEW", 25, False, False, True),
    (VITAMIN_C_FIXED, "O-1003"): ("REVIEW", 75, True, False, True),
    (VITAMIN_C_FIXED, "O-1004"): ("REVIEW", 50, False, True, True),
}

# demand IDs -> candidate_offer_count, top_offer_score
EXPECTED_SELLER_SUMMARY = {
    GINSENG: (1, 100),
    VITAMIN_C: (1, 100),
    VITAMIN_C_FIXED: (0, 0),
}


def _drive():
    spec = importlib.util.spec_from_file_location(
        "run_mvp_local_e2e", ROOT / "scripts" / "e2e" / "run_mvp_local_e2e.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read(output_dir, name):
    return pd.read_csv(output_dir / name, dtype=str, encoding="utf-8-sig")


def _truth(value):
    return str(value).strip().casefold() in {"true", "1", "1.0"}


def _cluster_keys(output_dir):
    clustered = _read(output_dir, "demand_clusters_v0.csv")
    return {cluster_id: frozenset(group["demand_id"]) for cluster_id, group in clustered.groupby("cluster_id")}


@pytest.fixture
def sample_run(tmp_path):
    result = _drive().run(DEMANDS, OFFERS, tmp_path)
    return result, tmp_path


def test_samples_carry_the_clustering_contract():
    columns = set(pd.read_csv(DEMANDS).columns)

    assert {"demand_id", "catalog_id", "label", "category_id", "quantity", "is_substitutable"} <= columns
    assert OFFERS.exists()


def test_run_reports_counts_and_writes_all_outputs(sample_run):
    result, output_dir = sample_run

    assert result == {"status": "COMPLETED", "demands": 6, "clusters": 3, "matches": 12, "offers": 4}
    for name in OUTPUTS:
        assert (output_dir / name).exists(), name


def test_clusters_match_expected_membership_and_totals(sample_run):
    _, output_dir = sample_run
    keys = _cluster_keys(output_dir)
    summary = _read(output_dir, "demand_cluster_summary_v0.csv")

    actual = {
        keys[row.cluster_id]: (
            int(row.participant_count),
            int(row.total_quantity),
            int(row.catalog_count),
            _truth(row.substitutable),
        )
        for row in summary.itertuples()
    }

    assert actual == EXPECTED_CLUSTERS


def test_every_cluster_offer_pair_is_judged_once_with_expected_result(sample_run):
    _, output_dir = sample_run
    keys = _cluster_keys(output_dir)
    matches = _read(output_dir, "seller_offer_matches_v0.csv")

    pairs = [(keys[row.cluster_id], row.item_id) for row in matches.itertuples()]
    assert len(pairs) == len(set(pairs)), "a cluster/offer pair was judged twice"

    actual = {
        (keys[row.cluster_id], row.item_id): (
            row.match_status,
            int(row.score),
            _truth(row.category_match),
            _truth(row.moq_ok),
            _truth(row.price_available),
        )
        for row in matches.itertuples()
    }

    assert actual == EXPECTED_MATCHES


def test_seller_summary_counts_only_candidates(sample_run):
    _, output_dir = sample_run
    keys = _cluster_keys(output_dir)
    analysis = _read(output_dir, "seller_demand_analysis_v0.csv")

    actual = {
        keys[row.cluster_id]: (int(float(row.candidate_offer_count)), int(float(row.top_offer_score)))
        for row in analysis.itertuples()
    }

    assert actual == EXPECTED_SELLER_SUMMARY


@pytest.mark.parametrize("missing", ["input", "offers"])
def test_missing_file_fails_before_writing_outputs(tmp_path, missing):
    """A missing file must not become an empty frame that still reports COMPLETED."""
    output_dir = tmp_path / "out"
    absent = tmp_path / "does-not-exist.csv"
    paths = {"input": DEMANDS, "offers": OFFERS, missing: absent}

    with pytest.raises(FileNotFoundError, match=f"--{missing}"):
        _drive().run(paths["input"], paths["offers"], output_dir)
    assert not output_dir.exists()


@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--input", str(DEMANDS)],
        ["--offers", str(OFFERS)],
        ["--example", "--input", str(DEMANDS)],
        ["--example", "--offers", str(OFFERS)],
        ["--example", "--input", str(DEMANDS), "--offers", str(OFFERS)],
    ],
    ids=["none", "input-only", "offers-only", "example+input", "example+offers", "example+both"],
)
def test_cli_rejects_implicit_or_mixed_inputs_before_writing(tmp_path, extra):
    output_dir = tmp_path / "out"

    with pytest.raises(SystemExit) as error:
        _drive().main([*extra, "--output-dir", str(output_dir)])

    assert error.value.code == 2
    assert not output_dir.exists()


def test_cli_example_mode_reports_its_source(tmp_path, capsys):
    _drive().main(["--example", "--output-dir", str(tmp_path)])

    printed = ast.literal_eval(capsys.readouterr().out.strip())
    assert printed["mode"] == "example"
    assert Path(printed["input"]) == DEMANDS
    assert Path(printed["offers_file"]) == OFFERS
    assert printed["matches"] == 12


def test_cli_files_mode_uses_only_the_given_files(tmp_path, capsys):
    demands = tmp_path / "demands.csv"
    offers = tmp_path / "offers.csv"
    demands.write_text(DEMANDS.read_text(encoding="utf-8").replace("D00", "CUSTOM-D00"), encoding="utf-8")
    offers.write_text(OFFERS.read_text(encoding="utf-8").replace("O-100", "CUSTOM-O-100"), encoding="utf-8")
    output_dir = tmp_path / "out"

    _drive().main(["--input", str(demands), "--offers", str(offers), "--output-dir", str(output_dir)])

    printed = ast.literal_eval(capsys.readouterr().out.strip())
    assert printed["mode"] == "files"
    assert Path(printed["input"]) == demands
    assert Path(printed["offers_file"]) == offers
    assert set(_read(output_dir, "demand_clusters_v0.csv")["demand_id"]) == {f"CUSTOM-D00{i}" for i in range(1, 7)}
    assert set(_read(output_dir, "seller_offer_matches_v0.csv")["item_id"]) == {f"CUSTOM-O-100{i}" for i in range(1, 5)}

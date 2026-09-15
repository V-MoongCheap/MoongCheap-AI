"""Profile generation must use the supplied taxonomy and preserve source IDs."""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

from moongcheap_ai.demand_clustering.part_a_integration import validate_profile_versions
from scripts.evaluation.build_catalog_wide_mfds_profiles import main

ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_PATH = ROOT / "config/facet_taxonomy_v2_2.json"


@pytest.fixture
def build_args(tmp_path):
    datasets = {
        "category-mapping": [{"source_product_id": "mfds-1", "service_category_candidate_key": "RED_GINSENG"}],
        "products": [{
            "source_product_id": "mfds-1", "name": "홍삼 완제품", "product_type": "홍삼",
            "product_form": "액상", "main_functionality": "면역력 증진에 도움을 줄 수 있음",
            "intake_method": "1일 1회 섭취", "functional_ingredients": "홍삼",
        }],
        "references": [{
            "category_reference_name": "홍삼", "ingredient_name": "진세노사이드",
            "main_functionality": "면역력 증진에 도움을 줄 수 있음",
        }],
        "claims": [{"claim_key_candidate": "claim-1", "claim_text_candidate": "면역력 증진에 도움을 줄 수 있음"}],
    }
    args = ["build_catalog_wide_mfds_profiles.py"]
    for option, rows in datasets.items():
        path = tmp_path / f"{option}.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        args.extend([f"--{option}", str(path)])
    return args + ["--taxonomy", str(TAXONOMY_PATH), "--output-dir", str(tmp_path / "generated")]


def test_generator_uses_taxonomy_version_and_preserves_source_ids(build_args, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", build_args)
    main()
    output = tmp_path / "generated"
    result = pd.read_csv(output / "catalog_profiles.csv", dtype=str)
    assert result.taxonomy_version.tolist() == ["v2.2"]
    assert result.catalog_id.tolist() == ["mfds-1"]
    assert (output / "taxonomy.json").read_bytes() == TAXONOMY_PATH.read_bytes()
    assert json.loads((output / "manifest.json").read_text())["taxonomyVersion"] == "v2.2"


@pytest.mark.parametrize("invalid", ["version", "category"])
def test_generator_rejects_incompatible_inputs_before_saving(build_args, tmp_path, monkeypatch, invalid):
    if invalid == "version":
        build_args.extend(["--taxonomy-version", "v2.1"])
    else:
        mapping = tmp_path / "category-mapping.csv"
        frame = pd.read_csv(mapping)
        frame["service_category_candidate_key"] = "UNKNOWN_CATEGORY"
        frame.to_csv(mapping, index=False)
    monkeypatch.setattr(sys, "argv", build_args)
    with pytest.raises(ValueError, match="taxonomy"):
        main()
    assert not (tmp_path / "generated").exists()


def test_mixed_profile_versions_are_rejected():
    taxonomy = json.loads(TAXONOMY_PATH.read_text())
    with pytest.raises(ValueError, match="do not match v2.2"):
        validate_profile_versions(pd.DataFrame({"taxonomy_version": ["v2.2", "v2.1"]}), taxonomy)
    assert validate_profile_versions(pd.DataFrame({"taxonomy_version": ["v2.2"]}), taxonomy) == "v2.2"


def test_empty_profiles_are_rejected():
    taxonomy = json.loads(TAXONOMY_PATH.read_text())
    with pytest.raises(ValueError, match="profiles must not be empty"):
        validate_profile_versions(pd.DataFrame({"taxonomy_version": []}), taxonomy)

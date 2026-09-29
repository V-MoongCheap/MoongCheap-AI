"""The checked-in release must build without local datasets or runtime storage."""

import gzip
import json
from pathlib import Path

import pytest

from scripts.deployment.prepare_demand_clustering_assets import (
    file_sha256,
    pack_catalog_seed,
    prepare_catalog,
)

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "packaging/demand-clustering/runtime-assets"


def test_packaged_release_is_complete_and_uses_current_taxonomy(tmp_path):
    manifest = prepare_catalog(ASSETS, tmp_path)
    assert manifest["catalogRowCount"] == 1_989
    assert manifest["categorySeedRowCount"] == 42
    assert manifest["mappedCategorySeedRowCount"] == 25
    assert manifest["unmappedCategorySeedRowCount"] == 17
    assert manifest["mappedCategoryRowCount"] == 1_890
    assert manifest["unmappedCategoryRowCount"] == 99
    assert (tmp_path / "taxonomy.json").read_bytes() == (
        ROOT / "config/facet_taxonomy_v2_2.json"
    ).read_bytes()
    assert (tmp_path / "product_catalog_seed_v5.csv").is_file()
    assert (tmp_path / "category_seed_v5.csv").is_file()
    assert json.loads((tmp_path / "manifest.json").read_text()) == manifest


@pytest.fixture
def seed_release(tmp_path):
    seed = tmp_path / "product_catalog_seed_v5.csv"
    seed.write_text(
        "catalog_seed_id,source_product_id,name,category_seed_id,"
        "source_category_path,source_category_id,status\n"
        "seed-1,source-1,상품,cat-1,식품,health,ACTIVE\n"
    )
    taxonomy = tmp_path / "taxonomy.json"
    taxonomy.write_text(json.dumps({
        "version": "v2.2",
        "categories": [{
            "category_id": "health",
            "facets": [],
            "status": "PROVISIONAL",
        }],
    }))
    category_seed = tmp_path / "category_seed_v5.csv"
    category_seed.write_text(
        "category_key,parent_key,name,depth,facet,source,"
        "source_category_path,health_taxonomy_category_id\n"
        'cat-1,,\uC2DD\uD488,1,"{""taxonomy_version"":""v2.2"",'
        '""category_id"":""health"",""facets"":[],""status"":'
        '""DRAFT_PENDING_HUMAN_REVIEW""}",DOMEGGOOK_CATEGORY_PATH,'
        "\uC2DD\uD488,health\n"
    )
    return seed, category_seed, taxonomy


def test_release_packaging_is_reproducible_and_preserves_csv(seed_release, tmp_path):
    seed, category_seed, taxonomy = seed_release
    first, second = tmp_path / "first", tmp_path / "second"
    pack_catalog_seed(seed, category_seed, taxonomy, first, release="test-v5")
    pack_catalog_seed(seed, category_seed, taxonomy, second, release="test-v5")
    assert (first / "product_catalog_seed_v5.csv.gz").read_bytes() == (
        second / "product_catalog_seed_v5.csv.gz"
    ).read_bytes()
    assert (first / "category_seed_v5.csv.gz").read_bytes() == (
        second / "category_seed_v5.csv.gz"
    ).read_bytes()
    prepare_catalog(first, tmp_path / "image")
    assert (tmp_path / "image/product_catalog_seed_v5.csv").read_bytes() == seed.read_bytes()
    assert (tmp_path / "image/category_seed_v5.csv").read_bytes() == (
        category_seed.read_bytes()
    )


@pytest.mark.parametrize(
    "damage",
    ["archive", "category_archive", "taxonomy", "version", "category", "count"],
)
def test_invalid_release_stops_image_assembly(seed_release, tmp_path, damage):
    seed, category_seed, taxonomy = seed_release
    assets = tmp_path / "assets"
    pack_catalog_seed(seed, category_seed, taxonomy, assets, release="test-v5")
    manifest_path = assets / "catalog.json"
    manifest = json.loads(manifest_path.read_text())
    if damage == "archive":
        (assets / "product_catalog_seed_v5.csv.gz").write_bytes(b"broken")
    elif damage == "category_archive":
        (assets / "category_seed_v5.csv.gz").write_bytes(b"broken")
    elif damage == "taxonomy":
        (assets / "taxonomy.json").write_text("{}")
    elif damage == "count":
        manifest["catalogRowCount"] = 2
    else:
        target = assets / ("taxonomy.json" if damage == "version" else "unused")
        if damage == "version":
            target.write_text(target.read_text().replace("v2.2", "v2.1"))
            manifest["taxonomySha256"] = file_sha256(target)
        else:
            seed.write_text(seed.read_text().replace("health", "unknown"))
        archive = assets / "product_catalog_seed_v5.csv.gz"
        archive.write_bytes(gzip.compress(seed.read_bytes(), mtime=0))
        manifest["compressedSha256"] = file_sha256(archive)
        manifest["catalogSha256"] = file_sha256(seed)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        prepare_catalog(assets, tmp_path / "image")

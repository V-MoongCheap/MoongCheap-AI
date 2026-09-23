"""The checked-in release must build without local datasets or runtime storage."""

import gzip
import json
from pathlib import Path

import pytest

from scripts.deployment.prepare_demand_clustering_assets import (
    file_sha256, pack_catalog, prepare_catalog,
)


ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "packaging/demand-clustering/runtime-assets"


def test_packaged_release_is_complete_and_uses_current_taxonomy(tmp_path):
    manifest = prepare_catalog(ASSETS, tmp_path)
    assert manifest["profileCount"] > 0
    assert (tmp_path / "taxonomy.json").read_bytes() == (
        ROOT / "config/facet_taxonomy_v2_2.json"
    ).read_bytes()
    assert json.loads((tmp_path / "manifest.json").read_text()) == manifest


@pytest.fixture
def release(tmp_path):
    source = tmp_path / "release"
    source.mkdir()
    (source / "catalog_profiles.csv").write_text(
        "catalog_id,service_category_id,taxonomy_version\n1,health,v2.2\n"
    )
    taxonomy = source / "taxonomy.json"
    taxonomy.write_text(json.dumps({
        "version": "v2.2", "categories": [{"category_id": "health"}],
    }))
    (source / "manifest.json").write_text(json.dumps({
        "taxonomySha256": file_sha256(taxonomy), "taxonomyVersion": "v2.2",
        "catalogMappings": 1, "identityContract": "preserved",
    }))
    return source


def test_release_packaging_is_reproducible_and_preserves_csv(release, tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    pack_catalog(release, first)
    pack_catalog(release, second)
    assert (first / "catalog_profiles.csv.gz").read_bytes() == (
        second / "catalog_profiles.csv.gz"
    ).read_bytes()
    prepare_catalog(first, tmp_path / "image")
    assert (tmp_path / "image/catalog_profiles.csv").read_bytes() == (
        release / "catalog_profiles.csv"
    ).read_bytes()


@pytest.mark.parametrize("damage", ["archive", "taxonomy", "version", "category", "count"])
def test_invalid_release_stops_image_assembly(release, tmp_path, damage):
    assets = tmp_path / "assets"
    pack_catalog(release, assets)
    manifest_path = assets / "catalog.json"
    manifest = json.loads(manifest_path.read_text())
    if damage == "archive":
        (assets / "catalog_profiles.csv.gz").write_bytes(b"broken")
    elif damage == "taxonomy":
        (assets / "taxonomy.json").write_text("{}")
    elif damage == "count":
        manifest["profileCount"] = 2
    else:
        profile = release / "catalog_profiles.csv"
        text = profile.read_text().replace(
            "v2.2" if damage == "version" else "health",
            "v2.1" if damage == "version" else "unknown",
        )
        profile.write_text(text)
        archive = assets / "catalog_profiles.csv.gz"
        archive.write_bytes(gzip.compress(profile.read_bytes(), mtime=0))
        manifest["compressedSha256"] = file_sha256(archive)
        manifest["profileSha256"] = file_sha256(profile)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        prepare_catalog(assets, tmp_path / "image")

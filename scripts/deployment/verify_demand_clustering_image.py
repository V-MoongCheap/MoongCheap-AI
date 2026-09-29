"""Run inside the built image, offline and without data/model mounts or real secrets."""

import hashlib
import json
import os

import pandas as pd

from moongcheap_ai.demand_clustering.catalog_seed_planner import (
    build_runtime_seed_catalog,
)
from moongcheap_ai.demand_clustering.e5_runtime_scorer import (
    E5RuntimeTextSimilarityScorer,
)
from moongcheap_ai.demand_clustering.part_a_integration import build_part_b_parser
from moongcheap_ai.demand_clustering.runtime_job import load_job_config


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    config = load_job_config({
        **os.environ,
        "SHARED_DATABASE_URL": "postgresql://test:test@localhost/test",
        "BACKEND_BASE_URL": "http://backend.invalid",
        "BACKEND_INTERNAL_KEY": "offline-image-check",
    })
    manifest = json.loads((config.catalog_seed_path.parent / "manifest.json").read_text())
    category_seed_path = config.catalog_seed_path.parent / "category_seed_v5.csv"
    assert digest(config.catalog_seed_path) == manifest["catalogSha256"]
    assert digest(category_seed_path) == manifest["categorySeedSha256"]
    assert digest(config.taxonomy_path) == manifest["taxonomySha256"]
    taxonomy = json.loads(config.taxonomy_path.read_text())
    seed = pd.read_csv(config.catalog_seed_path, dtype=str, keep_default_na=False)
    category_seed = pd.read_csv(
        category_seed_path,
        dtype=str,
        keep_default_na=False,
    )
    assert len(seed) == manifest["catalogRowCount"]
    assert len(category_seed) == manifest["categorySeedRowCount"]
    _parser, integration = build_part_b_parser(
        taxonomy=taxonomy, rules_path=config.constraint_rules_path,
        aliases_path=config.constraint_aliases_path,
        compatibility_aliases_path=config.constraint_compat_aliases_path,
    )
    runtime_catalog = build_runtime_seed_catalog(seed, taxonomy=taxonomy)
    assert len(runtime_catalog) == len(seed)
    model_manifest = json.loads((config.e5.model_path / "image-model-manifest.json").read_text())
    for filename, expected in model_manifest["files"].items():
        assert digest(config.e5.model_path / filename) == expected, filename
    scorer = E5RuntimeTextSimilarityScorer(config.e5)
    scorer.prepare(["먹기 편한 영양제"], ["작은 캡슐 형태의 영양제"])
    assert scorer.model_loaded
    print(json.dumps({
        "release": manifest["release"], "catalogSeedRows": len(seed),
        "modelRevision": model_manifest["revision"],
        "aliasMode": integration["aliasMode"],
        "embeddingCache": scorer.cache_summary,
        "uid": os.getuid(), "networkRequired": False, "dataMountsRequired": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

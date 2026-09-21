"""Run inside the built image, offline and without data/model mounts or real secrets."""

import hashlib
import json
import os

import pandas as pd

from moongcheap_ai.demand_clustering.e5_runtime_scorer import E5RuntimeTextSimilarityScorer
from moongcheap_ai.demand_clustering.part_a_integration import (
    build_part_b_parser, validate_profile_versions,
)
from moongcheap_ai.demand_clustering.runtime_job import load_job_config
from moongcheap_ai.demand_clustering.substitute_proposal_planner import (
    build_runtime_catalog_profiles,
)


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
    manifest = json.loads((config.catalog_profiles_path.parent / "manifest.json").read_text())
    assert digest(config.catalog_profiles_path) == manifest["profileSha256"]
    assert digest(config.taxonomy_path) == manifest["taxonomySha256"]
    taxonomy = json.loads(config.taxonomy_path.read_text())
    profiles = pd.read_csv(config.catalog_profiles_path, dtype=str, keep_default_na=False)
    validate_profile_versions(profiles, taxonomy)
    assert len(profiles) == manifest["profileCount"]
    _parser, integration = build_part_b_parser(
        taxonomy=taxonomy, rules_path=config.constraint_rules_path,
        aliases_path=config.constraint_aliases_path,
        compatibility_aliases_path=config.constraint_compat_aliases_path,
    )
    runtime_profiles = build_runtime_catalog_profiles(profiles, taxonomy=taxonomy)
    assert len(runtime_profiles) == len(profiles)
    model_manifest = json.loads((config.e5.model_path / "image-model-manifest.json").read_text())
    for filename, expected in model_manifest["files"].items():
        assert digest(config.e5.model_path / filename) == expected, filename
    scorer = E5RuntimeTextSimilarityScorer(config.e5)
    scorer.prepare(["먹기 편한 영양제"], ["작은 캡슐 형태의 영양제"])
    assert scorer.model_loaded
    print(json.dumps({
        "release": manifest["release"], "profiles": len(profiles),
        "modelRevision": model_manifest["revision"],
        "aliasMode": integration["aliasMode"],
        "embeddingCache": scorer.cache_summary,
        "uid": os.getuid(), "networkRequired": False, "dataMountsRequired": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

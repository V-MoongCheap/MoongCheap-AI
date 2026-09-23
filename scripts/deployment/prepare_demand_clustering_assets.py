"""Assemble verified image assets at build time; never runs in the batch job."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import shutil
from pathlib import Path


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_sha256(path: Path, expected: str) -> None:
    if file_sha256(path) != expected:
        raise ValueError(f"SHA256 mismatch: {path.name}")


def pack_catalog(release: Path, assets: Path) -> None:
    """Publish a generated release into the small, versioned Docker build inputs."""
    source = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    taxonomy = release / "taxonomy.json"
    profiles = release / "catalog_profiles.csv"
    verify_sha256(taxonomy, source["taxonomySha256"])
    assets.mkdir(parents=True, exist_ok=True)
    compressed = assets / "catalog_profiles.csv.gz"
    with profiles.open("rb") as stream, compressed.open("wb") as destination:
        with gzip.GzipFile(filename="", mode="wb", fileobj=destination, mtime=0) as archive:
            shutil.copyfileobj(stream, archive)
    shutil.copyfile(taxonomy, assets / "taxonomy.json")
    manifest = {
        "schemaVersion": "demand-clustering-image-catalog.v1",
        "release": release.name,
        "taxonomyVersion": source["taxonomyVersion"],
        "profileCount": source["catalogMappings"],
        "profileSha256": file_sha256(profiles),
        "compressedSha256": file_sha256(compressed),
        "taxonomySha256": file_sha256(taxonomy),
        "identityContract": source["identityContract"],
        "sourceManifest": source,
    }
    (assets / "catalog.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


def prepare_catalog(assets: Path, output: Path) -> dict:
    manifest = json.loads((assets / "catalog.json").read_text(encoding="utf-8"))
    compressed = assets / "catalog_profiles.csv.gz"
    taxonomy_file = assets / "taxonomy.json"
    verify_sha256(compressed, manifest["compressedSha256"])
    verify_sha256(taxonomy_file, manifest["taxonomySha256"])
    taxonomy = json.loads(taxonomy_file.read_text(encoding="utf-8"))
    if taxonomy["version"] != manifest["taxonomyVersion"]:
        raise ValueError("catalog and taxonomy versions differ")
    categories = {row["category_id"] for row in taxonomy["categories"]}

    output.mkdir(parents=True, exist_ok=True)
    profile_file = output / "catalog_profiles.csv"
    with gzip.open(compressed, "rb") as source, profile_file.open("wb") as destination:
        shutil.copyfileobj(source, destination)
    verify_sha256(profile_file, manifest["profileSha256"])
    count = 0
    catalog_ids: set[str] = set()
    with profile_file.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["taxonomy_version"] != manifest["taxonomyVersion"]:
                raise ValueError("profile taxonomy version mismatch")
            if row["service_category_id"] not in categories:
                raise ValueError("profile category missing from taxonomy")
            catalog_id = row["catalog_id"]
            if not catalog_id or catalog_id in catalog_ids:
                raise ValueError("profile catalog IDs must be nonempty and unique")
            catalog_ids.add(catalog_id)
            count += 1
    if not count or count != manifest["profileCount"]:
        raise ValueError("profile count mismatch")
    shutil.copyfile(taxonomy_file, output / "taxonomy.json")
    shutil.copyfile(assets / "catalog.json", output / "manifest.json")
    return manifest


def prepare_model(manifest_file: Path, output: Path) -> None:
    from huggingface_hub import hf_hub_download

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    revision = manifest["revision"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("model revision must be a full commit SHA")
    output.mkdir(parents=True, exist_ok=True)
    for filename, digest in manifest["files"].items():
        path = Path(hf_hub_download(
            repo_id=manifest["repository"], revision=revision,
            filename=filename, local_dir=output,
        ))
        verify_sha256(path, digest)
    # local_dir contains standalone files, so no cache symlinks reach the image.
    shutil.rmtree(output / ".cache", ignore_errors=True)
    shutil.copyfile(manifest_file, output / "image-model-manifest.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("pack")
    pack.add_argument("--release", type=Path, required=True)
    pack.add_argument("--assets", type=Path, required=True)
    catalog = commands.add_parser("catalog")
    catalog.add_argument("--assets", type=Path, required=True)
    catalog.add_argument("--output", type=Path, required=True)
    model = commands.add_parser("model")
    model.add_argument("--manifest", type=Path, required=True)
    model.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "pack":
        pack_catalog(args.release, args.assets)
        print("Packaged catalog build inputs; commit runtime-assets together")
    elif args.command == "catalog":
        manifest = prepare_catalog(args.assets, args.output)
        print(f"Prepared {manifest['profileCount']} catalog profiles ({manifest['release']})")
    else:
        prepare_model(args.manifest, args.output)
        print("Prepared pinned E5 model")


if __name__ == "__main__":
    main()

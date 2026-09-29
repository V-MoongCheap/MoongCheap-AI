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


REQUIRED_SEED_COLUMNS = {
    "catalog_seed_id",
    "source_product_id",
    "name",
    "category_seed_id",
    "source_category_path",
    "source_category_id",
    "status",
}

REQUIRED_CATEGORY_SEED_COLUMNS = {
    "category_key",
    "parent_key",
    "name",
    "depth",
    "facet",
    "source",
    "source_category_path",
    "health_taxonomy_category_id",
}


def _taxonomy_metadata(taxonomy_file: Path) -> tuple[str, dict[str, dict]]:
    taxonomy = json.loads(taxonomy_file.read_text(encoding="utf-8"))
    version = str(taxonomy.get("version") or taxonomy.get("taxonomy_version") or "")
    if not version:
        raise ValueError("taxonomy version must not be blank")
    categories = {}
    for row in taxonomy.get("categories", ()):
        category_id = str(row.get("category_id", "")).strip()
        if not category_id:
            continue
        if category_id in categories:
            raise ValueError("taxonomy category IDs must be unique")
        categories[category_id] = row
    if not categories:
        raise ValueError("taxonomy must contain categories")
    return version, categories


def _category_facets_match(
    seed_facets: object,
    taxonomy_facets: object,
) -> bool:
    """Allow reviewed taxonomy aliases while preserving every seeded value."""

    if not isinstance(seed_facets, list) or not isinstance(taxonomy_facets, list):
        return False
    if len(seed_facets) != len(taxonomy_facets):
        return False
    for seeded, runtime in zip(seed_facets, taxonomy_facets, strict=True):
        if not isinstance(seeded, dict) or not isinstance(runtime, dict):
            return False
        for key in ("facet_id", "name", "order", "definition", "status"):
            if seeded.get(key) != runtime.get(key):
                return False
        seeded_values = seeded.get("values")
        runtime_values = runtime.get("values")
        if not isinstance(seeded_values, list) or not isinstance(
            runtime_values,
            list,
        ):
            return False
        if len(seeded_values) != len(runtime_values):
            return False
        for seeded_value, runtime_value in zip(
            seeded_values,
            runtime_values,
            strict=True,
        ):
            for key in ("code", "value"):
                if seeded_value.get(key) != runtime_value.get(key):
                    return False
            if seeded_value.get("status") != runtime_value.get("status"):
                normalized_as_alias = (
                    seeded_value.get("status") == "PROVISIONAL"
                    and runtime_value.get("status") == "DEPRECATED"
                    and any(
                        seeded_value.get("value")
                        in candidate.get("aliases", ())
                        for candidate in runtime_values
                        if candidate is not runtime_value
                    )
                )
                if not normalized_as_alias:
                    return False
            if not set(seeded_value.get("aliases", ())).issubset(
                runtime_value.get("aliases", ())
            ):
                return False
    return True


def _category_seed_bindings(
    category_seed_file: Path,
    taxonomy_file: Path,
) -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    """Validate Backend category CSV and return product join fields by seed key."""

    taxonomy_version, taxonomy_categories = _taxonomy_metadata(taxonomy_file)
    rows: dict[str, dict[str, str]] = {}
    with category_seed_file.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if missing := sorted(
            REQUIRED_CATEGORY_SEED_COLUMNS - set(reader.fieldnames or ())
        ):
            raise ValueError("category seed missing columns: " + ", ".join(missing))
        for row in reader:
            key = row["category_key"].strip()
            if not key or key in rows:
                raise ValueError("category seed keys must be nonempty and unique")
            if not row["name"].strip() or not row["source_category_path"].strip():
                raise ValueError("category seed names and paths must not be blank")
            if row["source"].strip() != "DOMEGGOOK_CATEGORY_PATH":
                raise ValueError("unsupported category seed source")
            try:
                depth = int(row["depth"])
            except ValueError as error:
                raise ValueError("category seed depths must be integers") from error
            if depth < 1:
                raise ValueError("category seed depths must be positive")
            normalized = {key: str(value or "").strip() for key, value in row.items()}
            normalized["depth"] = str(depth)
            rows[key] = normalized

    if not rows:
        raise ValueError("category seed must not be empty")

    mapped = 0
    seen_paths: set[str] = set()
    mapped_facets: dict[str, object] = {}
    for key, row in rows.items():
        parent_key = row["parent_key"]
        depth = int(row["depth"])
        if depth == 1:
            if parent_key:
                raise ValueError("depth-1 category must not have a parent")
            expected_path = row["name"]
        else:
            parent = rows.get(parent_key)
            if parent is None or int(parent["depth"]) != depth - 1:
                raise ValueError("category seed parent hierarchy is invalid")
            expected_path = f"{parent['source_category_path']} > {row['name']}"
        path = row["source_category_path"]
        if path != expected_path or path in seen_paths:
            raise ValueError("category seed paths must match the parent hierarchy")
        seen_paths.add(path)

        category_id = row["health_taxonomy_category_id"]
        facet_text = row["facet"]
        if not category_id:
            if facet_text:
                raise ValueError("unmapped category seed rows must not contain facets")
            continue
        mapped += 1
        category = taxonomy_categories.get(category_id)
        if category is None:
            raise ValueError("category seed mapping missing from taxonomy")
        if not facet_text:
            raise ValueError("mapped category seed rows must contain facets")
        try:
            facet = json.loads(facet_text)
        except json.JSONDecodeError as error:
            raise ValueError("category seed facets must be valid JSON") from error
        if (
            facet.get("taxonomy_version") != taxonomy_version
            or facet.get("category_id") != category_id
            or not _category_facets_match(
                facet.get("facets"),
                category.get("facets"),
            )
        ):
            raise ValueError("category seed facets are incompatible with taxonomy")
        prior = mapped_facets.setdefault(category_id, facet.get("facets"))
        if prior != facet.get("facets"):
            raise ValueError("category seed repeats inconsistent facets")

    return rows, {
        "categorySeedRowCount": len(rows),
        "mappedCategorySeedRowCount": mapped,
        "unmappedCategorySeedRowCount": len(rows) - mapped,
    }


def validate_category_seed(
    category_seed_file: Path,
    taxonomy_file: Path,
) -> dict[str, int]:
    """Validate the category CSV that generated the Backend category SQL."""

    _, counts = _category_seed_bindings(category_seed_file, taxonomy_file)
    return counts


def validate_catalog_seed(
    seed_file: Path,
    category_seed_file: Path,
    taxonomy_file: Path,
) -> dict[str, int]:
    """Validate the deterministic v5-to-runtime identity boundary."""

    _, categories = _taxonomy_metadata(taxonomy_file)
    category_bindings, _ = _category_seed_bindings(
        category_seed_file,
        taxonomy_file,
    )
    count = 0
    mapped = 0
    seed_ids: set[str] = set()
    source_ids: set[str] = set()
    names: set[str] = set()
    with seed_file.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if missing := sorted(REQUIRED_SEED_COLUMNS - set(reader.fieldnames or ())):
            raise ValueError("catalog seed missing columns: " + ", ".join(missing))
        for row in reader:
            seed_id = row["catalog_seed_id"].strip()
            source_id = row["source_product_id"].strip()
            name = row["name"].strip()
            category_seed_id = row["category_seed_id"].strip()
            category_id = row["source_category_id"].strip()
            if not seed_id or seed_id in seed_ids:
                raise ValueError("catalog seed IDs must be nonempty and unique")
            if not source_id or source_id in source_ids:
                raise ValueError("source product IDs must be nonempty and unique")
            if not name or name in names:
                raise ValueError("catalog names must be nonempty and unique")
            if not category_seed_id:
                raise ValueError("category seed IDs must not be blank")
            category_binding = category_bindings.get(category_seed_id)
            if category_binding is None:
                raise ValueError("catalog row references unknown category seed ID")
            if row["source_category_path"].strip() != category_binding[
                "source_category_path"
            ]:
                raise ValueError("catalog and category seed paths differ")
            if category_id != category_binding["health_taxonomy_category_id"]:
                raise ValueError("catalog and category taxonomy mappings differ")
            if category_id and category_id not in categories:
                raise ValueError("catalog seed category missing from taxonomy")
            if row["status"].strip() not in {"ACTIVE", "INACTIVE"}:
                raise ValueError("unsupported catalog seed status")
            seed_ids.add(seed_id)
            source_ids.add(source_id)
            names.add(name)
            count += 1
            mapped += bool(category_id)
    if not count:
        raise ValueError("catalog seed must not be empty")
    return {
        "catalogRowCount": count,
        "mappedCategoryRowCount": mapped,
        "unmappedCategoryRowCount": count - mapped,
    }


def pack_catalog_seed(
    seed_file: Path,
    category_seed_file: Path,
    taxonomy: Path,
    assets: Path,
    *,
    release: str,
) -> dict:
    """Publish the Backend v5 seed as deterministic Docker build inputs."""

    category_counts = validate_category_seed(category_seed_file, taxonomy)
    counts = validate_catalog_seed(seed_file, category_seed_file, taxonomy)
    taxonomy_version, _ = _taxonomy_metadata(taxonomy)
    assets.mkdir(parents=True, exist_ok=True)
    compressed = assets / "product_catalog_seed_v5.csv.gz"
    with (
        seed_file.open("rb") as stream,
        compressed.open("wb") as destination,
        gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=destination,
            mtime=0,
        ) as archive,
    ):
        shutil.copyfileobj(stream, archive)
    category_compressed = assets / "category_seed_v5.csv.gz"
    with category_seed_file.open("rb") as stream, category_compressed.open(
        "wb"
    ) as destination, gzip.GzipFile(
        filename="", mode="wb", fileobj=destination, mtime=0
    ) as archive:
        shutil.copyfileobj(stream, archive)
    shutil.copyfile(taxonomy, assets / "taxonomy.json")
    manifest = {
        "schemaVersion": "demand-clustering-image-catalog-seed.v1",
        "release": release,
        "taxonomyVersion": taxonomy_version,
        **category_counts,
        **counts,
        "catalogSha256": file_sha256(seed_file),
        "compressedSha256": file_sha256(compressed),
        "categorySeedSha256": file_sha256(category_seed_file),
        "categoryCompressedSha256": file_sha256(category_compressed),
        "taxonomySha256": file_sha256(taxonomy),
        "identityContract": (
            "bind v5 name to Backend product_catalog.name by exact match; "
            "Backend product_catalog.name is unique"
        ),
        "substitutionPolicy": (
            "same v5 leaf category, explicit name facets, no MFDS claim IDs"
        ),
    }
    (assets / "catalog.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return manifest


def prepare_catalog(assets: Path, output: Path) -> dict:
    manifest = json.loads((assets / "catalog.json").read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != "demand-clustering-image-catalog-seed.v1":
        raise ValueError("unsupported catalog seed manifest")
    compressed = assets / "product_catalog_seed_v5.csv.gz"
    category_compressed = assets / "category_seed_v5.csv.gz"
    taxonomy_file = assets / "taxonomy.json"
    verify_sha256(compressed, manifest["compressedSha256"])
    verify_sha256(
        category_compressed,
        manifest["categoryCompressedSha256"],
    )
    verify_sha256(taxonomy_file, manifest["taxonomySha256"])
    taxonomy_version, _ = _taxonomy_metadata(taxonomy_file)
    if taxonomy_version != manifest["taxonomyVersion"]:
        raise ValueError("catalog and taxonomy versions differ")

    output.mkdir(parents=True, exist_ok=True)
    seed_file = output / "product_catalog_seed_v5.csv"
    with gzip.open(compressed, "rb") as source, seed_file.open("wb") as destination:
        shutil.copyfileobj(source, destination)
    category_seed_file = output / "category_seed_v5.csv"
    with gzip.open(category_compressed, "rb") as source, category_seed_file.open(
        "wb"
    ) as destination:
        shutil.copyfileobj(source, destination)
    verify_sha256(seed_file, manifest["catalogSha256"])
    verify_sha256(category_seed_file, manifest["categorySeedSha256"])
    category_counts = validate_category_seed(category_seed_file, taxonomy_file)
    counts = validate_catalog_seed(seed_file, category_seed_file, taxonomy_file)
    for key, value in {**category_counts, **counts}.items():
        if manifest.get(key) != value:
            raise ValueError(f"catalog seed manifest mismatch: {key}")
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
    pack = commands.add_parser("pack-seed")
    pack.add_argument("--seed", type=Path, required=True)
    pack.add_argument("--category-seed", type=Path, required=True)
    pack.add_argument("--taxonomy", type=Path, required=True)
    pack.add_argument("--release", required=True)
    pack.add_argument("--assets", type=Path, required=True)
    catalog = commands.add_parser("catalog")
    catalog.add_argument("--assets", type=Path, required=True)
    catalog.add_argument("--output", type=Path, required=True)
    model = commands.add_parser("model")
    model.add_argument("--manifest", type=Path, required=True)
    model.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "pack-seed":
        manifest = pack_catalog_seed(
            args.seed,
            args.category_seed,
            args.taxonomy,
            args.assets,
            release=args.release,
        )
        print(
            f"Packaged {manifest['catalogRowCount']} v5 catalog seed rows; "
            "commit runtime-assets together"
        )
    elif args.command == "catalog":
        manifest = prepare_catalog(args.assets, args.output)
        print(
            f"Prepared {manifest['catalogRowCount']} catalog seed rows "
            f"({manifest['release']})"
        )
    else:
        prepare_model(args.manifest, args.output)
        print("Prepared pinned E5 model")


if __name__ == "__main__":
    main()

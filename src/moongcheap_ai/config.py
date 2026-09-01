from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value in (None, "") else int(value)


def _optional_int(name: str) -> int | None:
    value = os.getenv(name)
    return None if value in (None, "") else int(value)


@dataclass(frozen=True)
class Settings:
    mfds_api_key: str | None = os.getenv("MFDS_API_KEY")
    mfds_max_pages: int | None = _optional_int("MFDS_MAX_PAGES")
    category_root_depth: int = _int("CATEGORY_ROOT_DEPTH", 1)
    min_term_documents: int = _int("MIN_TERM_DOCUMENTS", 3)
    min_term_document_ratio: float = float(os.getenv("MIN_TERM_DOCUMENT_RATIO", "0.05"))


def paths(root: Path = ROOT) -> dict[str, Path]:
    return {
        "root": root,
        "raw_aihub": root / "data/raw/aihub",
        "raw_kan": root / "data/raw/kan",
        "raw_mfds": root / "data/raw/mfds",
        "interim_category": root / "data/interim/category",
        "interim_products": root / "data/interim/products",
        "interim_facet": root / "data/interim/facet_discovery",
        "processed_category": root / "data/processed/category",
        "processed_catalog": root / "data/processed/product_catalog",
        "processed_facet": root / "data/processed/facet_discovery",
        "reports": root / "data/reports",
    }


def ensure_dirs(root: Path = ROOT) -> None:
    for path in paths(root).values():
        if path.suffix == "":
            path.mkdir(parents=True, exist_ok=True)

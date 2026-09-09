"""Provider-neutral Model 1 Facet Discovery adapter and evidence-safe parser."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from .category_v2_1 import classify_v2_1


MODEL_COLUMNS = ["category_key", "category_name", "source_product_id", "product_name", "source_category", "product_form", "functional_ingredients", "regulated_function", "intake_method", "sampling_reason"]
MODEL_OUTPUT_COLUMNS = ["category_key", "category_name", "facet_id_candidate", "name", "definition", "value", "alias", "source_product_id", "source_field", "source_text", "status"]
PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "facet_discovery_v0.txt"


class ModelCallError(RuntimeError):
    pass


class ModelAdapter(Protocol):
    provider: str
    model: str

    def generate_facet_candidates(self, category: str, products: list[dict[str, Any]], prompt_version: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model: str
    api_key_env: str = ""


class UnavailableModelAdapter:
    provider = "unavailable"
    model = "none"

    def generate_facet_candidates(self, category: str, products: list[dict[str, Any]], prompt_version: str) -> dict[str, Any]:
        raise ModelCallError("No executable Model 1 provider or local model is configured")


class OllamaAdapter:
    provider = "ollama"

    def __init__(self, model: str, endpoint: str = "http://localhost:11434") -> None:
        self.model = model
        self.endpoint = endpoint.rstrip("/")

    def generate_facet_candidates(self, category: str, products: list[dict[str, Any]], prompt_version: str) -> dict[str, Any]:
        product_text = json.dumps(products, ensure_ascii=False)
        prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
        prompt = f"{prompt_template}\n\nPrompt version: {prompt_version}\nTarget category_key: {category}\nInput products (evidence only):\n{product_text}"
        body = json.dumps({"model": self.model, "prompt": prompt, "format": "json", "stream": False, "think": False}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(f"{self.endpoint}/api/generate", data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise ModelCallError(f"Ollama call failed: {exc}") from exc
        raw_response = payload.get("response", "")
        if not raw_response:
            raise ModelCallError("Ollama returned an empty response")
        try:
            return json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise ModelCallError(f"Ollama returned invalid JSON: {exc}") from exc


class MockModelAdapter:
    """Test-only adapter; never used by the production Model 1 runner."""

    provider = "mock-test"
    model = "mock-facet-v0"

    def generate_facet_candidates(self, category: str, products: list[dict[str, Any]], prompt_version: str) -> dict[str, Any]:
        first = products[0]
        return {"category_key": category, "category_name": first.get("category_name", ""), "facets": [{"facet_id_candidate": "form", "name": "product_form", "definition": "Observed product form candidate", "values": [{"value": first.get("product_form", ""), "aliases": []}], "evidence": [{"source_product_id": first["source_product_id"], "source_field": "product_form", "source_text": first.get("product_form", "")}]}]}


def sample_products(frame: pd.DataFrame, max_per_category: int = 24, seed: int = 42) -> pd.DataFrame:
    data = frame.fillna("").copy()
    for column in data.columns:
        data[column] = data[column].astype(str).str.strip()
    classified = data.apply(classify_v2_1, axis=1, result_type="expand")
    # The category name/key are derived from the same V2.1 classifier used by mapping.
    data["category_key"] = [f"health-functional-food:{key.lower()}" if row["product_type"] else "UNMAPPED" for (_, row), key in zip(data.iterrows(), classified[0])]
    data["category_name"] = classified[1].values
    data["regulated_function"] = data.get("main_functionality", "")
    sampled: list[pd.DataFrame] = []
    for category_key, group in data[data["category_key"] != "UNMAPPED"].groupby("category_key", sort=True):
        group = group.sample(frac=1, random_state=seed).drop_duplicates(subset=["source_product_id"])
        selected = pd.concat([
            group.sort_values("source_category_path" if "source_category_path" in group else "product_type").head(max_per_category // 3),
            group[group.get("product_form", "") != ""].head(max_per_category // 3),
            group[group.get("functional_ingredients", "") != ""].head(max_per_category // 3),
        ]).drop_duplicates(subset=["source_product_id"]).head(max_per_category)
        selected = selected.copy()
        selected["sampling_reason"] = "category/source/form/ingredient diversity sample"
        sampled.append(selected)
    result = pd.concat(sampled, ignore_index=True) if sampled else pd.DataFrame()
    return result.reindex(columns=MODEL_COLUMNS, fill_value="")


def parse_model_output(payload: Any, input_products: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    failures: list[dict[str, str]] = []
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict) or not isinstance(payload.get("facets"), list):
            raise ValueError("root/facets schema invalid")
        category_key = str(payload.get("category_key", ""))
        category_name = str(payload.get("category_name", ""))
        valid_ids = set(input_products["source_product_id"].astype(str))
        rows = []
        seen_facets: set[str] = set()
        for facet in payload["facets"]:
            name = str(facet.get("name", "")).strip()
            if not name:
                failures.append({"failure_type": "EMPTY_FACET", "detail": "facet name is empty"}); continue
            if name in seen_facets:
                failures.append({"failure_type": "DUPLICATE_FACET", "detail": name}); continue
            seen_facets.add(name)
            values = facet.get("values") or []
            if not values:
                failures.append({"failure_type": "EMPTY_VALUE", "detail": name}); continue
            evidence = facet.get("evidence") or []
            if not evidence:
                failures.append({"failure_type": "EVIDENCE_MISSING", "detail": name}); continue
            for item in evidence:
                if str(item.get("source_product_id", "")) not in valid_ids:
                    failures.append({"failure_type": "HALLUCINATED_EVIDENCE", "detail": str(item.get("source_product_id", ""))}); continue
                source_id = str(item.get("source_product_id", ""))
                source_text = str(item.get("source_text", ""))
                source_field = str(item.get("source_field", ""))
                if source_field in input_products.columns:
                    allowed = str(input_products.loc[input_products["source_product_id"].astype(str) == source_id, source_field].iloc[0])
                    if source_text and source_text not in allowed:
                        failures.append({"failure_type": "HALLUCINATED_EVIDENCE", "detail": source_id})
                        continue
                for value in values:
                    rows.append({"category_key": category_key, "category_name": category_name, "facet_id_candidate": facet.get("facet_id_candidate", ""), "name": name, "definition": facet.get("definition", ""), "value": value.get("value", ""), "alias": "|".join(value.get("aliases") or []), "source_product_id": source_id, "source_field": source_field, "source_text": source_text, "status": "PROVISIONAL_MODEL_OUTPUT"})
        return pd.DataFrame(rows, columns=MODEL_OUTPUT_COLUMNS), failures
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        failures.append({"failure_type": "SCHEMA_VALIDATION_FAILED", "detail": str(exc)})
        return pd.DataFrame(columns=MODEL_OUTPUT_COLUMNS), failures


def discover_model_config() -> ModelConfig | None:
    provider = os.getenv("MODEL1_PROVIDER", "").strip()
    model = os.getenv("MODEL1_MODEL", "").strip()
    if provider and model:
        return ModelConfig(provider, model, os.getenv("MODEL1_API_KEY_ENV", ""))
    return None

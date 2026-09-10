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


def _build_prompt(prompt_path: Path, category: str, products: list[dict[str, Any]], prompt_version: str) -> str:
    product_text = json.dumps(products, ensure_ascii=False)
    prompt_template = prompt_path.read_text(encoding="utf-8")
    return f"{prompt_template}\n\nPrompt version: {prompt_version}\nTarget category_key: {category}\nInput products (evidence only):\n{product_text}"


def _parse_json_response(raw_response: str, provider: str) -> dict[str, Any]:
    try:
        return json.loads(raw_response)
    except json.JSONDecodeError:
        start, end = raw_response.find("{"), raw_response.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw_response[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise ModelCallError(f"{provider} returned invalid JSON")


class OllamaAdapter:
    provider = "ollama"

    def __init__(self, model: str, endpoint: str = "http://localhost:11434", prompt_path: Path | None = None) -> None:
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.prompt_path = prompt_path or PROMPT_PATH

    def generate_facet_candidates(self, category: str, products: list[dict[str, Any]], prompt_version: str) -> dict[str, Any]:
        prompt = _build_prompt(self.prompt_path, category, products, prompt_version)
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
        return _parse_json_response(raw_response, "Ollama")


class OpenAICompatibleAdapter:
    """Adapter for OpenAI-compatible local servers or commercial APIs."""

    provider = "openai_compatible"

    def __init__(self, model: str, endpoint: str = "https://api.openai.com/v1", api_key: str = "", prompt_path: Path | None = None) -> None:
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.prompt_path = prompt_path or PROMPT_PATH

    def generate_facet_candidates(self, category: str, products: list[dict[str, Any]], prompt_version: str) -> dict[str, Any]:
        prompt = _build_prompt(self.prompt_path, category, products, prompt_version)
        body = json.dumps({"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0, "response_format": {"type": "json_object"}}, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(f"{self.endpoint}/chat/completions", data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise ModelCallError(f"OpenAI-compatible call failed: {exc}") from exc
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelCallError("OpenAI-compatible response schema invalid") from exc
        return _parse_json_response(content, "OpenAI-compatible provider")


class TransformersAdapter:
    """Offline Hugging Face Transformers adapter, loaded lazily when selected."""

    provider = "transformers"

    def __init__(self, model: str, prompt_path: Path | None = None) -> None:
        self.model = model
        self.prompt_path = prompt_path or PROMPT_PATH
        self._pipeline = None

    def _get_pipeline(self):
        if self._pipeline is None:
            try:
                from transformers import pipeline
                self._pipeline = pipeline("text-generation", model=self.model, tokenizer=self.model)
            except Exception as exc:
                raise ModelCallError(f"Transformers model unavailable: {exc}") from exc
        return self._pipeline

    def generate_facet_candidates(self, category: str, products: list[dict[str, Any]], prompt_version: str) -> dict[str, Any]:
        prompt = _build_prompt(self.prompt_path, category, products, prompt_version)
        try:
            output = self._get_pipeline()(prompt, max_new_tokens=2048, do_sample=False, return_full_text=False)[0]["generated_text"]
        except ModelCallError:
            raise
        except Exception as exc:
            raise ModelCallError(f"Transformers generation failed: {exc}") from exc
        return _parse_json_response(output, "Transformers")


def create_model_adapter(provider: str, model: str, endpoint: str = "", api_key: str = "", prompt_path: Path | None = None) -> ModelAdapter:
    provider_key = provider.strip().casefold()
    if provider_key == "ollama":
        return OllamaAdapter(model, endpoint=endpoint or "http://localhost:11434", prompt_path=prompt_path)
    if provider_key in {"openai", "openai_compatible", "vllm", "lm_studio"}:
        return OpenAICompatibleAdapter(model, endpoint=endpoint or "https://api.openai.com/v1", api_key=api_key, prompt_path=prompt_path)
    if provider_key in {"transformers", "huggingface", "hf"}:
        return TransformersAdapter(model, prompt_path=prompt_path)
    return UnavailableModelAdapter()


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
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        failures.append({"failure_type": "SCHEMA_VALIDATION_FAILED", "detail": str(exc)})
        return pd.DataFrame(columns=MODEL_OUTPUT_COLUMNS), failures


def discover_model_config() -> ModelConfig | None:
    provider = os.getenv("MODEL1_PROVIDER", "").strip()
    model = os.getenv("MODEL1_MODEL", "").strip()
    if provider and model:
        return ModelConfig(provider, model, os.getenv("MODEL1_API_KEY_ENV", ""))
    return None

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

MODEL_COLUMNS = [
    "category_key",
    "category_name",
    "source_product_id",
    "product_name",
    "source_category",
    "product_form",
    "functional_ingredients",
    "regulated_function",
    "intake_method",
    "sampling_reason",
]
MODEL_OUTPUT_COLUMNS = [
    "category_key",
    "category_name",
    "facet_id_candidate",
    "name",
    "definition",
    "value",
    "alias",
    "source_product_id",
    "source_field",
    "source_text",
    "status",
]
PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "facet_discovery_v0.txt"
KNOWN_FACET_NAMES = {
    "form": "product_form",
    "product form": "product_form",
    "product_form": "product_form",
    "제품 형태": "product_form",
    "functional ingredients": "functional_ingredients",
    "functional_ingredients": "functional_ingredients",
    "기능성 성분": "functional_ingredients",
    "intake method": "intake_method",
    "intake_method": "intake_method",
    "섭취 방법": "intake_method",
    "regulated function": "regulated_function",
    "regulated_function": "regulated_function",
    "규제 기능": "regulated_function",
}


class ModelCallError(RuntimeError):
    pass


class ModelAdapter(Protocol):
    provider: str
    model: str

    def generate_facet_candidates(
        self, category: str, products: list[dict[str, Any]], prompt_version: str
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model: str
    api_key_env: str = ""


class UnavailableModelAdapter:
    provider = "unavailable"
    model = "none"

    def generate_facet_candidates(
        self, category: str, products: list[dict[str, Any]], prompt_version: str
    ) -> dict[str, Any]:
        raise ModelCallError(
            "No executable Model 1 provider or local model is configured"
        )


def _build_prompt(
    prompt_path: Path,
    category: str,
    products: list[dict[str, Any]],
    prompt_version: str,
) -> str:
    product_text = json.dumps(products, ensure_ascii=False)
    prompt_template = prompt_path.read_text(encoding="utf-8")
    return f"{prompt_template}\n\nPrompt version: {prompt_version}\nTarget category_key: {category}\nInput products (evidence only):\n{product_text}"


def _build_compact_prompt(
    category: str, products: list[dict[str, Any]], prompt_version: str
) -> str:
    """Build a bounded prompt for small-context Korean models."""
    compact_rows = []
    keep = (
        "source_product_id",
        "source_type",
        "product_form",
        "functional_ingredients",
        "intake_method",
    )
    for product in products:
        compact_rows.append({key: str(product.get(key, ""))[:120] for key in keep})
    allowed_ids = [row["source_product_id"] for row in compact_rows if row["source_product_id"]]
    instruction = (
        "Return JSON only; no markdown, no explanation. Use exactly this shape: "
        '{"category_key":"...","category_name":"...","facets":['
        '{"facet_id_candidate":"...","name":"...","definition":"...",'
        '"selection_reason":"...","values":[{"value":"...",'
        '"aliases":[],"value_reason":"..."}],"evidence":['
        '{"source_product_id":"...","source_field":"...",'
        '"source_text":"..."}]}]}. '
        "Use only observed product facts. Return at most 1 facet and 1 value. "
        "Use exactly 1 evidence item per facet; source_text must be one short field value, "
        "not a sentence. Copy source_product_id exactly from the input and choose it only "
        f"from this allowed list: {json.dumps(allowed_ids, ensure_ascii=False)}. "
        "Copy source_text character-for-character from the matching input field; never "
        "translate, normalize, summarize, or invent evidence text. "
        "Keep all strings under 60 characters. Never invent IDs, values, prices, or medical claims."
    )
    return f"{instruction}\nPrompt version: {prompt_version}\nTarget category_key: {category}\nEvidence:\n{json.dumps(compact_rows, ensure_ascii=False)}"


def _parse_json_response(raw_response: str, provider: str) -> dict[str, Any]:
    try:
        return json.loads(raw_response)
    except json.JSONDecodeError:
        start, end = raw_response.find("{"), raw_response.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw_response[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise ModelCallError(f"{provider} returned invalid JSON")


class OllamaAdapter:
    provider = "ollama"

    def __init__(
        self,
        model: str,
        endpoint: str = "http://localhost:11434",
        prompt_path: Path | None = None,
    ) -> None:
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.prompt_path = prompt_path or PROMPT_PATH

    def generate_facet_candidates(
        self, category: str, products: list[dict[str, Any]], prompt_version: str
    ) -> dict[str, Any]:
        compact = os.getenv("MODEL1_COMPACT_PROMPT", "false").casefold() == "true"
        prompt = (
            _build_compact_prompt(category, products, prompt_version)
            if compact
            else _build_prompt(self.prompt_path, category, products, prompt_version)
        )
        body = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "think": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.endpoint}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
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

    def __init__(
        self,
        model: str,
        endpoint: str = "https://api.openai.com/v1",
        api_key: str = "",
        prompt_path: Path | None = None,
    ) -> None:
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.prompt_path = prompt_path or PROMPT_PATH

    def generate_facet_candidates(
        self, category: str, products: list[dict[str, Any]], prompt_version: str
    ) -> dict[str, Any]:
        prompt = _build_prompt(self.prompt_path, category, products, prompt_version)
        body = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.endpoint}/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
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

    def __init__(
        self,
        model: str,
        prompt_path: Path | None = None,
        max_new_tokens: int | None = None,
    ) -> None:
        self.model = model
        self.prompt_path = prompt_path or PROMPT_PATH
        self.max_new_tokens = max_new_tokens or int(
            os.getenv("MODEL1_MAX_NEW_TOKENS", "1024")
        )
        self.use_chat_template = (
            os.getenv("MODEL1_USE_CHAT_TEMPLATE", "true").casefold() == "true"
        )
        self.trust_remote_code = (
            os.getenv("MODEL1_TRUST_REMOTE_CODE", "false").casefold() == "true"
        )
        self._pipeline = None

    def _get_pipeline(self):
        if self._pipeline is None:
            try:
                from transformers import AutoTokenizer, pipeline

                tokenizer = AutoTokenizer.from_pretrained(
                    self.model,
                    use_fast=False,
                    trust_remote_code=self.trust_remote_code,
                )
                self._pipeline = pipeline(
                    "text-generation",
                    model=self.model,
                    tokenizer=tokenizer,
                    trust_remote_code=self.trust_remote_code,
                )
            except Exception as exc:
                raise ModelCallError(f"Transformers model unavailable: {exc}") from exc
        return self._pipeline

    @staticmethod
    def _generated_text(output: Any) -> str:
        generated = (
            output[0].get("generated_text", "")
            if isinstance(output, list) and output
            else ""
        )
        if isinstance(generated, str):
            return generated
        if isinstance(generated, list):
            for message in reversed(generated):
                if isinstance(message, dict) and message.get("role") == "assistant":
                    return str(message.get("content", ""))
            if generated and isinstance(generated[-1], dict):
                return str(generated[-1].get("content", ""))
        return str(generated or "")

    def generate_facet_candidates(
        self, category: str, products: list[dict[str, Any]], prompt_version: str
    ) -> dict[str, Any]:
        compact = os.getenv("MODEL1_COMPACT_PROMPT", "false").casefold() == "true"
        prompt = (
            _build_compact_prompt(category, products, prompt_version)
            if compact
            else _build_prompt(self.prompt_path, category, products, prompt_version)
        )
        try:
            generator = self._get_pipeline()
            tokenizer = getattr(generator, "tokenizer", None)
            has_chat_template = bool(getattr(tokenizer, "chat_template", None))
            input_payload: Any = prompt
            if self.use_chat_template and has_chat_template:
                input_payload = [{"role": "user", "content": prompt}]
            output = generator(
                input_payload,
                max_new_tokens=self.max_new_tokens,
                truncation=True,
                do_sample=False,
                return_full_text=False,
            )
            raw_output = self._generated_text(output)
        except ModelCallError:
            raise
        except Exception as exc:
            raise ModelCallError(f"Transformers generation failed: {exc}") from exc
        return _parse_json_response(raw_output, "Transformers")


def create_model_adapter(
    provider: str,
    model: str,
    endpoint: str = "",
    api_key: str = "",
    prompt_path: Path | None = None,
) -> ModelAdapter:
    provider_key = provider.strip().casefold()
    if provider_key == "ollama":
        return OllamaAdapter(
            model,
            endpoint=endpoint or "http://localhost:11434",
            prompt_path=prompt_path,
        )
    if provider_key in {"openai", "openai_compatible", "vllm", "lm_studio"}:
        return OpenAICompatibleAdapter(
            model,
            endpoint=endpoint or "https://api.openai.com/v1",
            api_key=api_key,
            prompt_path=prompt_path,
        )
    if provider_key in {"transformers", "huggingface", "hf"}:
        return TransformersAdapter(model, prompt_path=prompt_path)
    return UnavailableModelAdapter()


class MockModelAdapter:
    """Test-only adapter; never used by the production Model 1 runner."""

    provider = "mock-test"
    model = "mock-facet-v0"

    def generate_facet_candidates(
        self, category: str, products: list[dict[str, Any]], prompt_version: str
    ) -> dict[str, Any]:
        first = products[0]
        return {
            "category_key": category,
            "category_name": first.get("category_name", ""),
            "facets": [
                {
                    "facet_id_candidate": "form",
                    "name": "product_form",
                    "definition": "Observed product form candidate",
                    "values": [{"value": first.get("product_form", ""), "aliases": []}],
                    "evidence": [
                        {
                            "source_product_id": first["source_product_id"],
                            "source_field": "product_form",
                            "source_text": first.get("product_form", ""),
                        }
                    ],
                }
            ],
        }


def sample_products(
    frame: pd.DataFrame, max_per_category: int = 24, seed: int = 42
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=MODEL_COLUMNS)
    data = frame.fillna("").copy()
    for column in (
        "source_product_id",
        "product_type",
        "source_category_path",
        "product_form",
        "functional_ingredients",
    ):
        if column not in data.columns:
            data[column] = ""
    for column in data.columns:
        data[column] = data[column].astype(str).str.strip()
    classified = data.apply(classify_v2_1, axis=1, result_type="expand")
    # The category name/key are derived from the same V2.1 classifier used by mapping.
    data["category_key"] = [
        f"health-functional-food:{key.lower()}" if row["product_type"] else "UNMAPPED"
        for (_, row), key in zip(data.iterrows(), classified[0])
    ]
    data["category_name"] = classified[1].values
    data["regulated_function"] = data.get("main_functionality", "")
    sampled: list[pd.DataFrame] = []
    for category_key, group in data[data["category_key"] != "UNMAPPED"].groupby(
        "category_key", sort=True
    ):
        group = group.sample(frac=1, random_state=seed).drop_duplicates(
            subset=["source_product_id"]
        )
        slots = max(1, max_per_category // 3)
        selected = (
            pd.concat(
                [
                    group.sort_values(
                        "source_category_path"
                        if "source_category_path" in group
                        else "product_type"
                    ).head(slots),
                    group[group.get("product_form", "") != ""].head(slots),
                    group[group.get("functional_ingredients", "") != ""].head(slots),
                ]
            )
            .drop_duplicates(subset=["source_product_id"])
            .head(max_per_category)
        )
        selected = selected.copy()
        selected["sampling_reason"] = "category/source/form/ingredient diversity sample"
        sampled.append(selected)
    result = pd.concat(sampled, ignore_index=True) if sampled else pd.DataFrame()
    return result.reindex(columns=MODEL_COLUMNS, fill_value="")


def parse_model_output(
    payload: Any, input_products: pd.DataFrame
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    failures: list[dict[str, str]] = []
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict) or not isinstance(payload.get("facets"), list):
            raise TypeError("root/facets schema invalid")
        if "source_product_id" not in input_products.columns:
            raise TypeError("input/source_product_id column missing")
        category_key = str(payload.get("category_key", ""))
        category_name = str(payload.get("category_name", ""))
        valid_ids = set(input_products["source_product_id"].astype(str))
        rows = []
        seen_facets: set[str] = set()
        for facet_index, facet in enumerate(payload["facets"]):
            if not isinstance(facet, dict):
                failures.append(
                    {"failure_type": "INVALID_FACET", "detail": str(facet_index)}
                )
                continue
            name = str(
                facet.get("name")
                or facet.get("facet_name")
                or facet.get("facet_key", "")
            ).strip()
            if not name:
                failures.append(
                    {"failure_type": "EMPTY_FACET", "detail": "facet name is empty"}
                )
                continue
            facet_id_candidate = str(facet.get("facet_id_candidate", "")).strip()
            if facet_id_candidate.isdigit():
                normalized_name = name.casefold()
                recovered = KNOWN_FACET_NAMES.get(normalized_name)
                if recovered is None:
                    failures.append(
                        {
                            "failure_type": "INVALID_FACET_ID",
                            "detail": f"numeric facet id with unknown name: {facet_id_candidate}/{name}",
                        }
                    )
                    continue
                facet_id_candidate = recovered
            if name in seen_facets:
                failures.append({"failure_type": "DUPLICATE_FACET", "detail": name})
                continue
            seen_facets.add(name)
            values = facet.get("values") or []
            if not values and facet.get("value") not in (None, ""):
                values = [
                    {
                        "value": facet.get("value", ""),
                        "aliases": facet.get("aliases", []),
                    }
                ]
            if not values:
                failures.append({"failure_type": "EMPTY_VALUE", "detail": name})
                continue
            valid_values = []
            for value_index, value in enumerate(values):
                if not isinstance(value, dict):
                    failures.append(
                        {
                            "failure_type": "INVALID_VALUE",
                            "detail": f"{name}[{value_index}]",
                        }
                    )
                    continue
                value_text = str(value.get("value") or "").strip()
                if not value_text:
                    failures.append({"failure_type": "EMPTY_VALUE", "detail": name})
                    continue
                valid_values.append((value, value_text))
            if not valid_values:
                continue
            evidence = facet.get("evidence") or []
            if not evidence:
                evidence = [
                    item
                    for value, _ in valid_values
                    for item in (value.get("evidence") or [])
                ]
            if not evidence:
                failures.append({"failure_type": "EVIDENCE_MISSING", "detail": name})
                continue
            for evidence_index, item in enumerate(evidence):
                if not isinstance(item, dict):
                    failures.append(
                        {
                            "failure_type": "INVALID_EVIDENCE",
                            "detail": f"{name}[{evidence_index}]",
                        }
                    )
                    continue
                source_id = str(
                    item.get("source_product_id") or item.get("product_id") or ""
                ).strip()
                source_text = str(
                    item.get("source_text") or item.get("evidence_text") or ""
                ).strip()
                source_field = str(item.get("source_field") or "").strip()
                if source_id not in valid_ids:
                    failures.append(
                        {"failure_type": "HALLUCINATED_EVIDENCE", "detail": source_id}
                    )
                    continue
                if not source_text:
                    failures.append(
                        {"failure_type": "EVIDENCE_TEXT_MISSING", "detail": source_id}
                    )
                    continue
                if source_field not in input_products.columns:
                    source_field = ""
                if not source_field:
                    source_row = input_products.loc[
                        input_products["source_product_id"].astype(str) == source_id
                    ].iloc[0]
                    source_field = next(
                        (
                            column
                            for column in input_products.columns
                            if source_text in str(source_row.get(column, ""))
                        ),
                        "",
                    )
                if not source_field:
                    failures.append(
                        {
                            "failure_type": "EVIDENCE_FIELD_UNRESOLVED",
                            "detail": source_id,
                        }
                    )
                    continue
                allowed = str(
                    input_products.loc[
                        input_products["source_product_id"].astype(str) == source_id,
                        source_field,
                    ].iloc[0]
                )
                if source_text not in allowed:
                    failures.append(
                        {"failure_type": "HALLUCINATED_EVIDENCE", "detail": source_id}
                    )
                    continue
                for value, value_text in valid_values:
                    aliases = value.get("aliases") or []
                    if not isinstance(aliases, list):
                        aliases = [aliases]
                    rows.append(
                        {
                            "category_key": category_key,
                            "category_name": category_name,
                            "facet_id_candidate": facet_id_candidate,
                            "name": name,
                            "definition": facet.get("definition", ""),
                            "value": value_text,
                            "alias": "|".join(
                                str(alias).strip()
                                for alias in aliases
                                if str(alias).strip()
                            ),
                            "source_product_id": source_id,
                            "source_field": source_field,
                            "source_text": source_text,
                            "status": "PROVISIONAL_MODEL_OUTPUT",
                        }
                    )
        return pd.DataFrame(rows, columns=MODEL_OUTPUT_COLUMNS), failures
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        failures.append(
            {"failure_type": "SCHEMA_VALIDATION_FAILED", "detail": str(exc)}
        )
        return pd.DataFrame(columns=MODEL_OUTPUT_COLUMNS), failures


def discover_model_config() -> ModelConfig | None:
    provider = os.getenv("MODEL1_PROVIDER", "").strip()
    model = os.getenv("MODEL1_MODEL", "").strip()
    if provider and model:
        return ModelConfig(provider, model, os.getenv("MODEL1_API_KEY_ENV", ""))
    return None

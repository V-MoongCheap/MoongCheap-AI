"""Run a small local Hugging Face candidate smoke test.

This checks model-weight availability, tokenizer compatibility, MPS/CPU loading,
and one bounded generation. It is not a quality benchmark.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


DEFAULT_MODELS = (
    "Infinity08/KAWK-500M-Korean-Instruct-v1",
    "sh-024/LFM2.5-1.2B-Instruct-Korean",
    "kakaocorp/kanana-nano-2.1b-instruct",
    "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct",
    "Qwen/Qwen2.5-3B-Instruct",
    "google/gemma-3-4b-it",
)


def _prompt(tokenizer, user_text: str) -> str:
    if getattr(tokenizer, "chat_template", None):
        return tokenizer.apply_chat_template(
            [{"role": "user", "content": user_text}],
            tokenize=False,
            add_generation_prompt=True,
        )
    return user_text


def check_model(model_id: str, *, local_files_only: bool, max_new_tokens: int) -> dict[str, object]:
    started = time.perf_counter()
    try:
        import torch
        from huggingface_hub import snapshot_download
        from transformers import AutoModelForCausalLM, AutoTokenizer

        device = "mps" if torch.backends.mps.is_available() else "cpu"
        model_path = snapshot_download(model_id, local_files_only=local_files_only)
        tokenizer = AutoTokenizer.from_pretrained(
            model_path,
            local_files_only=True,
            trust_remote_code=True,
            use_fast=False if "LFM2.5" in model_id else True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            local_files_only=True,
            trust_remote_code=True,
            dtype=torch.float16 if device == "mps" else torch.float32,
            low_cpu_mem_usage=True,
        ).to(device)
        model.eval()
        prompt = _prompt(
            tokenizer,
            "다음 문장을 JSON으로만 짧게 분류해줘: 무설탕이고 캡슐 형태의 제품을 원해요.",
        )
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
        inputs = {key: value.to(device) for key, value in inputs.items()}
        with torch.inference_mode():
            output = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id or tokenizer.pad_token_id,
            )
        generated = output[0, inputs["input_ids"].shape[1] :]
        text = tokenizer.decode(generated, skip_special_tokens=True)
        return {
            "model": model_id,
            "status": "OK",
            "device": device,
            "input_tokens": int(inputs["input_ids"].shape[1]),
            "output_tokens": int(generated.shape[0]),
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "output_preview": text[:500],
        }
    except Exception as error:  # Candidate availability diagnostics must continue.
        return {
            "model": model_id,
            "status": "FAILED",
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "error_type": type(error).__name__,
            "error": str(error)[:1000],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--online", action="store_true", help="Allow downloading missing weights")
    parser.add_argument("--max-new-tokens", type=int, default=64)
    args = parser.parse_args()
    models = tuple(args.models or DEFAULT_MODELS)
    results = [
        check_model(model, local_files_only=not args.online, max_new_tokens=args.max_new_tokens)
        for model in models
    ]
    payload = {"status": "COMPLETED", "local_files_only": not args.online, "results": results}
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if all(item["status"] == "OK" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

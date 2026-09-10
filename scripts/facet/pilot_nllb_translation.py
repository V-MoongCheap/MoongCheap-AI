"""Local research-only translation comparison; never replaces production inputs."""

import argparse
import json
import time
from pathlib import Path


MODEL = "facebook/nllb-200-distilled-600M"
REVISION = "f8d333a098d19b4fd9a8b18f94170487ad3f821d"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, default=Path("data/models/nllb-600m"))
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--input", type=Path, default=Path("data/interim/facet_evidence/kuaiseach_health_queries_ko_v2.parquet"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/kuaisearch_translation_repair_v2/nllb_pilot.csv"))
    args = parser.parse_args()
    if args.download_only:
        from huggingface_hub import snapshot_download
        snapshot_download(MODEL, revision=REVISION, local_dir=args.model_dir, token=False, allow_patterns=["*.json", "pytorch_model.bin", "sentencepiece.bpe.model", "README.md"])
        print({"downloaded": str(args.model_dir), "model": MODEL, "revision": REVISION}, flush=True)
        return

    import pandas as pd
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    from repair_kuaisearch_translation import quality_flags

    torch.set_num_threads(4)
    frame = pd.read_parquet(args.input).fillna("")
    known = frame[frame.source_record_id.astype(str).isin(["13304", "208240", "379597", "409567"])]
    accepted = frame[frame.repair_status.eq("AUTOMATED_CHECKS_PASSED")]
    sample = pd.concat([known, accepted.sample(min(20, len(accepted)), random_state=7), frame.sample(20, random_state=42)]).drop_duplicates("query_raw")
    tokenizer = AutoTokenizer.from_pretrained(args.model_dir, src_lang="zho_Hans", local_files_only=True, trust_remote_code=False)
    model = AutoModelForSeq2SeqLM.from_pretrained(args.model_dir, local_files_only=True, trust_remote_code=False, weights_only=True, use_safetensors=False)
    model.eval()
    started = time.perf_counter()
    rows = []
    for start in range(0, len(sample), 4):
        batch = sample.iloc[start:start + 4]
        inputs = tokenizer(batch.query_raw.tolist(), return_tensors="pt", padding=True, truncation=True, max_length=256)
        with torch.inference_mode():
            output = model.generate(**inputs, forced_bos_token_id=tokenizer.convert_tokens_to_ids("kor_Hang"), max_new_tokens=96, num_beams=4)
        translations = tokenizer.batch_decode(output, skip_special_tokens=True)
        for row, translated in zip(batch.to_dict("records"), translations, strict=True):
            row["nllb_translation"] = translated
            row["nllb_flags"] = "|".join(quality_flags(row["query_raw"], translated))
            rows.append(row)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(args.output, index=False, encoding="utf-8-sig")
        print({"processed": len(rows), "rows": len(sample)}, flush=True)
    report = {"model": MODEL, "revision": REVISION, "license": "CC-BY-NC-4.0", "usage": "LOCAL_RESEARCH_PILOT_ONLY", "rows": len(rows), "runtime_seconds": round(time.perf_counter() - started, 3), "accuracy": None}
    args.output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()

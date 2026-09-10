"""Repair flagged translations with checkpoints and an immutable source snapshot."""

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from audit_kuaisearch_translation import screen
from translate_kuaisearch import (
    GLOSSARY,
    _translate_batch,
    normalize_translation,
    numeric_tokens,
    transliterate_cjk_for_review,
)


def quality_flags(raw, translated):
    flags = [flag for flag in screen(raw, translated)[0].split("|") if flag]
    if "NUMBER_MISSING" in flags and numeric_tokens(raw).issubset(numeric_tokens(translated)):
        flags.remove("NUMBER_MISSING")
    for word, meanings in GLOSSARY.items():
        if word in raw and not any(meaning in translated for meaning in meanings):
            flags.append("TERM_MISMATCH:" + word)
    return flags


def blocking_quality_flags(flags):
    """Return errors that make a candidate unsafe to replace automatically.

    CJK_REMAINS is blocking because downstream Korean facet extraction must not
    receive untranslated Chinese text. Proper names are handled by transliteration
    in the model prompt or remain explicitly reviewable.
    """
    return list(flags)


def is_source_nontranslatable(raw):
    """Return true for identifiers already expressed without Chinese/Korean text."""
    value = str(raw).strip()
    return bool(value) and not re.search(r"[\u4e00-\u9fff]", value) and not re.search(r"[\uac00-\ud7a3]", value)


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def checkpoint(frame, output):
    temporary = output.with_suffix(".tmp.parquet")
    frame.to_parquet(temporary, index=False)
    # Windows readers can briefly hold the destination open during inspection.
    for attempt in range(6):
        try:
            temporary.replace(output)
            break
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.2 * (attempt + 1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/interim/facet_evidence/kuaiseach_health_queries_ko.parquet"))
    parser.add_argument("--output", type=Path, default=Path("data/interim/facet_evidence/kuaiseach_health_queries_ko_v2.parquet"))
    parser.add_argument("--model", default="qwen3:4b")
    parser.add_argument("--endpoint", default="http://localhost:11434")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--passes", type=int, default=2)
    parser.add_argument("--checkpoint-every", type=int, default=10, help="Save the parquet checkpoint every N batches")
    parser.add_argument("--priority-source-ids", default="", help="Comma-separated source IDs to process first")
    parser.add_argument("--finalize-only", action="store_true", help="Export checkpoint reports without calling a model")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Use a separate output to preserve original translations")
    if args.batch_size < 1 or args.passes < 1 or args.checkpoint_every < 1 or (args.limit is not None and args.limit < 1):
        parser.error("batch-size, passes, checkpoint-every and limit must be positive")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(args.input.read_bytes()).hexdigest()
    metadata = args.output.with_suffix(".metadata.json")
    if args.output.exists():
        previous_meta = json.loads(metadata.read_text(encoding="utf-8"))
        if previous_meta["source_sha256"] != source_hash:
            raise ValueError("Source snapshot changed; use a new output")
        frame = pd.read_parquet(args.output).fillna("")
        if "repair_blocking_flags" not in frame:
            frame["repair_blocking_flags"] = ""
    else:
        frame = pd.read_parquet(args.input).fillna("")
        frame["translation_original"] = frame.query_translated
        frame["repair_status"] = "NOT_REPROCESSED"
        frame["repair_model"] = ""
        frame["repair_flags"] = ""
        frame["repair_blocking_flags"] = ""
        frame["repair_candidate"] = ""
        frame["repair_attempts"] = 0
        write_json(metadata, {"version": "translation_repair_v2", "source_sha256": source_hash, "source": str(args.input), "accuracy": None})
    # Apply source-grounded glossary corrections before spending a model call.
    # This also fixes rows where the previous translation simply echoed a known
    # Chinese product term.
    for index, row in frame.iterrows():
        normalized, changes = normalize_translation(str(row.query_raw), str(row.query_translated))
        if changes and normalized != str(row.query_translated).strip():
            frame.at[index, "query_translated"] = normalized
            frame.at[index, "repair_candidate"] = normalized
            frame.at[index, "repair_model"] = "source-grounded-normalizer"
            frame.at[index, "repair_status"] = "AUTOMATED_NORMALIZATION"
    flags = [quality_flags(str(row.query_raw), str(row.query_translated)) for row in frame.itertuples()]
    blocking_flags = [blocking_quality_flags(value) for value in flags]
    frame["repair_flags"] = ["|".join(value) for value in flags]
    # CJK_REMAINS is a hard check. Once a row passes all hard checks, do not send
    # it through the model again.
    candidates = [index for index, value in enumerate(blocking_flags) if value]
    # Correct known term errors and placeholders first; ambiguous names remain reviewable.
    priority_ids = set(args.priority_source_ids.split(",")) - {""}
    candidates.sort(key=lambda i: (str(frame.at[i, "source_record_id"]) not in priority_ids, not any(flag.startswith("TERM_MISMATCH") for flag in blocking_flags[i]), "PLACEHOLDER" not in blocking_flags[i], i))
    selected = candidates[:args.limit] if args.limit else candidates
    no_text = [i for i in selected if not re.search(r"[\w]", str(frame.at[i, "query_raw"]))]
    source_nontranslatable = [i for i in selected if is_source_nontranslatable(frame.at[i, "query_raw"])]
    frame.loc[no_text, "repair_status"] = "SOURCE_NONLEXICAL_REVIEW"
    frame.loc[source_nontranslatable, "repair_status"] = "SOURCE_NONTRANSLATABLE"
    frame.loc[source_nontranslatable, "repair_blocking_flags"] = ""
    nonlexical_indices = set(no_text) | set(source_nontranslatable)
    pending = [i for i in selected if i not in nonlexical_indices]
    # Repeated raw queries need one model call. Results are copied back to all
    # rows sharing the same source text after validation.
    raw_groups = {}
    for index in pending:
        raw_groups.setdefault(str(frame.at[index, "query_raw"]), []).append(index)
    pending = [indices[0] for indices in raw_groups.values()]
    started = time.perf_counter()
    calls = failures = consecutive_errors = 0
    journal = args.output.with_suffix(".attempts.jsonl")
    for pass_number in range(0 if args.finalize_only else args.passes):
        # Keep retry batches small enough for stable JSON, but do not fall back
        # to one model call per row on the second pass.
        batch_size = args.batch_size
        retry = []
        for start in range(0, len(pending), batch_size):
            indexes = pending[start:start + batch_size]
            rows = [{"source_record_id": str(i), "query_raw": str(frame.at[i, "query_raw"])} for i in indexes]
            calls += 1
            call_start = time.perf_counter()
            error = ""
            result = []
            try:
                result = _translate_batch(rows, args.model, args.endpoint, args.timeout)
                if not isinstance(result, list):
                    raise ValueError("translations must be a list")
                lookup = {}
                for item in result:
                    key = item.get("source_record_id")
                    if key not in {row["source_record_id"] for row in rows} or key in lookup:
                        raise ValueError("Unexpected or duplicate response ID")
                    lookup[key] = item.get("query_translated")
            except Exception as exc:
                error = str(exc)
                lookup = {}
            consecutive_errors = consecutive_errors + 1 if error else 0
            rejected = []
            for i in indexes:
                targets = raw_groups.get(str(frame.at[i, "query_raw"]), [i])
                value = lookup.get(str(i))
                normalized = normalize_translation(str(frame.at[i, "query_raw"]), value.strip())[0] if isinstance(value, str) else ""
                all_flags = quality_flags(str(frame.at[i, "query_raw"]), normalized) if isinstance(value, str) else ["MISSING_RESPONSE"]
                new_flags = blocking_quality_flags(all_flags)
                if isinstance(value, str) and normalized and "CJK_REMAINS" in new_flags:
                    fallback = transliterate_cjk_for_review(normalized)
                    fallback_flags = quality_flags(str(frame.at[i, "query_raw"]), fallback)
                    fallback_blocking = blocking_quality_flags(fallback_flags)
                    if "CJK_REMAINS" not in fallback_blocking:
                        normalized = fallback
                        all_flags = fallback_flags + ["CJK_FALLBACK_TRANSLITERATION"]
                        new_flags = fallback_blocking
                        frame.at[i, "repair_status"] = "TRANSLITERATED_REVIEW"
                for target in targets:
                    frame.at[target, "repair_attempts"] = int(frame.at[target, "repair_attempts"]) + 1
                    frame.at[target, "repair_candidate"] = normalized
                    frame.at[target, "repair_blocking_flags"] = "|".join(new_flags)
                    frame.at[target, "repair_model"] = args.model
                if not error and not new_flags:
                    for target in targets:
                        frame.at[target, "query_translated"] = normalized
                        if frame.at[target, "repair_status"] != "TRANSLITERATED_REVIEW":
                            frame.at[target, "repair_status"] = "AUTOMATED_CHECKS_PASSED"
                        frame.at[target, "repair_flags"] = "|".join(all_flags)
                else:
                    for target in targets:
                        frame.at[target, "repair_status"] = "NEEDS_REVIEW"
                    rejected.append({"row": i, "duplicate_rows": len(targets), "flags": new_flags})
                    retry.append(i)
            if error or rejected:
                failures += 1
            with journal.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"model": args.model, "rows": indexes, "response": result, "error": error, "rejected": rejected, "runtime_seconds": round(time.perf_counter() - call_start, 3)}, ensure_ascii=False) + "\n")
            is_last_batch = start + batch_size >= len(pending)
            if calls % args.checkpoint_every == 0 or is_last_batch:
                checkpoint(frame, args.output)
            progress = {"status": "RUNNING", "updated_at": datetime.now(timezone.utc).isoformat(), "pass": pass_number + 1, "processed": min(start + batch_size, len(pending)), "pass_rows": len(pending), "calls": calls, "repaired_total": int(frame.repair_status.eq("AUTOMATED_CHECKS_PASSED").sum()), "remaining_blocking": int(frame.repair_blocking_flags.ne("").sum()), "runtime_seconds": round(time.perf_counter() - started, 3)}
            write_json(args.output.with_suffix(".progress.json"), progress)
            print(progress, flush=True)
            if consecutive_errors >= 3:
                break
        pending = retry
        if not pending or consecutive_errors >= 3:
            break
    checkpoint(frame, args.output)
    review = frame[frame.repair_blocking_flags.ne("")]
    review.to_csv(args.output.with_suffix(".review.csv"), index=False, encoding="utf-8-sig")
    frame[frame.repair_status.eq("AUTOMATED_CHECKS_PASSED")].to_csv(args.output.with_suffix(".changes.csv"), index=False, encoding="utf-8-sig")
    report = {"status": "CHECKPOINT_EXPORTED" if args.finalize_only else "COMPLETED_WITH_REVIEW" if len(review) else "AUTOMATED_CHECKS_PASSED", "rows": len(frame), "selected": len(selected), "repaired_total": int(frame.repair_status.eq("AUTOMATED_CHECKS_PASSED").sum()), "remaining_blocking": len(review), "source_nonlexical": len(no_text), "source_nontranslatable": len(source_nontranslatable), "calls": calls, "failed_or_rejected_batches": failures, "runtime_seconds": round(time.perf_counter() - started, 3), "model": args.model, "accuracy": None}
    write_json(args.output.with_suffix(".report.json"), report)
    write_json(args.output.with_suffix(".progress.json"), report)
    print(report, flush=True)


if __name__ == "__main__":
    main()

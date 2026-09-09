"""Offline human annotation workflow for directional substitute-product pairs.

The SQLite state in this module is evaluation data.  It is deliberately
separate from Backend Demand state and must never create a runtime REVIEW
status or trigger another buyer question.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


GOLD_LABELS = (
    "SUBSTITUTABLE",
    "NOT_SUBSTITUTABLE",
    "INSUFFICIENT_EVIDENCE",
)

REASON_CODES = (
    "SOURCE_FUNCTION_COVERED",
    "SAME_PRIMARY_FUNCTION",
    "COMPATIBLE_PRODUCT_TYPE",
    "COMPATIBLE_FORM_AND_INTAKE",
    "SHARED_FUNCTIONAL_INGREDIENT",
    "SOURCE_FUNCTION_NOT_COVERED",
    "CATEGORY_MISMATCH",
    "NON_FINISHED_PRODUCT",
    "INCOMPATIBLE_FORM_OR_INTAKE",
    "SOURCE_EVIDENCE_MISSING",
    "CANDIDATE_EVIDENCE_MISSING",
    "FUNCTION_EVIDENCE_AMBIGUOUS",
    "RECORD_TYPE_AMBIGUOUS",
    "OTHER",
)


class AnnotationValidationError(ValueError):
    pass


def load_pair_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    required = {
        "pair_id",
        "source_product_id",
        "candidate_product_id",
        "source_product_name",
        "candidate_product_name",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise AnnotationValidationError(
            f"pair review input is missing columns: {', '.join(missing)}"
        )
    if frame.empty:
        raise AnnotationValidationError("pair review input must not be empty")
    if frame["pair_id"].eq("").any() or not frame["pair_id"].is_unique:
        raise AnnotationValidationError("pair_id must be non-empty and unique")
    return frame


def dataset_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_identifiers(values: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(str(value).strip() for value in values)
    if any(not value for value in normalized):
        raise AnnotationValidationError("reviewer identifiers must not be empty")
    if len(normalized) != len(set(normalized)):
        raise AnnotationValidationError("reviewer identifiers must be unique")
    return normalized


def _validated_decision(
    label: str,
    reason_codes: Iterable[str],
    critical_negative: bool,
) -> tuple[str, tuple[str, ...], bool]:
    normalized_label = str(label).strip()
    if normalized_label not in GOLD_LABELS:
        raise AnnotationValidationError(f"invalid gold label: {normalized_label}")
    normalized_reasons = tuple(
        dict.fromkeys(str(reason).strip() for reason in reason_codes if str(reason).strip())
    )
    invalid_reasons = sorted(set(normalized_reasons) - set(REASON_CODES))
    if invalid_reasons:
        raise AnnotationValidationError(
            f"invalid reason codes: {', '.join(invalid_reasons)}"
        )
    if not normalized_reasons:
        raise AnnotationValidationError("at least one reason code is required")
    if critical_negative and normalized_label != "NOT_SUBSTITUTABLE":
        raise AnnotationValidationError(
            "critical_negative is valid only for NOT_SUBSTITUTABLE"
        )
    return normalized_label, normalized_reasons, bool(critical_negative)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SubstituteAnnotationStore:
    """SQLite-backed, resumable two-reviewer plus adjudicator workflow."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assignments (
                    pair_id TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    reviewer_position INTEGER NOT NULL,
                    PRIMARY KEY (pair_id, reviewer_id),
                    UNIQUE (pair_id, reviewer_position)
                );
                CREATE TABLE IF NOT EXISTS annotations (
                    pair_id TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    reason_codes TEXT NOT NULL,
                    critical_negative INTEGER NOT NULL,
                    note TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL,
                    PRIMARY KEY (pair_id, reviewer_id),
                    FOREIGN KEY (pair_id, reviewer_id)
                        REFERENCES assignments(pair_id, reviewer_id)
                );
                CREATE TABLE IF NOT EXISTS adjudications (
                    pair_id TEXT PRIMARY KEY,
                    adjudicator_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    reason_codes TEXT NOT NULL,
                    critical_negative INTEGER NOT NULL,
                    note TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL
                );
                """
            )

    def _metadata(self) -> dict[str, str]:
        with self._connect() as connection:
            return {
                str(row["key"]): str(row["value"])
                for row in connection.execute("SELECT key, value FROM metadata")
            }

    @property
    def initialized(self) -> bool:
        return "dataset_fingerprint" in self._metadata()

    def initialize_assignments(
        self,
        pair_ids: Sequence[str],
        reviewer_ids: Sequence[str],
        fingerprint: str,
        *,
        reviews_per_pair: int = 2,
    ) -> dict[str, int]:
        pairs = tuple(str(pair_id).strip() for pair_id in pair_ids)
        if not pairs or any(not pair_id for pair_id in pairs):
            raise AnnotationValidationError("pair identifiers must not be empty")
        if len(pairs) != len(set(pairs)):
            raise AnnotationValidationError("pair identifiers must be unique")
        reviewers = _normalized_identifiers(reviewer_ids)
        if len(reviewers) < 3:
            raise AnnotationValidationError(
                "at least three reviewers are required for independent adjudication"
            )
        if reviews_per_pair != 2:
            raise AnnotationValidationError("exactly two reviewers per pair are required")

        metadata = self._metadata()
        if metadata:
            self.verify_dataset(pairs, fingerprint)
            if tuple(json.loads(metadata["reviewer_ids"])) != reviewers:
                raise AnnotationValidationError(
                    "reviewer roster differs from the initialized database"
                )
            return self.assignment_counts()

        with self._connect() as connection:
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                (
                    ("dataset_fingerprint", fingerprint),
                    ("pair_count", str(len(pairs))),
                    ("reviewer_ids", json.dumps(reviewers, ensure_ascii=False)),
                    ("reviews_per_pair", str(reviews_per_pair)),
                ),
            )
            assignments: list[tuple[str, str, int]] = []
            for index, pair_id in enumerate(pairs):
                for position in range(reviews_per_pair):
                    reviewer_id = reviewers[(index + position) % len(reviewers)]
                    assignments.append((pair_id, reviewer_id, position + 1))
            connection.executemany(
                """
                INSERT INTO assignments(pair_id, reviewer_id, reviewer_position)
                VALUES (?, ?, ?)
                """,
                assignments,
            )
        return self.assignment_counts()

    def verify_dataset(self, pair_ids: Sequence[str], fingerprint: str) -> None:
        metadata = self._metadata()
        if not metadata:
            raise AnnotationValidationError("annotation database is not initialized")
        if metadata.get("dataset_fingerprint") != fingerprint:
            raise AnnotationValidationError(
                "pair review file differs from the database's initialized dataset"
            )
        if int(metadata.get("pair_count", "-1")) != len(pair_ids):
            raise AnnotationValidationError("pair review row count differs from database")

    def reviewer_ids(self) -> tuple[str, ...]:
        metadata = self._metadata()
        return tuple(json.loads(metadata.get("reviewer_ids", "[]")))

    def assignment_counts(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT reviewer_id, COUNT(*) AS assigned
                FROM assignments
                GROUP BY reviewer_id
                ORDER BY reviewer_id
                """
            )
        return {str(row["reviewer_id"]): int(row["assigned"]) for row in rows}

    def assigned_pair_ids(self, reviewer_id: str) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT pair_id FROM assignments
                WHERE reviewer_id = ?
                ORDER BY rowid
                """,
                (reviewer_id,),
            )
        return tuple(str(row["pair_id"]) for row in rows)

    def reviewed_pair_ids(self, reviewer_id: str) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT pair_id FROM annotations WHERE reviewer_id = ?",
                (reviewer_id,),
            )
        return {str(row["pair_id"]) for row in rows}

    def annotation(self, pair_id: str, reviewer_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT pair_id, reviewer_id, label, reason_codes,
                       critical_negative, note, reviewed_at
                FROM annotations
                WHERE pair_id = ? AND reviewer_id = ?
                """,
                (pair_id, reviewer_id),
            ).fetchone()
        return self._annotation_row(row) if row else None

    @staticmethod
    def _annotation_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "pair_id": str(row["pair_id"]),
            "reviewer_id": str(row["reviewer_id"]),
            "label": str(row["label"]),
            "reason_codes": tuple(json.loads(row["reason_codes"])),
            "critical_negative": bool(row["critical_negative"]),
            "note": str(row["note"]),
            "reviewed_at": str(row["reviewed_at"]),
        }

    def annotations_for_pair(self, pair_id: str) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT pair_id, reviewer_id, label, reason_codes,
                       critical_negative, note, reviewed_at
                FROM annotations
                WHERE pair_id = ?
                ORDER BY reviewer_id
                """,
                (pair_id,),
            ).fetchall()
        return tuple(self._annotation_row(row) for row in rows)

    def reviewers_for_pair(self, pair_id: str) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT reviewer_id FROM assignments
                WHERE pair_id = ? ORDER BY reviewer_position
                """,
                (pair_id,),
            )
        return tuple(str(row["reviewer_id"]) for row in rows)

    def save_annotation(
        self,
        pair_id: str,
        reviewer_id: str,
        label: str,
        reason_codes: Iterable[str],
        critical_negative: bool,
        note: str = "",
    ) -> None:
        label, reasons, critical = _validated_decision(
            label, reason_codes, critical_negative
        )
        with self._connect() as connection:
            assignment = connection.execute(
                """
                SELECT 1 FROM assignments
                WHERE pair_id = ? AND reviewer_id = ?
                """,
                (pair_id, reviewer_id),
            ).fetchone()
            if assignment is None:
                raise AnnotationValidationError(
                    "reviewer is not assigned to this pair"
                )
            connection.execute(
                """
                INSERT INTO annotations(
                    pair_id, reviewer_id, label, reason_codes,
                    critical_negative, note, reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pair_id, reviewer_id) DO UPDATE SET
                    label = excluded.label,
                    reason_codes = excluded.reason_codes,
                    critical_negative = excluded.critical_negative,
                    note = excluded.note,
                    reviewed_at = excluded.reviewed_at
                """,
                (
                    pair_id,
                    reviewer_id,
                    label,
                    json.dumps(reasons, ensure_ascii=False),
                    int(critical),
                    str(note).strip(),
                    _utc_now(),
                ),
            )
            connection.execute(
                "DELETE FROM adjudications WHERE pair_id = ?",
                (pair_id,),
            )

    def conflict_pair_ids(self, *, pending_only: bool = True) -> tuple[str, ...]:
        condition = "AND j.pair_id IS NULL" if pending_only else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT a.pair_id
                FROM annotations a
                LEFT JOIN adjudications j ON j.pair_id = a.pair_id
                GROUP BY a.pair_id
                HAVING COUNT(*) = 2 AND COUNT(DISTINCT a.label) > 1
                    {condition}
                ORDER BY a.pair_id
                """
            ).fetchall()
        return tuple(str(row["pair_id"]) for row in rows)

    def save_adjudication(
        self,
        pair_id: str,
        adjudicator_id: str,
        label: str,
        reason_codes: Iterable[str],
        critical_negative: bool,
        note: str,
    ) -> None:
        label, reasons, critical = _validated_decision(
            label, reason_codes, critical_negative
        )
        reviewer_ids = self.reviewers_for_pair(pair_id)
        if len(self.annotations_for_pair(pair_id)) != 2:
            raise AnnotationValidationError(
                "two independent annotations are required before adjudication"
            )
        labels = {row["label"] for row in self.annotations_for_pair(pair_id)}
        if len(labels) != 2:
            raise AnnotationValidationError(
                "adjudication is allowed only when reviewer labels disagree"
            )
        if adjudicator_id not in self.reviewer_ids():
            raise AnnotationValidationError("adjudicator is not in the reviewer roster")
        if adjudicator_id in reviewer_ids:
            raise AnnotationValidationError(
                "adjudicator must not be one of this pair's reviewers"
            )
        normalized_note = str(note).strip()
        if not normalized_note:
            raise AnnotationValidationError("adjudication note is required")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO adjudications(
                    pair_id, adjudicator_id, label, reason_codes,
                    critical_negative, note, reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pair_id) DO UPDATE SET
                    adjudicator_id = excluded.adjudicator_id,
                    label = excluded.label,
                    reason_codes = excluded.reason_codes,
                    critical_negative = excluded.critical_negative,
                    note = excluded.note,
                    reviewed_at = excluded.reviewed_at
                """,
                (
                    pair_id,
                    adjudicator_id,
                    label,
                    json.dumps(reasons, ensure_ascii=False),
                    int(critical),
                    normalized_note,
                    _utc_now(),
                ),
            )

    def adjudication(self, pair_id: str) -> dict[str, Any] | None:
        return self._all_adjudications().get(pair_id)

    def _all_annotations(self) -> dict[str, list[dict[str, Any]]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT pair_id, reviewer_id, label, reason_codes,
                       critical_negative, note, reviewed_at
                FROM annotations ORDER BY pair_id, reviewer_id
                """
            ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            annotation = self._annotation_row(row)
            grouped.setdefault(annotation["pair_id"], []).append(annotation)
        return grouped

    def _all_adjudications(self) -> dict[str, dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT pair_id, adjudicator_id, label, reason_codes,
                       critical_negative, note, reviewed_at
                FROM adjudications ORDER BY pair_id
                """
            ).fetchall()
        return {
            str(row["pair_id"]): {
                "pair_id": str(row["pair_id"]),
                "adjudicator_id": str(row["adjudicator_id"]),
                "label": str(row["label"]),
                "reason_codes": tuple(json.loads(row["reason_codes"])),
                "critical_negative": bool(row["critical_negative"]),
                "note": str(row["note"]),
                "reviewed_at": str(row["reviewed_at"]),
            }
            for row in rows
        }

    def progress_summary(self) -> dict[str, Any]:
        annotations = self._all_annotations()
        adjudications = self._all_adjudications()
        with self._connect() as connection:
            total_pairs = int(
                connection.execute(
                    "SELECT COUNT(DISTINCT pair_id) FROM assignments"
                ).fetchone()[0]
            )
            assigned_judgments = int(
                connection.execute("SELECT COUNT(*) FROM assignments").fetchone()[0]
            )
        completed_judgments = sum(len(values) for values in annotations.values())
        fully_reviewed = [values for values in annotations.values() if len(values) == 2]
        agreements = sum(len({row["label"] for row in values}) == 1 for values in fully_reviewed)
        conflicts = sum(len({row["label"] for row in values}) == 2 for values in fully_reviewed)
        adjudicated = sum(pair_id in adjudications for pair_id in self.conflict_pair_ids(pending_only=False))
        return {
            "total_pairs": total_pairs,
            "assigned_judgments": assigned_judgments,
            "completed_judgments": completed_judgments,
            "pending_judgments": assigned_judgments - completed_judgments,
            "fully_reviewed_pairs": len(fully_reviewed),
            "agreement_pairs": agreements,
            "conflict_pairs": conflicts,
            "adjudicated_pairs": adjudicated,
            "gold_complete_pairs": agreements + adjudicated,
        }

    def export_gold(self, pairs: pd.DataFrame, output_path: Path) -> dict[str, Any]:
        output = pairs.copy()
        annotations = self._all_annotations()
        adjudications = self._all_adjudications()
        statuses: list[str] = []
        for index, row in output.iterrows():
            pair_id = str(row["pair_id"])
            decisions = annotations.get(pair_id, [])
            gold_label = ""
            reason_codes: tuple[str, ...] = ()
            critical_negative: bool | None = None
            adjudicator = ""
            reviewed_at = ""
            if len(decisions) < 2:
                status = "PENDING_REVIEW"
            elif len({decision["label"] for decision in decisions}) == 1:
                status = "AGREEMENT"
                gold_label = decisions[0]["label"]
                reason_codes = tuple(sorted({
                    reason
                    for decision in decisions
                    for reason in decision["reason_codes"]
                }))
                critical_negative = any(
                    decision["critical_negative"] for decision in decisions
                )
                reviewed_at = max(decision["reviewed_at"] for decision in decisions)
            elif pair_id in adjudications:
                status = "ADJUDICATED"
                decision = adjudications[pair_id]
                gold_label = decision["label"]
                reason_codes = decision["reason_codes"]
                critical_negative = decision["critical_negative"]
                adjudicator = decision["adjudicator_id"]
                reviewed_at = decision["reviewed_at"]
            else:
                status = "NEEDS_ADJUDICATION"

            reviewers = sorted(decision["reviewer_id"] for decision in decisions)
            output.at[index, "gold_label"] = gold_label
            output.at[index, "label_reason_codes"] = " | ".join(reason_codes)
            output.at[index, "critical_negative"] = (
                "" if critical_negative is None else str(critical_negative).lower()
            )
            output.at[index, "reviewer_1"] = reviewers[0] if reviewers else ""
            output.at[index, "reviewer_2"] = reviewers[1] if len(reviewers) > 1 else ""
            output.at[index, "adjudicator"] = adjudicator
            output.at[index, "reviewed_at"] = reviewed_at
            statuses.append(status)
        output["annotation_status"] = statuses
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        output.to_csv(temporary, index=False, encoding="utf-8-sig")
        temporary.replace(output_path)
        counts = output["annotation_status"].value_counts().to_dict()
        return {
            "rows": len(output),
            "gold_rows": int(output["gold_label"].ne("").sum()),
            "status_counts": {str(key): int(value) for key, value in counts.items()},
            "output": str(output_path),
        }

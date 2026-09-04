"""Internal clustering inputs backed by the Backend-owned ERD v2.

These models describe only the fields that the clustering step needs to read.
They are not Backend DTOs and intentionally contain no assignment policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


def _parse_timestamptz(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{field_name} must be an ISO 8601 timestamp") from error
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError(f"{field_name} must be a datetime or ISO 8601 string")

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone information")
    return parsed


def _parse_optional_timestamptz(value: Any, field_name: str) -> datetime | None:
    if value is None:
        return None
    return _parse_timestamptz(value, field_name)


@dataclass(frozen=True, slots=True)
class DemandInput:
    id: int
    catalog_id: int
    created_at: datetime
    updated_at: datetime
    demand_board_id: int | None = None
    desired_price_min: int | None = None
    desired_price_max: int | None = None
    quantity: int | None = None
    is_substitutable: bool | None = None
    status: str | None = None
    label: str | None = None
    desire_end_at: datetime | None = None
    processed_at: datetime | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> DemandInput:
        return cls(
            id=value["id"],
            catalog_id=value["catalog_id"],
            created_at=_parse_timestamptz(value["created_at"], "created_at"),
            updated_at=_parse_timestamptz(value["updated_at"], "updated_at"),
            demand_board_id=value.get("demand_board_id"),
            desired_price_min=value.get("desired_price_min"),
            desired_price_max=value.get("desired_price_max"),
            quantity=value.get("quantity"),
            is_substitutable=value.get("is_substitutable"),
            status=value.get("status"),
            label=value.get("label"),
            desire_end_at=_parse_optional_timestamptz(
                value.get("desire_end_at"), "desire_end_at"
            ),
            processed_at=_parse_optional_timestamptz(
                value.get("processed_at"), "processed_at"
            ),
        )


@dataclass(frozen=True, slots=True)
class DemandBoardInput:
    id: int
    catalog_id: int
    participant_count: int
    created_at: datetime
    sale_end_at: datetime
    price_min: int | None = None
    price_max: int | None = None
    status: str = "GB_GATHERING"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> DemandBoardInput:
        return cls(
            id=value["id"],
            catalog_id=value["catalog_id"],
            participant_count=value["participant_count"],
            created_at=_parse_timestamptz(value["created_at"], "created_at"),
            sale_end_at=_parse_timestamptz(
                value["sale_end_at"], "sale_end_at"
            ),
            price_min=value.get("price_min"),
            price_max=value.get("price_max"),
            status=value.get("status", "GB_GATHERING"),
        )

"""Versioned, metadata-only ingestion contract. Prompts are deliberately excluded."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")]
TokenCount = Annotated[int, Field(strict=True, ge=0, le=1_000_000_000)]


class UsageEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schema_version: Literal["1"] = "1"
    request_id: Identifier
    timestamp: datetime
    provider: Identifier
    model: Identifier
    team: Identifier
    environment: Literal["production", "staging", "development"] = "production"
    input_tokens: TokenCount
    output_tokens: TokenCount
    cached_input_tokens: TokenCount = 0
    latency_ms: Annotated[float, Field(ge=0, le=86_400_000)]
    status: Literal["success", "error"] = "success"

    @field_validator("timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        value = value.astimezone(UTC)
        if value < datetime(2020, 1, 1, tzinfo=UTC):
            raise ValueError("timestamp precedes supported history")
        if value > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("timestamp is in the future")
        return value

    @model_validator(mode="after")
    def check_cache(self):
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached input is a subset of total input tokens")
        return self

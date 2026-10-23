"""Bounded public and persisted contracts for manual project check-ins."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator,
)

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
SourceId = Annotated[str, StringConstraints(min_length=1, max_length=100)]
SourceIds = Annotated[list[SourceId], Field(min_length=1, max_length=16)]


class CheckInRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    note_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    priorities: list[ShortText] = Field(min_length=1, max_length=5)

    @field_validator("note_ids")
    @classmethod
    def canonical_note_ids(cls, values: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(values) != len(set(values)):
            raise ValueError("note_ids must be unique")
        return sorted(values, key=str)


class EvidenceStatement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: ShortText
    source_ids: SourceIds


class RecommendedAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["advance_priority", "resolve_blocker", "clarify_context"]
    description: ShortText
    rationale: ShortText
    source_ids: SourceIds


class CheckInResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    status: Literal["ready", "insufficient_information"]
    summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800)
    ]
    blockers: list[EvidenceStatement] = Field(max_length=5)
    recommended_action: RecommendedAction | None
    supporting_source_ids: SourceIds
    uncertainty: list[ShortText] = Field(max_length=5)

    @model_validator(mode="after")
    def action_matches_evidence_status(self) -> "CheckInResult":
        if self.status == "ready" and self.recommended_action is None:
            raise ValueError("a ready check-in requires one recommended action")
        if self.status == "insufficient_information":
            if self.recommended_action is not None or not self.uncertainty:
                raise ValueError("insufficient information requires uncertainty and no action")
        return self


class NoteSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: SourceId
    updated_at: datetime
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: Annotated[str, StringConstraints(min_length=1, max_length=5000)]


class PriorCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: SourceId
    completed_at: datetime
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result: CheckInResult


class PreparedCheckIn(CheckInRequest):
    schema_version: Literal[1] = 1
    captured_at: datetime
    sources: list[NoteSnapshot] = Field(min_length=1, max_length=10)
    previous_result: PriorCheckIn | None = None
    previous_result_omitted_for_size: bool = False
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

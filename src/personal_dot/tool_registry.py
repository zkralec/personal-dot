from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from personal_dot.models import Note, ToolRisk


class GetCurrentTimeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(
        min_length=1,
        max_length=100,
        description="IANA timezone name, for example UTC or America/New_York.",
    )

    @field_validator("timezone")
    @classmethod
    def timezone_must_exist(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value


class SaveNoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(
        min_length=1,
        max_length=10_000,
        description="The note text to save in Personal Dot's local database.",
    )

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


@dataclass(frozen=True)
class ToolContext:
    task_id: uuid.UUID
    session: Session


ToolHandler = Callable[[ToolContext, BaseModel], dict[str, Any]]
ApprovalSummary = Callable[[BaseModel], str]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    risk: ToolRisk
    automatic_execution_allowed: bool
    requires_approval: bool
    handler: ToolHandler
    approval_summary: ApprovalSummary
    sensitive_fields: frozenset[str] = frozenset()

    @property
    def input_schema(self) -> dict[str, Any]:
        schema = self.input_model.model_json_schema()
        schema["additionalProperties"] = False
        return schema

    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema,
            "strict": True,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"tool '{definition.name}' is already registered")
        if definition.automatic_execution_allowed and definition.requires_approval:
            raise ValueError("an automatic tool cannot also require approval")
        if not (
            definition.automatic_execution_allowed or definition.requires_approval
        ):
            raise ValueError("a tool must be automatic or require approval")
        if (
            definition.automatic_execution_allowed
            and definition.risk != ToolRisk.READ_ONLY
        ):
            raise ValueError("only read-only tools may execute automatically")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def definitions(self) -> list[ToolDefinition]:
        return [self._tools[name] for name in sorted(self._tools)]

    def openai_tools(self) -> list[dict[str, Any]]:
        return [definition.as_openai_tool() for definition in self.definitions()]


def _get_current_time(
    context: ToolContext, arguments: BaseModel
) -> dict[str, Any]:
    del context
    validated = GetCurrentTimeInput.model_validate(arguments)
    now = datetime.now(UTC).astimezone(ZoneInfo(validated.timezone))
    return {"datetime": now.isoformat(), "timezone": validated.timezone}


def _save_note(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    validated = SaveNoteInput.model_validate(arguments)
    note = Note(task_id=context.task_id, content=validated.content)
    context.session.add(note)
    context.session.flush()
    return {"note_id": str(note.id), "saved": True}


def _time_summary(arguments: BaseModel) -> str:
    validated = GetCurrentTimeInput.model_validate(arguments)
    return f"Read the current time in {validated.timezone}."


def _note_summary(arguments: BaseModel) -> str:
    validated = SaveNoteInput.model_validate(arguments)
    return f"Save a local note containing {len(validated.content)} characters."


def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="get_current_time",
            description=(
                "Return the current date and time in a requested IANA timezone. "
                "This only reads the system clock."
            ),
            input_model=GetCurrentTimeInput,
            risk=ToolRisk.READ_ONLY,
            automatic_execution_allowed=True,
            requires_approval=False,
            handler=_get_current_time,
            approval_summary=_time_summary,
        )
    )
    registry.register(
        ToolDefinition(
            name="save_note",
            description=(
                "Save a short note in Personal Dot's local PostgreSQL database. "
                "This changes local persistent state and requires user approval."
            ),
            input_model=SaveNoteInput,
            risk=ToolRisk.LOCAL_WRITE,
            automatic_execution_allowed=False,
            requires_approval=True,
            handler=_save_note,
            approval_summary=_note_summary,
        )
    )
    return registry


def get_tool_registry() -> ToolRegistry:
    return build_tool_registry()

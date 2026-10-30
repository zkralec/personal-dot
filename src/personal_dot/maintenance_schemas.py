"""Explicit operator configuration; repository/model text cannot alter it."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, StrictBool, field_validator
from personal_dot.documentation_schemas import StrictModel
from personal_dot.github import repository_name


class MaintenanceConfiguration(StrictModel):
    daily_time: str = Field(pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
    timezone: Literal['America/New_York'] = 'America/New_York'
    daily_budget_microusd: int = Field(gt=0, le=1_000_000)
    max_input_bytes_per_call: int = Field(ge=1024, le=65_536)
    max_output_tokens_per_call: int = Field(ge=128, le=4096)
    exclusions: list[str] = Field(max_length=1000)
    reassessment_days: int = Field(default=7, ge=1, le=365)
    discovery_hours: int = Field(default=24, ge=1, le=168)
    max_merged_per_run: Literal[1] = 1
    max_model_calls_per_day: Literal[2] = 2
    correction_attempts: Literal[0] = 0

    @field_validator('exclusions')
    @classmethod
    def validate_exclusions(cls, values: list[str]) -> list[str]:
        return sorted({repository_name(v).lower() for v in values})


class MaintenanceRequest(StrictModel):
    pilot: StrictBool = False
    resume_preview_task_id: uuid.UUID | None = None


class MaintenanceStateUpdate(StrictModel):
    action: Literal['pause', 'resume', 'disable']


class MaintenanceReconcile(StrictModel):
    task_id: uuid.UUID

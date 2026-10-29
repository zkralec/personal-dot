"""Explicit inputs and untrusted model-output contracts for documentation previews."""

import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class TargetSelection(StrictModel):
    path: str = Field(min_length=1, max_length=512)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class EvidenceSelection(TargetSelection):
    start_line: int = Field(ge=1, le=100_000)
    end_line: int = Field(ge=1, le=100_000)


class PreviewBudget(StrictModel):
    max_input_bytes_per_call: int = Field(default=65_536, ge=1024, le=65_536)
    max_output_tokens_per_call: int = Field(default=2048, ge=128, le=4096)


class DocumentationRequest(StrictModel):
    inspection_task_id: uuid.UUID
    base_commit: str = Field(pattern=r'^[0-9a-f]{40}$')
    targets: list[TargetSelection] = Field(min_length=1, max_length=3)
    evidence: list[EvidenceSelection] = Field(min_length=1, max_length=8)
    inputs_reviewed_for_model: Literal[True]
    allow_paid_model: StrictBool = False
    budget: PreviewBudget = Field(default_factory=PreviewBudget)


    @field_validator('inputs_reviewed_for_model', mode='before')
    @classmethod
    def explicit_review_acknowledgment(cls, value: object) -> bool:
        if value is not True:
            raise ValueError('exact reviewed-input acknowledgment required')
        return True


class SupportQuote(StrictModel):
    source_id: str = Field(pattern=r'^evidence:[1-8]$')
    quote: str = Field(min_length=20, max_length=500)


class DocumentationEdit(StrictModel):
    path: str = Field(min_length=1, max_length=512)
    after_line: int = Field(ge=1, le=100_000)
    text: str = Field(min_length=1, max_length=8192)
    support: list[SupportQuote] = Field(min_length=1, max_length=8)


class EditorOutput(StrictModel):
    outcome: Literal['candidate', 'no_useful_change', 'insufficient_evidence']
    gap: str = Field(min_length=1, max_length=1000)
    evidence_refs: list[str] = Field(min_length=1, max_length=8)
    edits: list[DocumentationEdit] = Field(max_length=12)


class ReviewFinding(StrictModel):
    code: Literal['unsupported_claim', 'accuracy', 'scope', 'structure', 'insufficient_evidence']
    description: str = Field(min_length=1, max_length=1000)
    evidence_refs: list[str] = Field(min_length=1, max_length=8)


class ReviewerOutput(StrictModel):
    binding_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    decision: Literal['approve', 'changes_requested', 'insufficient_evidence']
    findings: list[ReviewFinding] = Field(max_length=10)

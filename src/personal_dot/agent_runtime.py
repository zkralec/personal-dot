from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from personal_dot.agent_service import (
    AgentExecutionError,
    AgentResult,
    AgentService,
    AgentToolCall,
    get_agent_service,
)
from personal_dot.config import get_settings
from personal_dot.diagnostics import error_class
from personal_dot.db import SessionLocal
from personal_dot.models import (
    ApprovalRequest,
    ApprovalStatus,
    ToolCall,
    ToolCallStatus,
    ToolRisk,
)
from personal_dot.schemas import AgentTaskPayload
from personal_dot.tool_registry import (
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    get_tool_registry,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentPaused:
    state: dict[str, Any]
    metadata: dict[str, Any]


def _safe_validation_error(exc: ValidationError) -> str:
    return "invalid tool arguments: schema validation failed"


def _safe_error(exc: Exception) -> str:
    return f"Tool execution failed ({error_class(exc)})"


def _function_output(call_id: str, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": json.dumps(body, separators=(",", ":"), sort_keys=True),
    }


class ToolRuntime:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def prepare_call(self, task_id: uuid.UUID, request: AgentToolCall) -> ToolCall:
        with SessionLocal() as session:
            existing = session.scalar(
                select(ToolCall).where(
                    ToolCall.task_id == task_id,
                    ToolCall.provider_call_id == request.call_id,
                )
            )
            if existing is not None:
                return existing

            definition = self.registry.get(request.name)
            if definition is None:
                call = ToolCall(
                    task_id=task_id,
                    provider_call_id=request.call_id,
                    tool_name=request.name[:100] or "unknown",
                    risk=ToolRisk.UNCLASSIFIED,
                    arguments={},
                    automatic_execution_allowed=False,
                    requires_approval=False,
                    status=ToolCallStatus.FAILED,
                    approval_status=ApprovalStatus.NOT_REQUIRED,
                    error="unregistered tool requested",
                    completed_at=datetime.now(UTC),
                )
                session.add(call)
                session.commit()
                return call

            try:
                decoded = json.loads(request.arguments)
                if not isinstance(decoded, dict):
                    raise ValueError("arguments must be a JSON object")
                validated = definition.input_model.model_validate(decoded)
            except (json.JSONDecodeError, ValueError, ValidationError) as exc:
                if isinstance(exc, ValidationError):
                    error = _safe_validation_error(exc)
                else:
                    error = "invalid tool arguments: expected a JSON object"
                call = ToolCall(
                    task_id=task_id,
                    provider_call_id=request.call_id,
                    tool_name=definition.name,
                    risk=definition.risk,
                    arguments={},
                    automatic_execution_allowed=definition.automatic_execution_allowed,
                    requires_approval=definition.requires_approval,
                    status=ToolCallStatus.FAILED,
                    approval_status=ApprovalStatus.NOT_REQUIRED,
                    error=error[:2000],
                    completed_at=datetime.now(UTC),
                )
                session.add(call)
                session.commit()
                return call

            arguments = validated.model_dump(mode="json")
            for field in definition.sensitive_fields:
                if field in arguments:
                    arguments[field] = "[REDACTED]"

            approval_status = (
                ApprovalStatus.PENDING
                if definition.requires_approval
                else ApprovalStatus.NOT_REQUIRED
            )
            call = ToolCall(
                task_id=task_id,
                provider_call_id=request.call_id,
                tool_name=definition.name,
                risk=definition.risk,
                arguments=arguments,
                automatic_execution_allowed=definition.automatic_execution_allowed,
                requires_approval=definition.requires_approval,
                status=(
                    ToolCallStatus.AWAITING_APPROVAL
                    if definition.requires_approval
                    else ToolCallStatus.RUNNING
                ),
                approval_status=approval_status,
            )
            session.add(call)
            session.flush()
            if definition.requires_approval:
                session.add(
                    ApprovalRequest(
                        task_id=task_id,
                        tool_call_id=call.id,
                        status=ApprovalStatus.PENDING,
                        summary=definition.approval_summary(validated),
                    )
                )
            session.commit()
            logger.info(
                "Agent tool call persisted",
                extra={
                    "event": "tool_call_requested",
                    "task_id": str(task_id),
                    "tool_call_id": str(call.id),
                    "tool_name": call.tool_name,
                    "tool_risk": call.risk.value,
                    "approval_status": call.approval_status.value,
                },
            )
            return call

    def execute_call(self, call_id: uuid.UUID) -> dict[str, Any]:
        with SessionLocal() as session:
            call = session.scalar(
                select(ToolCall).where(ToolCall.id == call_id).with_for_update()
            )
            if call is None:
                return {"ok": False, "error": "tool call does not exist"}
            if call.status == ToolCallStatus.SUCCEEDED:
                return {"ok": True, "result": call.result or {}}
            if call.status in (ToolCallStatus.FAILED, ToolCallStatus.DENIED):
                return {"ok": False, "error": call.error or call.status.value}
            if call.requires_approval and call.approval_status != ApprovalStatus.APPROVED:
                return {"ok": False, "error": "tool call is not approved"}
            call.status = ToolCallStatus.RUNNING
            call.execution_started_at = datetime.now(UTC)
            session.commit()
            task_id = call.task_id
            tool_name = call.tool_name

        definition = self.registry.get(tool_name)
        if definition is None:
            return self._mark_failed(call_id, RuntimeError("tool is no longer registered"))

        try:
            with SessionLocal() as session:
                call = session.scalar(
                    select(ToolCall).where(ToolCall.id == call_id).with_for_update()
                )
                if call is None:
                    return {"ok": False, "error": "tool call does not exist"}
                validated = definition.input_model.model_validate(call.arguments)
                result = definition.handler(
                    ToolContext(task_id=task_id, session=session), validated
                )
                call.status = ToolCallStatus.SUCCEEDED
                call.result = result
                call.error = None
                call.completed_at = datetime.now(UTC)
                session.commit()
        except Exception as exc:
            return self._mark_failed(call_id, exc)

        logger.info(
            "Agent tool call completed",
            extra={
                "event": "tool_call_succeeded",
                "task_id": str(task_id),
                "tool_call_id": str(call_id),
                "tool_name": tool_name,
            },
        )
        return {"ok": True, "result": result}

    def _mark_failed(
        self, call_id: uuid.UUID, exc: Exception
    ) -> dict[str, Any]:
        error = _safe_error(exc)
        with SessionLocal() as session:
            call = session.scalar(
                select(ToolCall).where(ToolCall.id == call_id).with_for_update()
            )
            if call is not None:
                call.status = ToolCallStatus.FAILED
                call.error = error
                call.completed_at = datetime.now(UTC)
                session.commit()
                task_id = call.task_id
                tool_name = call.tool_name
            else:
                task_id = None
                tool_name = None
        logger.error(
            "Agent tool call failed",
            extra={
                "event": "tool_call_failed",
                "task_id": str(task_id) if task_id else None,
                "tool_call_id": str(call_id),
                "tool_name": tool_name,
            },
        )
        return {"ok": False, "error": error}


class AgentRuntime:
    def __init__(
        self,
        service: AgentService,
        registry: ToolRegistry,
        max_tool_rounds: int,
    ) -> None:
        self.service = service
        self.registry = registry
        self.tools = ToolRuntime(registry)
        self.max_tool_rounds = max_tool_rounds

    @staticmethod
    def _merge_metadata(
        accumulated: dict[str, Any], current: dict[str, Any]
    ) -> dict[str, Any]:
        merged = dict(accumulated)
        for key in (
            "provider",
            "model",
            "reasoning_effort",
            "output_verbosity",
            "request_id",
            "response_id",
            "response_status",
            "model_completed_at",
        ):
            if current.get(key) is not None:
                merged[key] = current[key]
        merged.setdefault("model_started_at", current.get("model_started_at"))
        response_ids = list(merged.get("response_ids", []))
        if current.get("response_id"):
            response_ids.append(current["response_id"])
        merged["response_ids"] = response_ids
        request_ids = list(merged.get("request_ids", []))
        if current.get("request_id"):
            request_ids.append(current["request_id"])
        merged["request_ids"] = request_ids
        usage = dict(merged.get("usage", {}))
        for key, value in current.get("usage", {}).items():
            if isinstance(value, int):
                usage[key] = usage.get(key, 0) + value
        merged["usage"] = usage
        return merged

    def _resume_pending(
        self, state: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], bool]:
        outputs: list[dict[str, Any]] = []
        still_pending = False
        for raw_id in state.get("pending_tool_call_ids", []):
            call_id = uuid.UUID(raw_id)
            with SessionLocal() as session:
                call = session.get(ToolCall, call_id)
                if call is None:
                    outputs.append(
                        _function_output(
                            "missing", {"ok": False, "error": "tool call missing"}
                        )
                    )
                    continue
                provider_call_id = call.provider_call_id
                approval_status = call.approval_status
            if approval_status == ApprovalStatus.PENDING:
                still_pending = True
                continue
            if approval_status == ApprovalStatus.DENIED:
                output = {"ok": False, "error": "user denied this tool call"}
            else:
                output = self.tools.execute_call(call_id)
            outputs.append(_function_output(provider_call_id, output))
        return outputs, still_pending

    def execute(
        self,
        task_id: uuid.UUID,
        payload: AgentTaskPayload,
        state: dict[str, Any] | None,
        memory_context: str | None = None,
        memory_metadata: dict[str, Any] | None = None,
    ) -> AgentResult | AgentPaused:
        if state:
            input_items = list(state.get("input_items", []))
            metadata = dict(state.get("metadata", {}))
            rounds = int(state.get("rounds", 0))
            pending_outputs, still_pending = self._resume_pending(state)
            if still_pending:
                return AgentPaused(state=state, metadata=metadata)
            metadata.pop("waiting_for_approval", None)
            input_items.extend(pending_outputs)
        else:
            input_items = self.service.build_input(
                payload.instruction,
                payload.context,
                memory_context,
            )
            metadata = {}
            if memory_metadata is not None:
                metadata["memory"] = memory_metadata
            rounds = 0

        while rounds < self.max_tool_rounds:
            rounds += 1
            try:
                turn = self.service.create_turn(
                    input_items=input_items,
                    tools=self.registry.openai_tools(),
                )
            except AgentExecutionError as exc:
                failed_metadata = self._merge_metadata(metadata, exc.metadata)
                failed_metadata.update({"success": False, "tool_rounds": rounds})
                raise AgentExecutionError(str(exc), failed_metadata) from None

            metadata = self._merge_metadata(metadata, turn.metadata)
            input_items.extend(turn.output_items)
            if not turn.tool_calls:
                if not turn.output_text.strip():
                    metadata.update({"success": False, "tool_rounds": rounds})
                    raise AgentExecutionError(
                        "OpenAI response completed without text output", metadata
                    )
                metadata.update({"success": True, "tool_rounds": rounds})
                return AgentResult(
                    output_text=turn.output_text,
                    metadata=metadata,
                )

            pending_ids: list[str] = []
            immediate_outputs: list[dict[str, Any]] = []
            for requested_call in turn.tool_calls:
                if not requested_call.call_id or not requested_call.name:
                    metadata.update({"success": False, "tool_rounds": rounds})
                    raise AgentExecutionError(
                        "OpenAI returned an invalid tool call", metadata
                    )
                call = self.tools.prepare_call(task_id, requested_call)
                if call.approval_status == ApprovalStatus.PENDING:
                    pending_ids.append(str(call.id))
                else:
                    immediate_outputs.append(
                        _function_output(
                            call.provider_call_id,
                            self.tools.execute_call(call.id),
                        )
                    )
            input_items.extend(immediate_outputs)

            if pending_ids:
                waiting_metadata = dict(metadata)
                waiting_metadata.update(
                    {
                        "success": None,
                        "waiting_for_approval": True,
                        "tool_rounds": rounds,
                    }
                )
                return AgentPaused(
                    state={
                        "input_items": input_items,
                        "pending_tool_call_ids": pending_ids,
                        "metadata": waiting_metadata,
                        "rounds": rounds,
                    },
                    metadata=waiting_metadata,
                )

        metadata.update({"success": False, "tool_rounds": rounds})
        raise AgentExecutionError(
            "Agent tool-round limit exceeded",
            metadata,
        )


def get_agent_runtime() -> AgentRuntime:
    settings = get_settings()
    return AgentRuntime(
        service=get_agent_service(),
        registry=get_tool_registry(),
        max_tool_rounds=settings.agent_max_tool_rounds,
    )

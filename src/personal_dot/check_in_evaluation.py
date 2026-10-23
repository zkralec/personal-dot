"""Small synthetic check-in corpus runner. No database or queue is accessed.

The default SDK stub checks application contracts, never real model quality.
Live generation requires both --live and RUN_CHECK_IN_LIVE_EVAL=1.
"""

import argparse
import hashlib
import json
import os
import platform
import re
import uuid
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from personal_dot import agent_service, check_in
from personal_dot.agent_service import AgentExecutionError, AgentService
from personal_dot.check_in_schemas import (
    CheckInRequest, CheckInResult, NoteSnapshot, PreparedCheckIn, PriorCheckIn,
)
from personal_dot.models import Task, TaskType

DEFAULT_CASES = Path("evaluations/check_in/cases.json")
SOURCE_REFERENCE = re.compile(
    r"\b(?:memory|task):[A-Za-z0-9_-]+|\bpriority:[a-z0-9_-]+:[0-9]+"
)


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    notes: list[str] = Field(min_length=1, max_length=10)
    priorities: list[str]
    prior_summary: str | None = None
    fixture: Literal[
        "ready", "unknown_source", "unknown_prose_source", "prior_only", "note_only",
        "malformed", "incomplete", "unavailable", "empty", "invalid_request",
    ] = "ready"
    expected: Literal["accepted", "invalid_result", "model_failure", "invalid_input"] = "accepted"
    expected_unlisted_text_sources: list[str] = Field(default_factory=list)
    review: list[str] = Field(min_length=1)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def load_cases(path: Path = DEFAULT_CASES) -> list[EvaluationCase]:
    cases = [EvaluationCase.model_validate(item) for item in json.loads(path.read_text())]
    if not cases or len({case.id for case in cases}) != len(cases):
        raise ValueError("the corpus must have unique case IDs and cannot be empty")
    return cases


def synthetic_result(prepared: PreparedCheckIn) -> dict[str, Any]:
    """Authored schema fixture; deliberately makes no claim about source meaning."""
    sources = [prepared.sources[0].source_id, f"priority:{prepared.project_id}:1"]
    return {
        "schema_version": 1, "status": "ready",
        "summary": "Synthetic contract fixture; factual quality has not been evaluated.",
        "blockers": [],
        "recommended_action": {
            "kind": "clarify_context", "description": "Review the supplied context.",
            "rationale": "Authored contract fixture, not a real model recommendation.",
            "source_ids": sources,
        },
        "supporting_source_ids": sources, "uncertainty": ["Human quality review required."],
    }


def prepare_case(case: EvaluationCase) -> PreparedCheckIn:
    """Stable synthetic IDs/times permit comparable input hashes across runs."""
    note_ids = [uuid.uuid5(uuid.NAMESPACE_URL, f"personal-dot-eval/{case.id}/{index}")
                for index in range(len(case.notes))]
    contents = dict(zip(note_ids, case.notes, strict=True))
    request = CheckInRequest(
        project_id="synthetic-project", note_ids=note_ids, priorities=case.priorities,
    )
    prepared = PreparedCheckIn(
        **request.model_dump(), captured_at=datetime(2026, 10, 23, tzinfo=UTC),
        sources=[NoteSnapshot(
            source_id=f"memory:{note_id}", updated_at=datetime(2026, 10, 20, tzinfo=UTC),
            content=contents[note_id], content_sha256=_hash(contents[note_id]),
        ) for note_id in request.note_ids], input_sha256="0" * 64,
    )
    if case.prior_summary is not None:
        prior = synthetic_result(prepared)
        prior["summary"] = case.prior_summary
        prior["recommended_action"].update(
            kind="advance_priority", description=case.prior_summary,
            rationale="Earlier synthetic inference; current notes may supersede it.",
        )
        prepared.previous_result = PriorCheckIn(
            source_id=f"task:{uuid.uuid5(uuid.NAMESPACE_URL, case.id + '/previous')}",
            completed_at=datetime(2026, 10, 21, tzinfo=UTC),
            result=CheckInResult.model_validate(prior), result_sha256=_hash(_json(prior)),
        )
    prepared.input_sha256 = _hash(check_in.render_context(prepared))
    return prepared


def unlisted_text_source_ids(result: dict[str, Any], prepared: PreparedCheckIn) -> list[str]:
    """Flag identifier-shaped references in prose; this is not fact checking."""
    allowed = {source.source_id for source in prepared.sources}
    allowed.update(f"priority:{prepared.project_id}:{i}"
                   for i in range(1, len(prepared.priorities) + 1))
    if prepared.previous_result:
        allowed.add(prepared.previous_result.source_id)
    prose = [result["summary"], *result["uncertainty"]]
    prose.extend(blocker["text"] for blocker in result["blockers"])
    if result["recommended_action"]:
        action = result["recommended_action"]
        prose.extend([action["description"], action["rationale"]])
    return sorted(set(SOURCE_REFERENCE.findall("\n".join(prose))) - allowed)


class SyntheticResponses:
    """SDK protocol fixture, never a substitute for live model evidence."""

    def __init__(self, case: EvaluationCase, prepared: PreparedCheckIn):
        self.case = case
        self.prepared = prepared
        self.requests: list[dict[str, Any]] = []

    def create(self, **request: Any) -> SimpleNamespace:
        self.requests.append(request)
        if self.case.fixture == "unavailable":
            raise RuntimeError("SYNTHETIC_PRIVATE_PROVIDER_DIAGNOSTIC")
        output = synthetic_result(self.prepared)
        fixture = self.case.fixture
        if fixture == "unknown_source":
            output["supporting_source_ids"].append("memory:unselected")
        elif fixture == "unknown_prose_source":
            output["summary"] = (
                "Shipped changes are documented by memory:00000000-0000-0000-0000-000000000000."
            )
        elif fixture == "prior_only":
            assert self.prepared.previous_result is not None
            output["supporting_source_ids"] = [self.prepared.previous_result.source_id]
            output["recommended_action"]["source_ids"] = output["supporting_source_ids"]
        elif fixture == "note_only":
            output["recommended_action"]["source_ids"] = [self.prepared.sources[0].source_id]
        text = _json(output)
        if fixture == "malformed":
            text = '{"private": "SYNTHETIC_PRIVATE_OUTPUT"'
        elif fixture == "empty":
            text = ""
        return SimpleNamespace(
            id="synthetic-response", _request_id="synthetic-request",
            model="synthetic-contract-fixture", output=[], output_text=text,
            status="incomplete" if fixture == "incomplete" else "completed", usage=None,
        )


def run_case(case: EvaluationCase, *, live: bool = False) -> dict[str, Any]:
    if live and (os.getenv("RUN_CHECK_IN_LIVE_EVAL") != "1" or case.fixture != "ready"):
        raise ValueError("live evaluation requires explicit opt-in and a quality case")
    row: dict[str, Any] = {
        "id": case.id, "evidence_kind": "live_model" if live else "synthetic_contract_fixture",
        "human_expectations": case.review, "human_review": "pending" if live else "not_evaluated",
    }
    try:
        prepared = prepare_case(case)
    except ValidationError:
        row.update(outcome="invalid_input", model_calls=0)
        if not live:
            row["fixture_expectation_met"] = case.expected == "invalid_input"
        return row

    row.update(input_sha256=prepared.input_sha256, context=json.loads(check_in.render_context(prepared)))
    service = check_in.get_check_in_service()
    responses = None
    if not live:
        responses = SyntheticResponses(case, prepared)
        service = AgentService(
            settings=service.settings.model_copy(update={"openai_api_key": "synthetic-unused"}),
            client=SimpleNamespace(responses=responses),
        )
    task = Task(type=TaskType.PROJECT_CHECK_IN, payload=prepared.model_dump(mode="json"))
    try:
        execution = check_in.execute_check_in(task, service=service)
        row.update(outcome="accepted", result=execution.result, metadata=execution.metadata)
        row["unlisted_text_source_ids"] = unlisted_text_source_ids(execution.result, prepared)
    except AgentExecutionError as exc:
        row.update(
            outcome=("invalid_result" if str(exc) == "Project check-in returned an invalid result"
                     else "model_failure"),
            error=str(exc), metadata=exc.metadata,
        )
    if responses is not None:
        row["model_calls"] = len(responses.requests)
        row["request_contract_passed"] = len(responses.requests) == 1 and all(
            "tools" not in request and "tool_choice" not in request
            and request["store"] is False and request["max_output_tokens"] <= 2048
            for request in responses.requests
        )
        row["fixture_expectation_met"] = (
            row["outcome"] == case.expected and row["request_contract_passed"]
            and row.get("unlisted_text_source_ids", []) == case.expected_unlisted_text_sources
        )
    return row


def run_identity(cases_path: Path, *, live: bool, revision: str) -> dict[str, Any]:
    settings = check_in.get_check_in_service().settings
    return {
        "format_version": 1, "mode": "live" if live else "synthetic_contracts",
        "started_at": datetime.now(UTC).isoformat(), "revision": revision,
        "corpus_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "prompt_sha256": _hash(check_in.build_check_in_instruction()),
        "schema_sha256": _hash(_json(CheckInResult.model_json_schema())),
        "code_sha256": {
            module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (check_in, agent_service)
        },
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(), "openai_sdk": version("openai"),
        "configuration": {
            "provider": "openai", "requested_model": settings.openai_model,
            "reasoning_effort": settings.openai_reasoning_effort,
            "output_verbosity": settings.openai_output_verbosity,
            "max_output_tokens": settings.openai_max_output_tokens,
            "timeout_seconds": settings.openai_timeout_seconds,
            "max_retries": settings.openai_max_retries, "tools": [], "store": False,
        },
        "quality": "requires_human_review" if live else "not_evaluated",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--live", action="store_true", help="allow paid generation for quality cases")
    parser.add_argument("--revision", default="unknown")
    parser.add_argument("--output", type=Path, required=True, help="new JSON report (never overwrites)")
    args = parser.parse_args()
    if args.live and os.getenv("RUN_CHECK_IN_LIVE_EVAL") != "1":
        parser.error("--live also requires RUN_CHECK_IN_LIVE_EVAL=1; paid calls are disabled by default")
    cases = load_cases(args.cases)
    if args.case_ids:
        unknown = set(args.case_ids) - {case.id for case in cases}
        if unknown:
            parser.error("unknown case ID")
        cases = [case for case in cases if case.id in args.case_ids]
    if args.live:
        if args.case_ids and any(case.fixture != "ready" for case in cases):
            parser.error("live mode accepts only quality cases (fixture=ready)")
        cases = [case for case in cases if case.fixture == "ready"]
    # Reserve the report before any paid call and flush each case as it completes.
    # A failed later call must not erase evidence from earlier requests.
    report = run_identity(args.cases, live=args.live, revision=args.revision)
    report["selected_case_ids"] = [case.id for case in cases]
    report["cases"] = []
    with args.output.open("x", encoding="utf-8") as output:
        def save() -> None:
            output.seek(0)
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.truncate()
            output.flush()
        save()
        for case in cases:
            report["cases"].append(run_case(case, live=args.live))
            save()
        report["completed_at"] = datetime.now(UTC).isoformat()
        if not args.live:
            report["fixture_expectations_met"] = all(
                row["fixture_expectation_met"] for row in report["cases"]
            )
        save()
    if args.live:
        return int(any(row["outcome"] != "accepted" or row.get("unlisted_text_source_ids")
                       for row in report["cases"]))
    return int(not report["fixture_expectations_met"])


if __name__ == "__main__":
    raise SystemExit(main())

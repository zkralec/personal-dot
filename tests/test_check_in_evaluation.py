"""Deterministic contracts only. These tests do not measure real model quality."""

import json
import sys

import pytest

from personal_dot import agent_service, check_in, check_in_evaluation as evaluation

CASES = evaluation.load_cases()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_synthetic_contract_case(case, monkeypatch):
    real_client_calls = []
    def forbid_network_client(*args, **kwargs):
        real_client_calls.append(True)
        raise AssertionError("contract runs must never construct a real provider client")
    monkeypatch.setattr(agent_service, "OpenAI", forbid_network_client)
    row = evaluation.run_case(case)
    assert row["fixture_expectation_met"], row
    assert row["evidence_kind"] == "synthetic_contract_fixture"
    assert row["human_review"] == "not_evaluated"
    assert row["model_calls"] == (0 if case.expected == "invalid_input" else 1)
    assert real_client_calls == []
    assert "SYNTHETIC_PRIVATE" not in json.dumps(row)


def test_valid_source_ids_do_not_establish_factual_support():
    prepared = evaluation.prepare_case(CASES[0])
    invented = evaluation.synthetic_result(prepared)
    invented["summary"] = "All features were deployed to production and the client approved them."
    # This documents a semantic limit, not successful factual grounding.
    validated = check_in.validate_check_in_output(json.dumps(invented), prepared)
    assert validated.summary == invented["summary"]


@pytest.mark.parametrize("reference", [
    "memory:unselected", "task:00000000-0000-0000-0000-000000000000",
    "priority:other-project:1", "priority:synthetic-project:99",
])
@pytest.mark.parametrize("wrapper", ["{}", "[{}]", "`{}`", "[evidence]({})"])
def test_recognized_prose_references_share_production_and_evaluation_contract(reference, wrapper):
    prepared = evaluation.prepare_case(CASES[0])
    result = evaluation.synthetic_result(prepared)
    result["summary"] = wrapper.format(reference)
    assert evaluation.unlisted_text_source_ids(result, prepared) == [reference]
    with pytest.raises(ValueError, match="unknown prose source"):
        check_in.validate_check_in_output(json.dumps(result), prepared)


def test_known_prose_ids_and_ordinary_markdown_and_code_are_accepted():
    prepared = evaluation.prepare_case(CASES[0])
    result = evaluation.synthetic_result(prepared)
    result["summary"] = (
        f"Evidence [{prepared.sources[0].source_id}] and `priority:synthetic-project:1`. "
        "[todo] [1] [docs](https://example.com) `values[0]` ```print('[x]')```"
    )
    check_in.validate_check_in_output(json.dumps(result), prepared)
    assert evaluation.unlisted_text_source_ids(result, prepared) == []


def test_prior_prose_reference_must_be_supplied_and_listed():
    case = next(case for case in CASES if case.prior_summary is not None)
    prepared = evaluation.prepare_case(case)
    result = evaluation.synthetic_result(prepared)
    result["summary"] = prepared.previous_result.source_id
    with pytest.raises(ValueError, match="must be listed"):
        check_in.validate_check_in_output(json.dumps(result), prepared)
    result["supporting_source_ids"].append(prepared.previous_result.source_id)
    check_in.validate_check_in_output(json.dumps(result), prepared)
    prepared.previous_result = None
    with pytest.raises(ValueError, match="unknown source"):
        check_in.validate_check_in_output(json.dumps(result), prepared)


def test_synthetic_inputs_have_repeatable_identity_and_prior_result():
    case = next(case for case in CASES if case.id == "stale_previous_result")
    first = evaluation.prepare_case(case)
    second = evaluation.prepare_case(case)
    assert first.model_dump() == second.model_dump()
    assert first.previous_result.result.summary == case.prior_summary
    assert "now complete" in first.sources[0].content


def test_paid_cli_requires_explicit_flag_and_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("RUN_CHECK_IN_LIVE_EVAL", raising=False)
    monkeypatch.setattr(sys, "argv", ["eval", "--live", "--output", str(tmp_path / "report.json")])
    with pytest.raises(SystemExit) as rejected:
        evaluation.main()
    assert rejected.value.code == 2
    with pytest.raises(ValueError, match="explicit opt-in"):
        evaluation.run_case(CASES[0], live=True)
    assert not (tmp_path / "report.json").exists()


def test_environment_alone_cannot_enable_paid_generation(monkeypatch, tmp_path):
    monkeypatch.setenv("RUN_CHECK_IN_LIVE_EVAL", "1")
    def forbid_network_client(*args, **kwargs):
        raise AssertionError("environment opt-in alone must not create a real client")
    monkeypatch.setattr(agent_service, "OpenAI", forbid_network_client)
    report_path = tmp_path / "contracts.json"
    monkeypatch.setattr(sys, "argv", [
        "eval", "--case", "clear_priority", "--revision", "synthetic-revision",
        "--output", str(report_path),
    ])
    assert evaluation.main() == 0
    report = json.loads(report_path.read_text())
    assert report["mode"] == "synthetic_contracts"
    assert report["quality"] == "not_evaluated"
    assert report["fixture_expectations_met"] is True
    assert report["revision"] == "synthetic-revision"
    assert len(report["prompt_sha256"]) == len(report["corpus_sha256"]) == 64
    assert report["configuration"]["max_output_tokens"] <= 2048
    assert report["configuration"]["timeout_seconds"] <= 60
    assert report["configuration"]["max_retries"] == 0
    assert "openai_api_key" not in json.dumps(report)
    with pytest.raises(FileExistsError):
        evaluation.main()


def test_live_report_plumbing_with_stub_is_not_quality_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("RUN_CHECK_IN_LIVE_EVAL", "1")
    case = CASES[0]
    responses = evaluation.SyntheticResponses(case, evaluation.prepare_case(case))
    original = check_in.get_check_in_service
    monkeypatch.setattr(check_in, "get_check_in_service", lambda: agent_service.AgentService(
        settings=original().settings, client=type("Client", (), {"responses": responses})(),
    ))
    report_path = tmp_path / "synthetic-live-plumbing.json"
    monkeypatch.setattr(sys, "argv", [
        "eval", "--live", "--case", case.id, "--output", str(report_path),
    ])
    assert evaluation.main() == 0
    report = json.loads(report_path.read_text())
    assert report["quality"] == "requires_human_review"
    assert report["cases"][0]["human_review"] == "pending"
    assert report["cases"][0]["metadata"]["model"] == "synthetic-contract-fixture"
    assert len(responses.requests) == 1


def test_unknown_prose_source_is_flagged_without_claiming_fact_checking():
    case = next(case for case in CASES if case.id == "unsupported_prose_reference")
    row = evaluation.run_case(case)
    assert row["outcome"] == "invalid_result"
    assert row["fixture_expectation_met"]
    assert "result" not in row


def test_live_mode_rejects_failure_fixtures_before_provider_call(monkeypatch):
    monkeypatch.setenv("RUN_CHECK_IN_LIVE_EVAL", "1")
    case = next(case for case in CASES if case.id == "unavailable_provider")
    with pytest.raises(ValueError, match="quality case"):
        evaluation.run_case(case, live=True)

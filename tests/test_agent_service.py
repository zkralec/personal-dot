from types import SimpleNamespace

import pytest

from personal_dot.agent_service import AgentConfigurationError, AgentService
from personal_dot.config import Settings
from personal_dot.tool_registry import build_tool_registry


class FakeResponses:
    def __init__(self, response) -> None:
        self.response = response
        self.request: dict | None = None

    def create(self, **kwargs):
        self.request = kwargs
        return self.response


class FakeOpenAIClient:
    def __init__(self, response) -> None:
        self.responses = FakeResponses(response)


def test_agent_service_normalizes_response_and_usage() -> None:
    response = SimpleNamespace(
        id="resp_test",
        _request_id="req_test",
        model="gpt-6-luna-2026-05-18",
        status="completed",
        output_text="A safe, stored answer.",
        usage=SimpleNamespace(
            input_tokens=25,
            output_tokens=14,
            total_tokens=39,
            input_tokens_details=SimpleNamespace(cached_tokens=5),
            output_tokens_details=SimpleNamespace(reasoning_tokens=7),
        ),
    )
    client = FakeOpenAIClient(response)
    settings = Settings(
        openai_api_key="test-key",
        openai_model="gpt-6-luna",
    )

    result = AgentService(settings=settings, client=client).execute(
        instruction="Summarize this.",
        context="Reference text.",
    )

    assert result.output_text == "A safe, stored answer."
    assert result.metadata["success"] is True
    assert result.metadata["model"] == "gpt-6-luna-2026-05-18"
    assert result.metadata["response_id"] == "resp_test"
    assert result.metadata["request_id"] == "req_test"
    assert result.metadata["usage"] == {
        "input_tokens": 25,
        "output_tokens": 14,
        "total_tokens": 39,
        "cached_input_tokens": 5,
        "reasoning_tokens": 7,
    }
    assert client.responses.request is not None
    assert client.responses.request["model"] == "gpt-6-luna"
    assert client.responses.request["reasoning"] == {"effort": "low"}
    assert client.responses.request["text"] == {"verbosity": "medium"}
    assert client.responses.request["store"] is False
    assert "Reference text." in str(client.responses.request["input"])
    assert "tools" not in client.responses.request


def test_agent_service_fails_clearly_without_api_key() -> None:
    service = AgentService(
        settings=Settings(
            openai_api_key=None,
            openai_model="gpt-6-luna",
        )
    )

    with pytest.raises(
        AgentConfigurationError,
        match="OPENAI_API_KEY is not configured for agent tasks",
    ) as raised:
        service.execute(instruction="This must not call the network.")

    assert raised.value.metadata["success"] is False
    assert raised.value.metadata["model"] == "gpt-6-luna"


def test_agent_service_uses_native_responses_function_calling() -> None:
    response = SimpleNamespace(
        id="resp_tool",
        _request_id="req_tool",
        model="gpt-6-luna",
        status="completed",
        output_text="",
        output=[
            {
                "type": "function_call",
                "call_id": "call_123",
                "name": "get_current_time",
                "arguments": '{"timezone":"UTC"}',
            }
        ],
        usage=None,
    )
    client = FakeOpenAIClient(response)
    service = AgentService(
        settings=Settings(openai_api_key="test-key"), client=client
    )
    registry = build_tool_registry()

    result = service.create_turn(
        input_items=service.build_input("What time is it?"),
        tools=registry.openai_tools(),
    )

    assert result.tool_calls[0].call_id == "call_123"
    assert result.tool_calls[0].name == "get_current_time"
    assert client.responses.request["tool_choice"] == "auto"
    assert client.responses.request["parallel_tool_calls"] is False
    sent_tools = {
        tool["name"]: tool for tool in client.responses.request["tools"]
    }
    assert sent_tools["get_current_time"]["type"] == "function"
    assert sent_tools["get_current_time"]["strict"] is True
    assert sent_tools["save_note"]["parameters"]["additionalProperties"] is False

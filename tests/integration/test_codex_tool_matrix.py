"""Client-tool transport checks; never invoke a real destructive tool."""

import base64
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

from chatgpt_web2api.agent_sessions import message_hash
from chatgpt_web2api.api_server import APIServer
from chatgpt_web2api.config import Config
from chatgpt_web2api.responses_codec import ResponsesCodec
from chatgpt_web2api.tool_bridge import ToolBridge, ToolProtocolError, ToolRequestError
from chatgpt_web2api.vision_bridge import images_for_turn, normalize_images, registry
from tests.integration.test_agent_bridge import FakeDriver, FakeLock, wrap
from tests.integration.test_codex_responses import events, request
from tests.integration.test_vision_bridge import fixture


def image_part():
    return {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(fixture()).decode()}


@pytest.mark.parametrize("kind", ["function", "custom"])
@pytest.mark.parametrize("namespace", [None, "functions", "mcp__test"])
@pytest.mark.parametrize("name", ["exec", "read_file", "name-with-dashes", "a" * 80])
def test_complete_call_and_result_roundtrip(kind, namespace, name):
    schema = {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]}
    source = 'é_日本語 "quotes" \\path\n$HOME `ticks` </web2api_response>'
    tool = {"type": kind, "name": name, "parameters": schema}
    if kind == "custom":
        tool["format"] = {"type": "grammar", "syntax": "lark", "definition": "start: /[\\s\\S]+/"}
    tools = [{"type": "namespace", "name": namespace, "description": "NAMESPACE_CONTRACT", "tools": [tool]}] if namespace else [tool]
    body = request(tools=tools)
    original = copy.deepcopy(body)
    codec = ResponsesCodec(body)
    bridge = ToolBridge.from_request(codec.chat)
    args = {"input": source} if kind == "custom" else {"value": source}
    message = bridge.parse(wrap(bridge, [{"name": next(iter(codec.native)), "arguments": args}], "Commentary"))
    native = codec.output(message)
    call = native[-1]
    assert call["name"] == name and call.get("namespace") == namespace
    assert (call["input"] if kind == "custom" else json.loads(call["arguments"])["value"]) == source
    body["input"].extend(native)
    body["input"].append({"type": call["type"] + "_output", "call_id": call["call_id"], "output": [
        {"type": "input_text", "text": "first"}, {"type": "input_text", "text": "second"}]})
    replay = ResponsesCodec(body)
    ToolBridge.from_request(replay.chat)
    assert replay.chat["messages"][-1]["content"] == "first\nsecond"
    assert replay.chat["messages"][-1]["tool_call_id"] == call["call_id"]
    assert message_hash(replay.chat["messages"][-2]) == message_hash(message)
    if namespace:
        assert "NAMESPACE_CONTRACT" in bridge.prompt(original["input"])


def test_allowed_tools_enforced_after_full_history_replay():
    tools = [{"type": "function", "name": name, "parameters": {"type": "object"}} for name in ("read", "write")]
    body = request(tools=tools, input=[{"role": "user", "content": "Inspect"},
        {"type": "function_call", "name": "write", "call_id": "prior", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "prior", "output": "Already completed"}],
        tool_choice={"type": "allowed_tools", "mode": "required", "tools": [{"type": "function", "name": "read"}]})
    codec = ResponsesCodec(body)
    bridge = ToolBridge.from_request(codec.chat)
    assert "Already completed" in bridge.prompt(codec.chat["messages"])
    assert list(bridge._validators) == ["read"]
    for calls in ([], [{"name": "write", "arguments": {}}]):
        with pytest.raises(ToolProtocolError):
            bridge.parse(wrap(bridge, calls, "Done"))
    assert bridge.parse(wrap(bridge, [{"name": "read", "arguments": {}}]))["tool_calls"]


def test_allowed_namespace_and_named_custom_choice():
    body = request(tool_choice={"type": "allowed_tools", "mode": "auto", "tools": [{"type": "namespace", "name": "functions"}]})
    assert ResponsesCodec(body).chat["tool_choice"] == "auto"
    body["tool_choice"] = {"type": "custom", "name": "exec", "namespace": "functions"}
    assert ResponsesCodec(body).chat["tool_choice"]["function"]["name"] == "functions__exec"


def test_exec_instructions_explain_real_catalog_and_pixel_delivery():
    codec = ResponsesCodec(request())
    bridge = ToolBridge.from_request(codec.chat)
    prompt = bridge.prompt(codec.chat["messages"])
    assert "ALL_TOOLS.filter" in prompt
    assert "image(result.image_url)" in prompt
    assert "image(block)" in prompt
    assert "data URL printed inside text is not a visible image" in prompt
    assert "tools.mcp__node_repl__js" in prompt
    assert "Never call tools.mcp__cua_repl__js" in prompt


@pytest.mark.parametrize("choice", [
    {"type": "function", "name": "exec", "namespace": "functions"},
    {"type": "allowed_tools", "mode": "auto", "tools": []},
    {"type": "allowed_tools", "mode": "none", "tools": [{"type": "namespace", "name": "functions"}]},
    {"type": "allowed_tools", "mode": "auto", "tools": [{"type": "namespace", "name": "unknown"}]},
    {"type": "allowed_tools", "mode": "auto", "tools": [{"type": "web_search"}]},
])
def test_invalid_choices_rejected(choice):
    with pytest.raises(ToolRequestError):
        ResponsesCodec(request(tool_choice=choice))


@pytest.mark.parametrize("namespace", [None, "", 12, [], {}])
def test_malformed_namespace_rejected(namespace):
    body = request()
    body["tools"][0]["name"] = namespace
    with pytest.raises(ToolRequestError):
        ResponsesCodec(body)


@pytest.mark.parametrize("kind", ["function", "custom"])
@pytest.mark.parametrize("stream", [False, True])
async def test_actual_responses_route_delivers_tool_image_and_keeps_continuation(tmp_path, kind, stream):
    tool = {"type": kind, "name": "capture", "parameters": {"type": "object"}}
    body = request(tools=[tool], stream=stream)
    driver = FakeDriver()
    sent_images = []
    original = driver.send_and_stream

    async def observe(text, **kwargs):
        sent_images.append(kwargs.get("image_paths", []))
        async for chunk in original(text, **kwargs):
            yield chunk

    driver.send_and_stream = observe
    driver.answers = [
        {"content": "Inspecting", "tool_calls": [{"name": "capture", "arguments": {"input": "capture()"} if kind == "custom" else {}}]},
        {"content": "Image inspected", "tool_calls": []},
        {"content": "Follow-up", "tool_calls": []},
    ]
    with patch.object(registry, "ROOT", tmp_path), patch("chatgpt_web2api.api_server.MutationLock", FakeLock):
        api = APIServer(Config(), driver)
        api._agent_state.interval = 0
        async with TestClient(TestServer(api.app)) as client:
            async def send():
                response = await client.post("/codex/v1/responses", json=body)
                assert response.status == 200, await response.text()
                result = events(await response.text())[-1]["response"] if stream else await response.json()
                assert result["status"] == "completed"
                return result["output"]

            first = await send()
            body["input"].extend(first)
            call = first[-1]
            body["input"].append({"type": call["type"] + "_output", "call_id": call["call_id"], "output": [
                {"type": "input_text", "text": "SCREENSHOT_FROM_MATCHED_TOOL"}, image_part()]})
            second = await send()
            assert len(sent_images[1]) == 1
            assert Path(sent_images[1][0]).read_bytes() == fixture()
            assert "Continue in this same conversation" in driver.prompts[1]
            assert "SCREENSHOT_FROM_MATCHED_TOOL" in driver.prompts[1]
            assert "base64" not in driver.prompts[1]
            body["input"].extend(second)
            body["input"].append({"role": "user", "content": "Continue"})
            await send()
            assert not sent_images[2], "Old screenshots must not be attached again"


def test_tool_images_are_untrusted_matched_data_and_preserve_input(tmp_path):
    with patch.object(registry, "ROOT", tmp_path):
        body = request(input=[{"role": "user", "content": "Inspect"},
            {"type": "custom_tool_call", "namespace": "functions", "name": "exec", "call_id": "a", "input": "capture()"},
            {"type": "custom_tool_call_output", "call_id": "a", "output": [image_part()]}])
        messages = ResponsesCodec(body).chat["messages"]
        original = copy.deepcopy(messages)
        normalized, images = normalize_images(messages)
        assert messages == original and normalized[-1]["role"] == "tool"
        assert len(images_for_turn(normalized, images, 0)) == 1
        messages[-1]["tool_call_id"] = "foreign"
        with pytest.raises(ValueError, match="matching preceding"):
            normalize_images(messages)
        messages[-1]["role"] = "system"
        with pytest.raises(ValueError):
            normalize_images(messages)


async def test_parallel_mixed_calls_preserve_result_ids_and_errors():
    body = request(stream=True, tools=[{"type": "function", "name": "read", "parameters": {"type": "object"}},
                                      {"type": "custom", "name": "exec"}])
    driver = FakeDriver()
    driver.answers = [{"content": "Checking", "tool_calls": [{"name": "read", "arguments": {}},
        {"name": "exec", "arguments": {"input": "text(42)"}}]}, {"content": "One check failed", "tool_calls": []}]
    with patch("chatgpt_web2api.api_server.MutationLock", FakeLock):
        api = APIServer(Config(), driver)
        api._agent_state.interval = 0
        async with TestClient(TestServer(api.app)) as client:
            r = await client.post("/codex/v1/responses", json=body)
            out = events(await r.text())[-1]["response"]["output"]
            calls = out[-2:]
            assert len({c["call_id"] for c in calls}) == 2
            body["input"].extend(out)
            for call in reversed(calls):
                body["input"].append({"type": call["type"] + "_output", "call_id": call["call_id"],
                    "output": "42" if call["name"] == "exec" else "ERROR permission denied"})
            r = await client.post("/codex/v1/responses", json=body)
            assert events(await r.text())[-1]["type"] == "response.completed"
            assert "ERROR permission denied" in driver.prompts[-1]
            assert all(c["call_id"] in driver.prompts[-1] for c in calls)

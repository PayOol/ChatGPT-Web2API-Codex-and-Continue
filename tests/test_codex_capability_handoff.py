import json
import re

import pytest

from chatgpt_web2api.responses_codec import ResponsesCodec
from chatgpt_web2api.tool_bridge import ToolBridge


def request(namespace=None, choice="auto"):
    tool = {"type": "custom", "name": "exec", "description": "Use tools methods and global ALL_TOOLS."}
    if namespace:
        tool = {"type": "namespace", "name": namespace, "tools": [tool]}
    return ResponsesCodec({"model": "auto", "tools": [tool], "tool_choice": choice,
                           "input": [{"role": "user", "content": "yo"}]})


@pytest.mark.parametrize("namespace", [None, "functions"])
def test_discovery_example_is_an_executable_schema_valid_call_with_current_nonce(namespace):
    codec = request(namespace)
    bridge = ToolBridge.from_request(codec.chat)
    prompt = bridge.prompt(codec.chat["messages"])
    frames = re.findall(re.escape(bridge.opening) + r'.*?</web2api_response>', prompt)
    message = bridge.parse(frames[-1])
    call = message["tool_calls"][0]["function"]
    assert call["name"] == ("functions__exec" if namespace else "exec")
    source = json.loads(call["arguments"])["input"]
    assert "ALL_TOOLS.filter" in source
    assert "tools.ALL_TOOLS" not in source
    assert "text(matches)" in source
    assert "exec_command" not in source  # This initial probe only reads metadata.
    assert "sky." not in source


def test_greeting_to_app_request_keeps_discovery_instruction_in_incremental_prompt():
    codec = request()
    bridge = ToolBridge.from_request(codec.chat)
    history = codec.chat["messages"] + [{"role": "assistant", "content": "yo"}]
    delta = [{"role": "user", "content": "As-tu accès à mes outils Computer Use ?"}]
    prompt = bridge.prompt(delta, prior_messages=history)
    assert "Available functions (JSON)" not in prompt
    assert "verify the relevant route with a read-only call before declaring it unavailable" in prompt
    assert "ALL_TOOLS.filter" in prompt
    assert "ALL_TOOLS and tools belong to exec; they are not globals in node_repl" in prompt
    assert "Never click, type, send messages, or replay an earlier action merely to test access" in prompt
    assert "unless the user forbids inspection" in prompt


def test_none_never_prompts_capability_discovery():
    codec = request(choice="none")
    bridge = ToolBridge.from_request(codec.chat)
    prompt = bridge.prompt(codec.chat["messages"], prior_messages=[{"role": "user", "content": "old"}])
    assert "Codex Computer Use route:" not in prompt
    assert "next tool-call frame can be" not in prompt


def test_named_unrelated_function_never_prompts_exec_discovery():
    codec = request()
    body = codec.chat
    body["tools"].append({"type": "function", "function": {
        "name": "read_file", "parameters": {"type": "object", "properties": {}}
    }})
    body["tool_choice"] = {"type": "function", "function": {"name": "read_file"}}
    bridge = ToolBridge.from_request(body)
    assert "Codex Computer Use route:" not in bridge.prompt(body["messages"])


def test_plain_continue_tools_do_not_gain_invented_exec_route():
    body = {"tools": [{"type": "function", "function": {
        "name": "read_file", "parameters": {"type": "object", "properties": {}}
    }}], "messages": [{"role": "user", "content": "Computer Use"}]}
    bridge = ToolBridge.from_request(body)
    assert "Codex Computer Use route:" not in bridge.prompt(body["messages"])

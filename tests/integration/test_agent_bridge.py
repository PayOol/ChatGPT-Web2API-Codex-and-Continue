import asyncio
import copy
import json
import re
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from chatgpt_web2api.api_server import APIServer
from chatgpt_web2api.cdp_driver import StreamChunk
from chatgpt_web2api.config import Config
from chatgpt_web2api.tool_bridge import ToolBridge, ToolProtocolError, ToolRequestError

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a local file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    }
]
MESSAGES = [
    {"role": "system", "content": "You are a coding agent."},
    {"role": "user", "content": "Read demo.py"},
]
CALL = {"name": "read_file", "arguments": {"path": "demo.py"}}


def body(**kwargs):
    return {
        "model": "auto",
        "messages": copy.deepcopy(MESSAGES),
        "tools": copy.deepcopy(TOOLS),
        **kwargs,
    }


def wrap(bridge, calls=None, content=None):
    return (
        bridge.opening
        + json.dumps({"content": content, "tool_calls": calls or []})
        + "</web2api_response>"
    )


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.bridge = ToolBridge.from_request(body())

    def test_plain_chat_not_wrapped(self):
        self.assertIsNone(ToolBridge.from_request({"messages": MESSAGES}))

    def test_incremental_resume_keeps_latest_nonempty_user_request(self):
        prior = MESSAGES + [
            {"role": "user", "content": [{"type": "text", "text": "Read next.py too"}]},
            {"role": "user", "content": []},
            {"role": "user", "content": "  "},
        ]
        delta = [{"role": "tool", "tool_call_id": "call_next", "content": "next.py contents"}]
        prompt = self.bridge.prompt(delta, prior_messages=prior)
        self.assertIn("Read next.py too", prompt)
        self.assertNotIn("Read demo.py", prompt)
        self.assertIn('"tool_call_id":"call_next"', prompt)
        self.assertGreater(prompt.index("Execution handoff:"), prompt.index("next.py contents"))
        self.assertIn("already supplied for the matching call IDs", prompt)

    def test_new_request_replaces_continuation_reminder(self):
        delta = [{"role": "user", "content": "Stop reading. Explain the result only."}]
        prompt = self.bridge.prompt(delta, prior_messages=MESSAGES)
        self.assertNotIn("Read demo.py", prompt)
        self.assertNotIn("Active user request already supplied", prompt)
        self.assertIn(delta[0]["content"], prompt)

    def test_large_prior_task_is_not_resent_or_truncated_into_an_instruction(self):
        prior = [{"role": "user", "content": "START_OLD_TASK " + "x" * 200000 + " END_OLD_TASK"}]
        delta = [{"role": "tool", "tool_call_id": "call_read", "content": "result " * 50000}]
        original = copy.deepcopy(delta)
        prompt = self.bridge.prompt(delta, prior_messages=prior)
        self.assertLess(len(prompt), 180000)
        self.assertNotIn("START_OLD_TASK", prompt)
        self.assertNotIn("END_OLD_TASK", prompt)
        self.assertIn("OUTPUT ABBREVIATED", prompt)
        self.assertEqual(delta, original)

    def test_none_choice_does_not_request_execution_and_real_limitations_are_preserved(self):
        bridge = ToolBridge.from_request(body(tool_choice="none"))
        prompt = bridge.prompt(MESSAGES)
        self.assertNotIn("Execution handoff:", prompt)
        content = "The tool reported permission denied. I cannot read this file."
        self.assertEqual(bridge.parse(wrap(bridge, content=content))["content"], content)

    def test_codex_freeform_source_is_preserved_in_function_envelope(self):
        tools = [{"type": "function", "function": {
            "name": "exec", "description": "Run raw JavaScript; tools.exec_command is available.",
            "parameters": {"type": "object", "required": ["input"],
                           "properties": {"input": {"type": "string"}},
                           "additionalProperties": False},
        }}]
        original = copy.deepcopy(tools)
        bridge = ToolBridge.from_request(body(tools=tools))
        prompt = bridge.prompt(MESSAGES)
        self.assertIn("arguments.input", prompt)
        self.assertIn("external Codex client executes it", prompt)
        self.assertEqual(tools, original)
        source = 'text(await tools.exec_command({cmd:"Get-Content -LiteralPath preuve.txt"}));'
        parsed = bridge.parse(wrap(bridge, [{"name": "exec", "arguments": {"input": source}}]))
        self.assertEqual(json.loads(parsed["tool_calls"][0]["function"]["arguments"]), {"input": source})
        with self.assertRaises(ToolProtocolError):
            bridge.parse(wrap(bridge, [{"name": "exec", "arguments": {"code": source}}]))

    def test_codex_incremental_prompt_reuses_catalog_and_is_compact(self):
        tools = [{"type": "function", "function": {
            "name": "exec", "description": "Run JavaScript " + "catalog " * 2000,
            "parameters": {"type": "object", "required": ["input"],
                           "properties": {"input": {"type": "string"}},
                           "additionalProperties": False},
        }}]
        bridge = ToolBridge.from_request(body(tools=tools))
        initial = bridge.prompt(MESSAGES)
        delta = [{"role": "tool", "tool_call_id": "call_1", "content": "ok"}]
        incremental = bridge.prompt(delta, prior_messages=MESSAGES)
        self.assertIn("Available functions (JSON)", initial)
        self.assertNotIn("Available functions (JSON)", incremental)
        self.assertIn("earlier system instructions", incremental)
        self.assertIn("Execution handoff:", incremental)
        self.assertLess(len(incremental), len(initial) // 3)

    def test_codex_computer_use_has_one_exact_nested_route(self):
        tools = [{"type": "function", "function": {
            "name": "exec", "description": "Run JavaScript",
            "parameters": {"type": "object", "required": ["input"],
                           "properties": {"input": {"type": "string"}},
                           "additionalProperties": False},
        }}]
        bridge = ToolBridge.from_request(body(tools=tools))
        prompt = bridge.prompt(MESSAGES)
        self.assertIn("tools.mcp__node_repl__js", prompt)
        self.assertIn("Only if that catalog returns mcp__node_repl__js", prompt)
        self.assertIn("read the installed Computer Use SKILL.md", prompt)
        self.assertIn('await import("@oai/sky")', prompt)
        self.assertIn("Do not rediscover tools", prompt)

    def test_codex_computer_use_observed_failures_break_discovery_loop(self):
        tools = [{"type": "function", "function": {
            "name": "exec", "description": "Run JavaScript",
            "parameters": {"type": "object", "required": ["input"],
                           "properties": {"input": {"type": "string"}},
                           "additionalProperties": False},
        }}]
        bridge = ToolBridge.from_request(body(tools=tools))
        prior = MESSAGES + [
            {"role": "tool", "tool_call_id": "bad", "content":
             "TypeError: tools.mcp__cua_repl__js is not a function"},
            {"role": "tool", "tool_call_id": "ready", "content":
             '{"skyType":"object","skyKeys":["list_windows"]}'},
        ]
        prompt = bridge.prompt(
            [{"role": "tool", "tool_call_id": "latest", "content": "continue"}],
            prior_messages=prior,
        )
        self.assertIn("already proves tools.mcp__cua_repl__js is unavailable", prompt)
        self.assertNotIn("persistent sky Computer Use are available", prompt)

    def test_frame_delimiter_inside_json_string_does_not_truncate(self):
        text = wrap(self.bridge, content="A literal </web2api_response> in code")
        self.assertEqual(
            self.bridge.parse(self.bridge.validated_frame(text))["content"],
            "A literal </web2api_response> in code",
        )

    def test_complete_frame_can_end_web_stream(self):
        text = wrap(self.bridge, [CALL])
        self.assertEqual(self.bridge.validated_frame(text + "_"), text)

    def test_incomplete_frame_cannot_end_web_stream(self):
        with self.assertRaises(ToolProtocolError):
            self.bridge.validated_frame(wrap(self.bridge, [CALL])[:-2])

    def test_valid_call(self):
        r = self.bridge.parse(wrap(self.bridge, [CALL]))
        self.assertEqual(
            json.loads(r["tool_calls"][0]["function"]["arguments"]), {"path": "demo.py"}
        )
        self.assertTrue(r["tool_calls"][0]["id"].startswith("call_"))

    def test_final_answer_preserves_markdown(self):
        text = "```python\ndef add(a, b):\n    return a + b\n```"
        self.assertEqual(self.bridge.parse(wrap(self.bridge, content=text))["content"], text)

    def test_mixed_commentary_and_call(self):
        self.assertEqual(
            self.bridge.parse(wrap(self.bridge, [CALL], "Reading now"))["content"], "Reading now"
        )

    def test_wrong_nonce(self):
        with self.assertRaises(ToolProtocolError):
            self.bridge.parse(wrap(self.bridge, [CALL]).replace(self.bridge.nonce, "wrong"))

    def test_plain_text_is_not_executed(self):
        with self.assertRaises(ToolProtocolError):
            self.bridge.parse("Run read_file demo.py")

    def test_unknown_tool(self):
        with self.assertRaises(ToolProtocolError):
            self.bridge.parse(wrap(self.bridge, [{"name": "shell", "arguments": {}}]))

    def test_missing_required_argument(self):
        with self.assertRaises(ToolProtocolError):
            self.bridge.parse(wrap(self.bridge, [{"name": "read_file", "arguments": {}}]))

    def test_invalid_type(self):
        with self.assertRaises(ToolProtocolError):
            self.bridge.parse(wrap(self.bridge, [{"name": "read_file", "arguments": {"path": 42}}]))

    def test_extra_argument(self):
        with self.assertRaises(ToolProtocolError):
            self.bridge.parse(
                wrap(
                    self.bridge,
                    [{"name": "read_file", "arguments": {"path": "x", "command": "no"}}],
                )
            )

    def test_none_forbids_tools(self):
        b = ToolBridge.from_request(body(tool_choice="none"))
        with self.assertRaises(ToolProtocolError):
            b.parse(wrap(b, [CALL]))

    def test_required_forbids_final_only(self):
        b = ToolBridge.from_request(body(tool_choice="required"))
        with self.assertRaises(ToolProtocolError):
            b.parse(wrap(b, content="Done"))

    def test_named_choice(self):
        b = ToolBridge.from_request(
            body(tool_choice={"type": "function", "function": {"name": "read_file"}})
        )
        self.assertIn("tool_calls", b.parse(wrap(b, [CALL])))

    def test_unknown_named_choice(self):
        with self.assertRaises(ToolRequestError):
            ToolBridge.from_request(
                body(tool_choice={"type": "function", "function": {"name": "missing"}})
            )

    def test_parallel_disabled(self):
        b = ToolBridge.from_request(body(parallel_tool_calls=False))
        with self.assertRaises(ToolProtocolError):
            b.parse(wrap(b, [CALL, CALL]))

    def test_parallel_ids_unique(self):
        calls = self.bridge.parse(wrap(self.bridge, [CALL, CALL]))["tool_calls"]
        self.assertNotEqual(calls[0]["id"], calls[1]["id"])

    def test_entire_batch_validated(self):
        with self.assertRaises(ToolProtocolError):
            self.bridge.parse(wrap(self.bridge, [CALL, {"name": "evil", "arguments": {}}]))

    def test_orphan_result_rejected(self):
        with self.assertRaises(ToolRequestError):
            ToolBridge.from_request(
                body(
                    messages=MESSAGES
                    + [{"role": "tool", "tool_call_id": "unknown", "content": "data"}]
                )
            )

    def test_full_history_preserved(self):
        history = copy.deepcopy(MESSAGES)
        for n in range(25):
            history.extend(
                [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": f"call{n}",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": "{}"},
                            }
                        ],
                    },
                    {"role": "tool", "tool_call_id": f"call{n}", "content": f"RESULT{n}"},
                ]
            )
        b = ToolBridge.from_request(body(messages=history))
        prompt = b.prompt(history)
        self.assertIn("RESULT0", prompt)
        self.assertIn("RESULT24", prompt)
        self.assertIn('"role":"tool"', prompt)

    def test_history_without_tools_allows_final(self):
        history = MESSAGES + [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c", "content": "ok"},
        ]
        b = ToolBridge.from_request(body(tools=[], messages=history))
        self.assertEqual(b.parse(wrap(b, content="Complete"))["content"], "Complete")

    def test_external_schema_ref_rejected(self):
        req = body()
        req["tools"][0]["function"]["parameters"] = {"$ref": "https://example.com/schema"}
        with self.assertRaises(ToolRequestError):
            ToolBridge.from_request(req)

    def test_context_overflow_is_explicit(self):
        with self.assertRaises(ToolRequestError):
            self.bridge.prompt([{"role": "user", "content": "X" * 180001}])

    def test_malformed_json(self):
        with self.assertRaises(ToolProtocolError):
            self.bridge.parse(self.bridge.opening + "{bad}</web2api_response>")


class FakeLock:
    def __init__(self, *args):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class FakeDriver:
    is_connected = True
    _current_conv_id = None

    def __init__(self):
        self.prompts = []
        self.answers = []
        self.navigations = 0

    async def navigate_new_chat(self, **kwargs):
        self.navigations += 1
        self._current_conv_id = None

    async def navigate_conversation(self, conversation):
        self.navigations += 1
        self._current_conv_id = conversation

    async def send_and_stream(self, text, **kwargs):
        self.prompts.append(text)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        self._current_conv_id = "test-conversation"
        if isinstance(answer, str):
            value = answer
        else:
            nonce = re.search(r'nonce="([a-f0-9]+)"', text).group(1)
            value = (
                f'<web2api_response nonce="{nonce}">' + json.dumps(answer) + "</web2api_response>"
            )
        yield StreamChunk(value)
        yield StreamChunk("", finish_reason="stop")


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.lock = patch("chatgpt_web2api.api_server.MutationLock", FakeLock)
        self.lock.start()
        self.driver = FakeDriver()
        self.api = APIServer(Config(), self.driver)
        self.api._agent_state.interval = 0
        self.client = TestClient(TestServer(self.api.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.lock.stop()

    async def test_nonstream_tool_call_then_result_and_final(self):
        self.driver.answers = [
            {"content": None, "tool_calls": [CALL]},
            {"content": "Read succeeded", "tool_calls": []},
        ]
        r = await self.client.post("/v1/chat/completions", json=body())
        self.assertEqual(r.status, 200)
        first = await r.json()
        self.assertEqual(first["choices"][0]["finish_reason"], "tool_calls")
        msg = first["choices"][0]["message"]
        call_id = msg["tool_calls"][0]["id"]
        history = MESSAGES + [
            msg,
            {"role": "tool", "tool_call_id": call_id, "content": "def add(a,b): return a+b"},
        ]
        r = await self.client.post("/v1/chat/completions", json=body(messages=history))
        result = await r.json()
        self.assertEqual(result["choices"][0]["finish_reason"], "stop")
        self.assertIn(call_id, self.driver.prompts[1])
        self.assertIn("return a+b", self.driver.prompts[1])
        self.assertEqual(self.driver.navigations, 1)
        self.assertIn("Read demo.py", self.driver.prompts[1])
        self.assertIn("Active user request already supplied", self.driver.prompts[1])
        self.assertNotIn('"role":"system"', self.driver.prompts[1])

    async def test_stream_tool_call_has_index_and_finish_reason(self):
        self.driver.answers = [{"content": "Reading", "tool_calls": [CALL]}]
        r = await self.client.post("/v1/chat/completions", json=body(stream=True))
        data = await r.text()
        events = [json.loads(line[6:]) for line in data.splitlines() if line.startswith("data: {")]
        tool_events = [e for e in events if "tool_calls" in e["choices"][0]["delta"]]
        self.assertEqual(tool_events[0]["choices"][0]["delta"]["tool_calls"][0]["index"], 0)
        self.assertEqual(events[-1]["choices"][0]["finish_reason"], "tool_calls")
        self.assertTrue(data.endswith("data: [DONE]\n\n"))

    async def test_three_tool_rounds_keep_task_and_only_new_results(self):
        history = MESSAGES + [{"role": "user", "content": []}]
        self.driver.answers = [
            {"content": None, "tool_calls": [CALL]},
            {"content": None, "tool_calls": [CALL]},
            {"content": None, "tool_calls": [CALL]},
            {"content": "All three results checked", "tool_calls": []},
        ]
        ids = []
        for turn in range(4):
            response = await self.client.post("/v1/chat/completions", json=body(messages=history))
            self.assertEqual(response.status, 200)
            result = (await response.json())["choices"][0]
            prompt = self.driver.prompts[-1]
            self.assertIn("Read demo.py", prompt)
            if turn:
                self.assertIn(ids[-1], prompt)
                self.assertIn(f"ONLY_RESULT_{turn - 1}", prompt)
                for older in range(turn - 1):
                    self.assertNotIn(f"ONLY_RESULT_{older}", prompt)
            if turn == 3:
                self.assertEqual(result["finish_reason"], "stop")
                break
            self.assertEqual(result["finish_reason"], "tool_calls")
            msg = result["message"]
            ids.append(msg["tool_calls"][0]["id"])
            history += [msg, {"role": "tool", "tool_call_id": ids[-1], "content": f"ONLY_RESULT_{turn}"}]
        self.assertEqual(self.driver.navigations, 1)

    async def test_unlimited_request_waits_and_delivers_only_validated_frame(self):
        original = self.driver.send_and_stream
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(text, **kwargs):
            self.assertEqual(kwargs["timeout"], 0)
            entered.set()
            await release.wait()
            async for chunk in original(text, **kwargs):
                yield chunk

        self.driver.send_and_stream = delayed
        self.driver.answers = [{"content": "Finished after waiting", "tool_calls": []}]
        request = asyncio.create_task(
            self.client.post("/v1/chat/completions", json=body(stream=True))
        )
        await asyncio.wait_for(entered.wait(), 2)
        await asyncio.sleep(0.03)
        self.assertFalse(request.done())
        release.set()
        response = await asyncio.wait_for(request, 2)
        self.assertEqual(response.status, 200)
        self.assertIn("Finished after waiting", await response.text())

    async def test_disconnect_cancels_observation_and_duplicate_request_does_not_resend(self):
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def waiting(text, **kwargs):
            self.driver.prompts.append(text)
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            yield  # async generator interface

        self.driver.send_and_stream = waiting
        request = asyncio.create_task(
            self.client.post("/v1/chat/completions", json=body(stream=True))
        )
        await asyncio.wait_for(entered.wait(), 2)
        request.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await request
        await asyncio.wait_for(cancelled.wait(), 3)
        for _ in range(20):
            if self.api._active_requests == 0:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(self.api._active_requests, 0)
        response = await self.client.post("/v1/chat/completions", json=body(stream=True))
        self.assertEqual(response.status, 422)
        self.assertEqual(len(self.driver.prompts), 1)

    async def test_stream_invalid_calls_never_emitted(self):
        self.driver.answers = ["invalid", "invalid again"]
        r = await self.client.post("/v1/chat/completions", json=body(stream=True))
        self.assertEqual(r.status, 422)
        self.assertEqual((await r.json())["error"]["code"], "invalid_tool_response")
        self.assertEqual(len(self.driver.prompts), 2)

    async def test_continue_receives_commentary_and_tools(self):
        import subprocess
        from pathlib import Path

        self.driver.answers = [
            {"content": "Je vais commencer par le README.", "tool_calls": [CALL]}
        ]
        r = await self.client.post("/v1/chat/completions", json=body(stream=True))
        data = await r.text()
        events = [json.loads(line[6:]) for line in data.splitlines() if line.startswith("data: {")]
        result = subprocess.run(
            ["node", str(Path(__file__).with_name("test_continue_stream.cjs"))],
            input=json.dumps(events),
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    async def test_invalid_tool_schema_returns_400_before_browser(self):
        req = body()
        req["tools"][0]["type"] = "custom"
        r = await self.client.post("/v1/chat/completions", json=req)
        self.assertEqual(r.status, 400)
        self.assertEqual(self.driver.prompts, [])

    async def test_plain_chat_regression(self):
        self.driver.answers = ["Hello"]
        r = await self.client.post(
            "/v1/chat/completions", json={"messages": MESSAGES, "model": "auto"}
        )
        self.assertEqual((await r.json())["choices"][0]["message"]["content"], "Hello")

    async def test_apply_after_agent_starts_fresh_without_system_message(self):
        self.driver.answers = [
            {"content": None, "tool_calls": [CALL]},
            "def add(a, b):\n    return a + b",
        ]
        r = await self.client.post("/v1/chat/completions", json=body())
        self.assertEqual(r.status, 200)
        await r.read()
        r = await self.client.post(
            "/v1/chat/completions",
            json={
                "model": "auto",
                "messages": [{"role": "user", "content": "Apply the change and return only code"}],
            },
        )
        self.assertEqual(r.status, 200)
        self.assertEqual(
            (await r.json())["choices"][0]["message"]["content"], "def add(a, b):\n    return a + b"
        )
        self.assertEqual(self.driver.navigations, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

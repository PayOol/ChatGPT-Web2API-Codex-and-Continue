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
        self.assertNotIn("Read demo.py", self.driver.prompts[1])

    async def test_stream_tool_call_has_index_and_finish_reason(self):
        self.driver.answers = [{"content": "Reading", "tool_calls": [CALL]}]
        r = await self.client.post("/v1/chat/completions", json=body(stream=True))
        data = await r.text()
        events = [json.loads(line[6:]) for line in data.splitlines() if line.startswith("data: {")]
        tool_events = [e for e in events if "tool_calls" in e["choices"][0]["delta"]]
        self.assertEqual(tool_events[0]["choices"][0]["delta"]["tool_calls"][0]["index"], 0)
        self.assertEqual(events[-1]["choices"][0]["finish_reason"], "tool_calls")
        self.assertTrue(data.endswith("data: [DONE]\n\n"))

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

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_agent_bridge import CALL, MESSAGES, HTTPTests, body

from chatgpt_web2api.agent_sessions import AgentState, UncertainSendError, message_hash
from chatgpt_web2api.cdp_driver import RateLimitError, SendReadinessError
from chatgpt_web2api.vision_bridge import ImageUploadError


# Reuse the HTTP fixture without importing its original tests twice.
class SessionHTTPTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = HTTPTests.asyncSetUp
    asyncTearDown = HTTPTests.asyncTearDown

    async def first_call(self):
        self.driver.answers.append({"content": "Reading", "tool_calls": [CALL]})
        r = await self.client.post("/v1/chat/completions", json=body())
        self.assertEqual(r.status, 200)
        msg = (await r.json())["choices"][0]["message"]
        return MESSAGES + [
            msg,
            {
                "role": "tool",
                "tool_call_id": msg["tool_calls"][0]["id"],
                "content": "file contents",
            },
        ]

    async def test_repeated_request_replays_without_browser_send(self):
        await self.first_call()
        r = await self.client.post("/v1/chat/completions", json=body(stream=True))
        self.assertEqual(r.status, 200)
        self.assertIn("tool_calls", await r.text())
        self.assertEqual(len(self.driver.prompts), 1)

    async def test_two_tasks_do_not_share_context(self):
        await self.first_call()
        self.driver.answers = [{"content": "Other task", "tool_calls": []}]
        other = copy.deepcopy(MESSAGES)
        other[-1]["content"] = "Different task"
        r = await self.client.post("/v1/chat/completions", json=body(messages=other))
        await r.read()
        self.assertEqual(self.driver.navigations, 2)
        self.assertNotIn("file contents", self.driver.prompts[-1])

    async def test_continue_space_placeholder_preserves_same_chat(self):
        self.driver.answers = [
            {"content": None, "tool_calls": [CALL]},
            {"content": "Done", "tool_calls": []},
        ]
        r = await self.client.post("/v1/chat/completions", json=body())
        msg = (await r.json())["choices"][0]["message"]
        msg["content"] = " "
        history = MESSAGES + [
            msg,
            {"role": "tool", "tool_call_id": msg["tool_calls"][0]["id"], "content": "Result"},
        ]
        r = await self.client.post("/v1/chat/completions", json=body(messages=history))
        await r.read()
        self.assertEqual(self.driver.navigations, 1)
        self.assertIn("Active user request already supplied", self.driver.prompts[1])
        self.assertIn("Read demo.py", self.driver.prompts[1])
        self.assertNotIn('"role":"system"', self.driver.prompts[1])

    async def test_changed_prior_history_starts_fresh(self):
        history = await self.first_call()
        history = copy.deepcopy(history)
        history[0]["content"] = "Different instructions"
        self.driver.answers = [{"content": "Done", "tool_calls": []}]
        r = await self.client.post("/v1/chat/completions", json=body(messages=history))
        await r.read()
        self.assertEqual(self.driver.navigations, 2)

    async def test_resume_agent_after_unrelated_apply(self):
        history = await self.first_call()
        self.driver.answers = ["Code", {"content": "Done", "tool_calls": []}]
        r = await self.client.post(
            "/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": "Apply this code"}]},
        )
        await r.read()
        self.driver._current_conv_id = "different-apply-chat"
        r = await self.client.post("/v1/chat/completions", json=body(messages=history))
        await r.read()
        self.assertEqual(self.driver.navigations, 3)
        self.assertIn("Active user request already supplied", self.driver.prompts[-1])
        self.assertIn("Read demo.py", self.driver.prompts[-1])
        self.assertNotIn("Apply this code", self.driver.prompts[-1])
        self.assertNotIn('"role":"system"', self.driver.prompts[-1])

    async def test_uncertain_send_blocks_all_client_retries(self):
        self.driver.answers = [SendReadinessError("Send not acknowledged")]
        for _ in range(4):
            r = await self.client.post("/v1/chat/completions", json=body())
            self.assertEqual(r.status, 422)
            self.assertEqual(r.headers["x-should-retry"], "false")
            await r.read()
        self.assertEqual(len(self.driver.prompts), 1)
        self.assertEqual(self.driver.navigations, 1)

    async def test_image_upload_failure_before_send_allows_explicit_retry(self):
        self.driver.answers = [
            ImageUploadError("Unsent attachment"),
            {"content": "Image received", "tool_calls": []},
        ]
        r = await self.client.post("/v1/chat/completions", json=body())
        self.assertEqual(r.status, 422)
        self.assertEqual((await r.json())["error"]["code"], "image_upload_failed_before_send")
        self.assertEqual(r.headers["x-should-retry"], "false")
        self.assertEqual(self.api._agent_state.uncertain, {})
        r = await self.client.post("/v1/chat/completions", json=body())
        self.assertEqual(r.status, 200)
        self.assertEqual((await r.json())["choices"][0]["message"]["content"], "Image received")

    async def test_rate_limit_pauses_other_requests_without_navigation(self):
        self.driver.answers = [RateLimitError(retry_after=300)]
        r = await self.client.post("/v1/chat/completions", json=body())
        await r.read()
        self.assertEqual(r.status, 429)
        deadline = self.api._agent_state.cooldown_until
        other = copy.deepcopy(MESSAGES)
        other[-1]["content"] = "Another request"
        for _ in range(3):
            r = await self.client.post("/v1/chat/completions", json=body(messages=other))
            self.assertEqual(r.status, 429)
            await r.read()
        self.assertEqual(len(self.driver.prompts), 1)
        self.assertEqual(self.driver.navigations, 1)
        self.assertEqual(self.api._agent_state.cooldown_until, deadline)


class StateTests(unittest.IsolatedAsyncioTestCase):
    async def test_zero_interval_has_no_artificial_wait(self):
        clock = [100.0]
        waits = []

        async def sleep(seconds):
            waits.append(seconds)
            clock[0] += seconds

        state = AgentState(interval=0)
        with (
            patch("chatgpt_web2api.agent_sessions.time.time", lambda: clock[0]),
            patch("chatgpt_web2api.agent_sessions.asyncio.sleep", sleep),
        ):
            observed = [await state.reserve(), await state.reserve(), await state.reserve()]
        self.assertEqual(waits, [0, 0, 0])
        self.assertEqual(observed, [0, 0, 0])

    async def test_spacing_between_sends(self):
        clock = [100.0]
        waits = []

        async def sleep(seconds):
            waits.append(seconds)
            clock[0] += seconds

        state = AgentState(interval=30)
        with (
            patch("chatgpt_web2api.agent_sessions.time.time", lambda: clock[0]),
            patch("chatgpt_web2api.agent_sessions.asyncio.sleep", sleep),
        ):
            await state.reserve()
            await state.reserve()
            await state.reserve()
        self.assertEqual(waits, [0, 30, 30])

    def test_persisted_old_pacing_is_capped_to_new_interval(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            path.write_text(json.dumps({"next_send": 999, "cooldown_until": 0}))
            with patch("chatgpt_web2api.agent_sessions.time.time", return_value=100):
                fast = AgentState(path, interval=0)
                bounded = AgentState(path, interval=2)
            self.assertEqual(fast.next_send, 100)
            self.assertEqual(bounded.next_send, 102)

    def test_session_and_pause_survive_restart_without_source_content(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            state = AgentState(path)
            reply = {"role": "assistant", "content": "private project response"}
            state.remember(MESSAGES, reply, "scope", "conv-123")
            state.penalize(300)
            state.begin("uncertain-key")
            restored = AgentState(path)
            self.assertEqual(
                restored.match(MESSAGES + [reply, {"role": "user", "content": "Next"}], "scope"),
                ("conv-123", len(MESSAGES)),
            )
            with self.assertRaises(RateLimitError):
                restored.check()
            with self.assertRaises(UncertainSendError):
                restored.check("uncertain-key")
            self.assertNotIn("private project", path.read_text())

    def test_argument_format_and_empty_content_normalization(self):
        a = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "x",
                    "type": "function",
                    "function": {"name": "read", "arguments": '{"x": 1}'},
                }
            ],
        }
        b = copy.deepcopy(a)
        b["content"] = ""
        b["tool_calls"][0]["function"]["arguments"] = '{"x":1}'
        self.assertEqual(message_hash(a), message_hash(b))

    def test_unrelated_tools_or_missing_prefix_do_not_reuse(self):
        state = AgentState()
        reply = {"role": "assistant", "content": "Done"}
        state.remember(MESSAGES, reply, "scope", "conv")
        self.assertEqual(
            state.match(MESSAGES + [reply, {"role": "user", "content": "Next"}], "other"), (None, 0)
        )
        self.assertEqual(
            state.match([reply, {"role": "user", "content": "Next"}], "scope"), (None, 0)
        )


del HTTPTests

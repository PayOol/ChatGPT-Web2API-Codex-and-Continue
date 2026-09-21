import asyncio
import json
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from chatgpt_web2api.api_server import APIServer
from chatgpt_web2api.config import Config
from tests.integration.test_agent_bridge import CALL, FakeDriver, FakeLock, body


class CodexTransportTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_catalog_is_static_and_auth_is_enforced(self):
        response = await self.client.get("/codex/v1/models")
        self.assertEqual([m["id"] for m in (await response.json())["data"]], ["auto"])
        self.assertFalse(self.driver.prompts)
        self.api._config.server.api_keys = ["test-key"]
        response = await self.client.get("/codex/v1/models")
        self.assertEqual(response.status, 401)
        response = await self.client.post("/codex/v1/chat/completions", json=body(stream=True))
        self.assertEqual(response.status, 401)
        self.assertFalse(self.driver.prompts)

    async def test_wait_heartbeat_does_not_deliver_tools_until_validated(self):
        release = asyncio.Event()
        original = self.driver.send_and_stream

        async def waiting(text, **kwargs):
            self.assertEqual(kwargs["timeout"], 0)
            await release.wait()
            async for chunk in original(text, **kwargs):
                yield chunk

        self.driver.send_and_stream = waiting
        self.driver.answers = [{"content": "Reading", "tool_calls": [CALL]}]
        with patch("chatgpt_web2api.codex_transport.HEARTBEAT_SECONDS", 0.02):
            response = await self.client.post("/codex/v1/chat/completions", json=body(stream=True))
            first = await asyncio.wait_for(response.content.readuntil(b"data: "), 2)
            beat = await response.content.readline()
            self.assertIn("Passerelle", beat.decode())
            self.assertNotIn("tool_calls", (first + beat).decode())
            release.set()
            result = await response.text()
        events = [json.loads(s[6:]) for s in result.splitlines() if s.startswith("data: {")]
        calls = [c for e in events for c in e["choices"][0]["delta"].get("tool_calls", [])]
        self.assertEqual(calls[0]["function"]["name"], CALL["name"])
        self.assertEqual(events[-1]["choices"][0]["finish_reason"], "tool_calls")
        self.assertTrue(result.endswith("data: [DONE]\n\n"))
        self.assertEqual(len(self.driver.prompts), 1)

    async def test_late_invalid_frame_is_stream_error_without_tool_or_success(self):
        original = self.driver.send_and_stream

        async def delayed(text, **kwargs):
            await asyncio.sleep(0.15)
            async for chunk in original(text, **kwargs):
                yield chunk

        self.driver.send_and_stream = delayed
        self.driver.answers = ["invalid", "still invalid"]
        response = await self.client.post("/codex/v1/chat/completions", json=body(stream=True))
        result = await response.text()
        self.assertIn('"error"', result)
        self.assertIn("invalid_tool_response", result)
        self.assertNotIn('"tool_calls"', result)
        self.assertNotIn("[DONE]", result)

    async def test_caller_cancellation_stops_observation_and_does_not_resend(self):
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def waiting(text, **kwargs):
            self.driver.prompts.append(text)
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            yield

        self.driver.send_and_stream = waiting
        response = await self.client.post("/codex/v1/chat/completions", json=body(stream=True))
        await entered.wait()
        response.close()
        await asyncio.wait_for(cancelled.wait(), 3)
        response = await self.client.post("/codex/v1/chat/completions", json=body(stream=True))
        self.assertEqual(response.status, 422)
        self.assertEqual(len(self.driver.prompts), 1)

    async def test_tool_result_round_trip_preserves_native_call_id_and_output(self):
        self.driver.answers = [
            {"content": None, "tool_calls": [CALL]},
            {"content": "Verified result", "tool_calls": []},
        ]
        request = body()
        response = await self.client.post("/codex/v1/chat/completions", json=request)
        first = (await response.json())["choices"][0]["message"]
        call_id = first["tool_calls"][0]["id"]
        request["messages"].extend(
            [first, {"role": "tool", "tool_call_id": call_id, "content": "CODEX_NATIVE_TOOL_PROOF"}]
        )
        response = await self.client.post("/codex/v1/chat/completions", json=request)
        self.assertEqual(
            (await response.json())["choices"][0]["message"]["content"], "Verified result"
        )
        self.assertIn(call_id, self.driver.prompts[-1])
        self.assertIn("CODEX_NATIVE_TOOL_PROOF", self.driver.prompts[-1])

    async def test_unknown_model_and_invalid_request_fail_without_submission(self):
        for value in [None, [], body(model="invented"), {"model": "auto", "messages": []}]:
            response = await self.client.post("/codex/v1/chat/completions", json=value)
            self.assertEqual(response.status, 400)
        self.assertFalse(self.driver.prompts)

import asyncio
import copy
import json
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from chatgpt_web2api.api_server import APIServer
from chatgpt_web2api.config import Config
from chatgpt_web2api.progress import current, report
from chatgpt_web2api.responses_codec import ResponsesCodec
from chatgpt_web2api.tool_bridge import ToolRequestError
from tests.integration.test_agent_bridge import FakeDriver, FakeLock


def request(**changes):
    return {"model": "auto", "input": [{"role": "user", "content": "Read the test file"}],
            "tools": [{"type": "namespace", "name": "functions", "tools": [
                {"type": "custom", "name": "exec", "description": "Run source code",
                 "format": {"type": "text"}}]}], **changes}


def events(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


class CodecTests(unittest.TestCase):
    def test_namespaced_custom_tool_and_images_roundtrip_without_mutation(self):
        source = 'text(await tools.exec_command({cmd:"Read test.txt"}));'
        body = request(input=[
            {"role": "user", "content": [{"type": "input_text", "text": "Inspect"},
                {"type": "input_image", "image_url": "data:image/png;base64,AA==", "detail": "original"}]},
            {"type": "reasoning", "summary": [{"type": "summary_text", "text": "BRIDGE_STATUS"}]},
            {"type": "custom_tool_call", "call_id": "native_123", "name": "exec", "namespace": "functions", "input": source},
            {"type": "custom_tool_call_output", "call_id": "native_123", "output": [
                {"type": "input_text", "text": "file content"},
                {"type": "input_image", "image_url": "data:image/png;base64,BB=="}]}])
        original = copy.deepcopy(body)
        codec = ResponsesCodec(body)
        self.assertEqual(body, original)
        self.assertNotIn("BRIDGE_STATUS", json.dumps(codec.chat))
        self.assertEqual(codec.chat["messages"][0]["content"][1]["image_url"]["detail"], "original")
        self.assertEqual(codec.chat["messages"][-1]["tool_call_id"], "native_123")
        call = codec.chat["messages"][1]["tool_calls"][0]
        item = codec.output({"content": None, "tool_calls": [call]})[0]
        self.assertEqual(item["type"], "custom_tool_call")
        self.assertTrue(item["id"].startswith("ctc_"))
        self.assertEqual((item["name"], item["namespace"], item["input"], item["call_id"]),
                         ("exec", "functions", source, "native_123"))

    def test_unknown_items_and_modalities_fail_before_submission(self):
        for value in [request(input=[{"type": "future_action"}]),
                      request(tools=[{"type": "unknown_hosted_tool"}]),
                      request(input=[{"role": "user", "content": [{"type": "input_audio"}]}]),
                      request(previous_response_id="resp_old"), request(background=True)]:
            with self.subTest(value=value), self.assertRaises(ToolRequestError):
                ResponsesCodec(value)

    def test_codex_hosted_search_does_not_disable_client_tools(self):
        body = request()
        body["tools"].insert(0, {"type": "web_search", "search_context_size": "medium"})
        codec = ResponsesCodec(body)
        self.assertEqual(codec.unavailable_hosted, ["web_search"])
        self.assertEqual(len(codec.chat["tools"]), 1)
        self.assertEqual(codec.chat["tools"][0]["function"]["name"], "functions__exec")
        self.assertIn("Client tools listed below remain available", codec.chat["messages"][0]["content"])
        body["tool_choice"] = {"type": "web_search"}
        with self.assertRaises(ToolRequestError):
            ResponsesCodec(body)

    def test_function_schema_choice_and_call_are_preserved(self):
        schema = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
        codec = ResponsesCodec(request(tools=[{"type": "function", "name": "read", "parameters": schema}],
                                       tool_choice={"type": "function", "name": "read"}))
        self.assertEqual(codec.chat["tools"][0]["function"]["parameters"], schema)
        self.assertEqual(codec.chat["tool_choice"]["function"]["name"], "read")
        item = codec.output({"content": "Reading", "tool_calls": [{"id": "id1", "function": {
            "name": "read", "arguments": '{"path":"a_b.txt"}'}}]})
        self.assertEqual(item[0]["phase"], "commentary")
        self.assertEqual(item[1]["arguments"], '{"path":"a_b.txt"}')
        self.assertTrue(item[1]["id"].startswith("fc_"))


class ResponsesTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_progress_arrives_before_generation_and_tool_dispatch(self):
        release = asyncio.Event()
        original = self.driver.send_and_stream

        async def wait(text, **kwargs):
            report("BROWSER_OBSERVED_GENERATING")
            await release.wait()
            async for chunk in original(text, **kwargs):
                yield chunk

        self.driver.send_and_stream = wait
        self.driver.answers = [{"content": "Inspecting", "tool_calls": [
            {"name": "functions__exec", "arguments": {"input": "text('READ_ONLY');"}}]}]
        response = await self.client.post("/codex/v1/responses", json=request(stream=True))
        prefix = b""
        while b"BROWSER_OBSERVED_GENERATING" not in prefix:
            prefix += await asyncio.wait_for(response.content.readline(), 2)
        self.assertNotIn(b"custom_tool_call", prefix)
        self.assertIn(b"response.reasoning_summary_text.delta", prefix)
        release.set()
        all_events = events(prefix.decode() + await response.text())
        final = all_events[-1]["response"]
        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["output"][-1]["type"], "custom_tool_call")
        self.assertEqual(final["output"][-1]["namespace"], "functions")
        self.assertEqual(final["output"][-1]["input"], "text('READ_ONLY');")
        self.assertEqual(final["output"][1]["content"][0]["text"], "Inspecting")
        self.assertEqual([e["sequence_number"] for e in all_events], list(range(len(all_events))))
        self.assertIsNone(current.get())

    async def test_native_tool_result_reuses_conversation_and_excludes_transport_summary(self):
        self.driver.answers = [{"content": "Reading", "tool_calls": [
            {"name": "functions__exec", "arguments": {"input": "text('probe');"}}]},
            {"content": "Verified", "tool_calls": []}]
        first = request(stream=True)
        r = await self.client.post("/codex/v1/responses", json=first)
        output = events(await r.text())[-1]["response"]["output"]
        first["input"].extend(output)
        first["input"].append({"type": "custom_tool_call_output", "call_id": output[-1]["call_id"], "output": "PROOF"})
        r = await self.client.post("/codex/v1/responses", json=first)
        result = events(await r.text())[-1]["response"]["output"]
        self.assertEqual(result[-1]["content"][0]["text"], "Verified")
        self.assertIn("Continue in this same conversation", self.driver.prompts[-1])
        self.assertNotIn("Connexion établie", self.driver.prompts[-1])
        self.assertIn("PROOF", self.driver.prompts[-1])

    async def test_late_error_has_no_call_or_completed_response(self):
        original = self.driver.send_and_stream

        async def delayed(text, **kwargs):
            await asyncio.sleep(0.13)
            async for chunk in original(text, **kwargs):
                yield chunk

        self.driver.send_and_stream = delayed
        self.driver.answers = ["bad", "still bad"]
        r = await self.client.post("/codex/v1/responses", json=request(stream=True))
        result = events(await r.text())
        self.assertEqual(result[-1]["type"], "response.failed")
        self.assertFalse(any(e["type"] == "response.completed" for e in result))
        self.assertNotIn('"custom_tool_call"', json.dumps(result))

    async def test_cancel_preserves_uncertain_send_without_resubmitting(self):
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
        with patch("chatgpt_web2api.codex_transport.HEARTBEAT_SECONDS", 0.02):
            r = await self.client.post("/codex/v1/responses", json=request(stream=True))
            await entered.wait()
            r.close()
            await asyncio.wait_for(cancelled.wait(), 3)
            r = await self.client.post("/codex/v1/responses", json=request(stream=True))
            self.assertEqual(r.status, 422)
        self.assertEqual(len(self.driver.prompts), 1)

    async def test_auth_and_invalid_body_never_send(self):
        for value in [None, [], request(input=[]), request(model="unknown")]:
            r = await self.client.post("/codex/v1/responses", json=value)
            self.assertEqual(r.status, 400)
        self.api._config.server.api_keys = ["test"]
        r = await self.client.post("/codex/v1/responses", json=request(stream=True))
        self.assertEqual(r.status, 401)
        self.assertFalse(self.driver.prompts)

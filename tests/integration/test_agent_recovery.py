import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from test_agent_bridge import CALL, HTTPTests, body

from chatgpt_web2api.agent_sessions import AgentState
from chatgpt_web2api.cdp_driver import GenerationStuckError
from chatgpt_web2api.tool_bridge import ToolProtocolError


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = HTTPTests.asyncSetUp
    asyncTearDown = HTTPTests.asyncTearDown

    async def fail_then_snapshot(self):
        self.driver.answers = [GenerationStuckError("phase_1_appear", 90)]
        r = await self.client.post("/v1/chat/completions", json=body())
        await r.read()
        self.assertEqual(r.status, 504)
        self.assertEqual(r.headers.get("x-should-retry"), "false")
        prompt = self.driver.prompts[0]
        nonce = re.search(r'nonce="([a-f0-9]+)"', prompt).group(1)
        snap = dict(
            user=prompt,
            assistant=f'<web2api_response nonce="{nonce}">'
            + json.dumps({"content": None, "tool_calls": [CALL]})
            + "</web2api_response>",
            conversation="recovered-chat",
            paired=True,
            generating=False,
        )
        self.driver.read_agent_exchange = AsyncMock(return_value=snap)
        return snap

    async def test_completed_pending_reply_recovered_once_and_replayed_with_same_ids(self):
        await self.fail_then_snapshot()
        r = await self.client.post("/v1/chat/completions", json=body())
        a = await r.json()
        self.assertEqual(r.status, 200)
        r = await self.client.post("/v1/chat/completions", json=body())
        b = await r.json()
        self.assertEqual(a["choices"], b["choices"])
        self.assertEqual(len(self.driver.prompts), 1)
        self.assertEqual(self.driver.navigations, 1)
        self.assertEqual(self.api._agent_state.uncertain, {})

    async def test_legacy_pending_timestamp_can_recover_only_full_matching_prompt(self):
        await self.fail_then_snapshot()
        self.api._agent_state.pending_frames = {}
        r = await self.client.post("/v1/chat/completions", json=body())
        await r.read()
        self.assertEqual(r.status, 200)
        self.assertEqual(len(self.driver.prompts), 1)

    async def test_different_prompt_wrong_nonce_partial_or_unpaired_stays_blocked(self):
        snapshot = await self.fail_then_snapshot()
        variants = [
            dict(user="Other task"),
            dict(assistant=snapshot["assistant"].replace('nonce="', 'nonce="wrong')),
            dict(assistant=snapshot["assistant"][:-5]),
            dict(paired=False),
            dict(generating=True),
            dict(conversation=""),
            dict(unsafe_markup=True),
            dict(literal=False),
        ]
        for change in variants:
            self.driver.read_agent_exchange.return_value = {**snapshot, **change}
            r = await self.client.post("/v1/chat/completions", json=body())
            await r.read()
            self.assertEqual(r.status, 422, change.keys())
        self.assertEqual(len(self.driver.prompts), 1)

    async def test_mismatched_conversation_stays_blocked(self):
        await self.fail_then_snapshot()
        for info in self.api._agent_state.pending_frames.values():
            info["conversation"] = "expected-chat"
        r = await self.client.post("/v1/chat/completions", json=body())
        await r.read()
        self.assertEqual(r.status, 422)
        self.assertEqual(len(self.driver.prompts), 1)

    async def test_restart_reopens_recorded_chat_and_recovers_without_sending(self):
        snapshot = await self.fail_then_snapshot()
        for info in self.api._agent_state.pending_frames.values():
            info["conversation"] = snapshot["conversation"]
        self.driver.read_agent_exchange.side_effect = [
            dict(conversation="", paired=False, generating=False),
            snapshot,
        ]
        r = await self.client.post("/v1/chat/completions", json=body())
        await r.read()
        self.assertEqual(r.status, 200)
        self.assertEqual(self.driver._current_conv_id, snapshot["conversation"])
        self.assertEqual(len(self.driver.prompts), 1)
        self.assertEqual(self.driver.navigations, 2)

    async def test_pending_metadata_survives_restart_and_contains_no_prompt(self):
        await self.fail_then_snapshot()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            self.api._agent_state.path = path
            self.api._agent_state.save()
            self.assertNotIn("Read demo.py", path.read_text())
            self.api._agent_state = AgentState(path, interval=0)
            r = await self.client.post("/v1/chat/completions", json=body())
            await r.read()
            self.assertEqual(r.status, 200)
        self.assertEqual(len(self.driver.prompts), 1)

    async def test_completed_plain_answer_gets_format_only_repair_on_retry(self):
        snapshot = await self.fail_then_snapshot()
        snapshot.update(
            assistant="Plain answer without protocol",
            literal=False,
            unsafe_markup=True,
            completed=True,
        )
        self.driver.answers = [{"content": "Recovered answer", "tool_calls": []}]
        original_nonce = next(iter(self.api._agent_state.pending_frames.values()))["nonce"]
        r = await self.client.post("/v1/chat/completions", json=body())
        self.assertEqual(r.status, 200)
        self.assertEqual((await r.json())["choices"][0]["message"]["content"], "Recovered answer")
        self.assertEqual(len(self.driver.prompts), 2)
        self.assertEqual(self.driver.navigations, 1)
        self.assertIn("Correct its format", self.driver.prompts[-1])
        self.assertIn(original_nonce, self.driver.prompts[-1])
        self.assertNotIn("Read demo.py", self.driver.prompts[-1])
        self.assertEqual(self.api._agent_state.uncertain, {})
        # A subsequent retry replays the validated result without another send.
        r = await self.client.post("/v1/chat/completions", json=body())
        await r.read()
        self.assertEqual(r.status, 200)
        self.assertEqual(len(self.driver.prompts), 2)

    async def test_plain_answer_without_current_turn_completion_stays_blocked(self):
        snapshot = await self.fail_then_snapshot()
        snapshot.update(assistant="Plain answer", literal=False, completed=False)
        r = await self.client.post("/v1/chat/completions", json=body())
        await r.read()
        self.assertEqual(r.status, 422)
        self.assertEqual(len(self.driver.prompts), 1)

    async def test_cancelled_repair_resumes_by_reading_its_result_not_sending_again(self):
        snapshot = await self.fail_then_snapshot()
        snapshot.update(assistant="Plain answer", literal=False, completed=True)
        self.driver.answers = [GenerationStuckError("phase_1_appear", 90)]
        r = await self.client.post("/v1/chat/completions", json=body())
        await r.read()
        self.assertEqual(r.status, 504)
        info = next(iter(self.api._agent_state.pending_frames.values()))
        self.assertTrue(info["repair_attempted"])
        with tempfile.TemporaryDirectory() as folder:
            self.api._agent_state.path = Path(folder) / "state.json"
            self.api._agent_state.save()
            self.api._agent_state = AgentState(self.api._agent_state.path, interval=0)
            snapshot.update(
                user=self.driver.prompts[-1], assistant="Still no protocol", literal=False
            )
            for _ in range(2):
                r = await self.client.post("/v1/chat/completions", json=body())
                self.assertEqual(r.status, 422)
                self.assertEqual((await r.json())["error"]["code"], "invalid_tool_response")
            self.assertEqual(len(self.driver.prompts), 2)
            snapshot.update(
                assistant=f'<web2api_response nonce="{info["nonce"]}">'
                + '{"content":"Recovered repair","tool_calls":[]}</web2api_response>',
                literal=True,
                unsafe_markup=False,
            )
            r = await self.client.post("/v1/chat/completions", json=body())
            self.assertEqual(r.status, 200)
            self.assertEqual(
                (await r.json())["choices"][0]["message"]["content"], "Recovered repair"
            )
            self.assertEqual(len(self.driver.prompts), 2)

    async def test_immediate_invalid_answer_repairs_once_and_persists_the_budget(self):
        self.driver.answers = [
            ToolProtocolError("Plain answer"),
            ToolProtocolError("Still invalid"),
        ]
        r = await self.client.post("/v1/chat/completions", json=body())
        await r.read()
        self.assertEqual(r.status, 422)
        self.assertEqual(len(self.driver.prompts), 2)
        info = next(iter(self.api._agent_state.pending_frames.values()))
        self.assertTrue(info["repair_attempted"])


del HTTPTests

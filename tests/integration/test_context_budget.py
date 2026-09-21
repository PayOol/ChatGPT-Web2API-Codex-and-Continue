import copy
import json
import unittest

from test_agent_bridge import CALL, MESSAGES, HTTPTests, body

from chatgpt_web2api.context_budget import fit_tool_outputs
from chatgpt_web2api.tool_bridge import ToolBridge, ToolRequestError


def history(output):
    return MESSAGES + [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_test",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path":"demo.py"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_test", "content": output},
    ]


class BudgetTests(unittest.TestCase):
    def test_small_history_exactly_preserved(self):
        incoming = history("complete output")
        result, stats = fit_tool_outputs(incoming, 10000)
        self.assertEqual(result, incoming)
        self.assertEqual(stats["shortened_outputs"], 0)

    def test_huge_terminal_output_preserves_failure_head_tail_and_call_ids(self):
        incoming = history(
            "START\n"
            + "noise\n" * 30000
            + "ERROR: CommandNotFoundException\n"
            + "noise\n" * 30000
            + "END failed\n"
        )
        original = copy.deepcopy(incoming)
        b = ToolBridge.from_request(body(messages=incoming))
        prompt = b.prompt(incoming)
        self.assertLess(len(prompt), 180000)
        for expected in (
            "START",
            "END failed",
            "CommandNotFoundException",
            "OUTPUT ABBREVIATED",
            "call_test",
        ):
            self.assertIn(expected, prompt)
        self.assertEqual(incoming, original)
        self.assertEqual(b.context_stats["shortened_outputs"], 1)

    def test_aggregate_budget_with_escaped_characters(self):
        incoming = history('\\\n\t"' * 100000)
        result, stats = fit_tool_outputs(incoming, 6000)
        self.assertLessEqual(
            len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))), 6000
        )
        self.assertEqual(stats["shortened_outputs"], 1)

    def test_many_results_fit_global_budget_and_keep_all_pairs(self):
        incoming = []
        for i in range(20):
            incoming.extend(
                [
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {"id": str(i), "function": {"name": "read_file", "arguments": "{}"}}
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": str(i),
                        "content": "BEGIN" + "x" * 20000 + "END",
                    },
                ]
            )
        result, stats = fit_tool_outputs(incoming, 35000)
        self.assertEqual(len(result), 40)
        self.assertLessEqual(stats["sent_chars"], 35000)
        self.assertEqual(
            [m["tool_call_id"] for m in result if m["role"] == "tool"], list(map(str, range(20)))
        )

    def test_tool_text_blocks_keep_other_content(self):
        incoming = history(
            [
                {"type": "text", "text": "x" * 250000},
                {"type": "image_url", "image_url": {"url": "data:unchanged"}},
            ]
        )
        result, _ = fit_tool_outputs(incoming, 5000)
        self.assertEqual(result[-1]["content"][1], incoming[-1]["content"][1])
        self.assertIn("OUTPUT ABBREVIATED", result[-1]["content"][0]["text"])

    def test_never_shorten_user_or_system_instructions_or_call_arguments(self):
        for role in ("user", "system", "developer", "assistant"):
            with self.subTest(role=role):
                incoming = [{"role": role, "content": "x" * 200000}]
                with self.assertRaises(ToolRequestError):
                    ToolBridge.from_request(body(messages=incoming)).prompt(incoming)
        incoming = history("small")
        incoming[-2]["tool_calls"][0]["function"]["arguments"] = json.dumps({"path": "x" * 200000})
        with self.assertRaises(ValueError):
            fit_tool_outputs(incoming, 10000)


class BudgetHTTPTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = HTTPTests.asyncSetUp
    asyncTearDown = HTTPTests.asyncTearDown

    async def test_huge_result_then_followup_reuses_same_chat_and_original_history_hashes(self):
        self.driver.answers = [
            {"content": None, "tool_calls": [CALL]},
            {"content": "Command failed, diagnostic retained", "tool_calls": []},
            {"content": "Same context", "tool_calls": []},
        ]
        r = await self.client.post("/v1/chat/completions", json=body())
        msg = (await r.json())["choices"][0]["message"]
        incoming = MESSAGES + [
            msg,
            {
                "role": "tool",
                "tool_call_id": msg["tool_calls"][0]["id"],
                "content": "CommandNotFoundException\n" * 16000,
            },
        ]
        r = await self.client.post("/v1/chat/completions", json=body(messages=incoming))
        self.assertEqual(r.status, 200)
        reply = (await r.json())["choices"][0]["message"]
        self.assertIn("OUTPUT ABBREVIATED", self.driver.prompts[1])
        self.assertLess(len(self.driver.prompts[1]), 180000)
        self.assertEqual(self.driver.navigations, 1)
        incoming.extend([reply, {"role": "user", "content": "Continue"}])
        r = await self.client.post("/v1/chat/completions", json=body(messages=incoming))
        await r.read()
        self.assertEqual(r.status, 200)
        self.assertEqual(self.driver.navigations, 1)
        self.assertNotIn("CommandNotFoundException", self.driver.prompts[2])


del HTTPTests

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from chatgpt_web2api.completion_detector import CompletionDetector
from chatgpt_web2api.tool_bridge import ToolBridge, ToolProtocolError
from chatgpt_web2api.turn_anchor import TurnAnchor, TurnTextResult


class StructuredDOMTests(unittest.IsolatedAsyncioTestCase):
    async def run_dom(
        self,
        value,
        bridge,
        generating_polls=0,
        complete_but_streaming=False,
        virtualized=False,
        unsafe_markup=False,
        literal_text=None,
        literal=True,
    ):
        polls = 0
        stopped = False

        async def js(expr):
            nonlocal polls, stopped
            if 'const kind="stop"' in expr:
                stopped = True
                return json.dumps({"status": "ready", "x": 10, "y": 20})
            if expr.startswith("!!document.querySelector"):
                return not stopped
            if "text: t.slice" in expr:
                return '{"text":""}'
            if "if(!last)return" in expr:
                return value
            if expr.endswith(".length"):
                return "3" if virtualized else "1"
            polls += 1
            generating = (polls <= generating_polls or complete_but_streaming) and not stopped
            visible = value[:-22] if generating and not complete_but_streaming else value
            if complete_but_streaming and generating:
                visible += "_"
            data = {
                "text": visible,
                "md_text": visible,
                "html_len": 400,
                "child_count": 1,
                "has_action": True,
                "is_thinking": False,
                "is_generating": generating,
                "unsafe_markup": unsafe_markup,
                "literal": literal,
            }
            if literal_text is not None:
                data["agent_text"] = literal_text
            return json.dumps(data)

        driver = SimpleNamespace(
            _current_conv_id="test-conv",
            _js_strict=js,
            _cdp=AsyncMock(),
            _fetch_end_turn_for_turn=AsyncMock(
                side_effect=AssertionError("Structured DOM must not fetch backend")
            ),
        )
        detector = CompletionDetector(driver)
        async for chunk in detector.stream_until_complete(
            initial_count=3 if virtualized else 0,
            timeout=4,
            turn_anchor=TurnAnchor(sent_text="test", mode="fresh_chat"),
            response_validator=bridge.validated_frame,
            response_marker=bridge.opening if virtualized else None,
        ):
            pass
        driver._fetch_end_turn_for_turn.assert_not_called()
        return detector.validated_dom_text

    def bridge(self):
        return ToolBridge.from_request(
            {
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "parameters": {
                                "type": "object",
                                "properties": {"path": {"type": "string"}},
                                "required": ["path"],
                            },
                        },
                    }
                ],
                "messages": [{"role": "user", "content": "Analyze project"}],
            }
        )

    async def test_finished_tool_call_uses_nonce_without_backend(self):
        b = self.bridge()
        value = (
            b.opening
            + json.dumps(
                {
                    "content": "Je poursuis.",
                    "tool_calls": [{"name": "read_file", "arguments": {"path": "README.md"}}],
                }
            )
            + "</web2api_response>"
        )
        self.assertEqual(await self.run_dom(value, b), value)

    async def test_final_content_preserves_code_spacing_and_newlines(self):
        b = self.bridge()
        content = "```python\ndef addition(a, b):\n    return a + b\n```"
        value = (
            b.opening + json.dumps({"content": content, "tool_calls": []}) + "</web2api_response>"
        )
        result = await self.run_dom(value, b)
        self.assertEqual(b.parse(result)["content"], content)

    async def test_wrong_nonce_cannot_complete_or_emit_tools(self):
        b = self.bridge()
        value = (
            '<web2api_response nonce="wrong">'
            + json.dumps({"content": "Old answer", "tool_calls": []})
            + "</web2api_response>"
        )
        with self.assertRaises(ToolProtocolError):
            await self.run_dom(value, b)

    async def test_invalid_call_cannot_complete_or_emit_tools(self):
        b = self.bridge()
        value = (
            b.opening
            + json.dumps(
                {"content": None, "tool_calls": [{"name": "run_unknown", "arguments": {}}]}
            )
            + "</web2api_response>"
        )
        with self.assertRaises(ToolProtocolError):
            await self.run_dom(value, b)

    async def test_action_row_during_generation_does_not_trigger_early_repair(self):
        b = self.bridge()
        value = (
            b.opening
            + json.dumps({"content": "Finished", "tool_calls": []})
            + "</web2api_response>"
        )
        self.assertEqual(await self.run_dom(value, b, generating_polls=4), value)

    async def test_complete_frame_stops_lingering_stream_before_delivery(self):
        b = self.bridge()
        value = (
            b.opening
            + json.dumps({"content": "Finished", "tool_calls": []})
            + "</web2api_response>"
        )
        self.assertEqual(await self.run_dom(value, b, complete_but_streaming=True), value)

    async def test_virtualized_count_stays_three_but_new_nonce_completes(self):
        b = self.bridge()
        value = (
            b.opening
            + json.dumps({"content": "New answer", "tool_calls": []})
            + "</web2api_response>"
        )
        self.assertEqual(await self.run_dom(value, b, virtualized=True), value)

    async def test_virtualized_code_viewer_uses_exact_completed_backend_frame(self):
        """A CodeMirror viewport may expose only a prefix after backend end_turn."""
        b = self.bridge()
        value = (
            b.opening
            + json.dumps({"content": "Backend complete", "tool_calls": []})
            + "</web2api_response>"
        )

        async def js(expr):
            if "text: t.slice" in expr:
                return '{"text":""}'
            if "if(!last)return" in expr:
                return b.opening[:28]
            if expr.endswith(".length"):
                return "3"
            raise AssertionError(f"Unexpected DOM read: {expr[:100]}")

        driver = SimpleNamespace(
            _current_conv_id=None,
            _js_strict=js,
            _get_live_conversation_id_best_effort=AsyncMock(return_value="conv-exact"),
            _fetch_text_for_turn=AsyncMock(
                return_value=TurnTextResult(status="matched", text=value)
            ),
            _fetch_end_turn_for_turn=AsyncMock(),
        )
        detector = CompletionDetector(driver)
        async for _ in detector.stream_until_complete(
            initial_count=3,
            timeout=4,
            turn_anchor=TurnAnchor(
                sent_text="test",
                mode="captured_id",
                captured_user_message_id="user-exact",
            ),
            response_validator=b.validated_frame,
            response_marker=b.opening,
        ):
            pass
        self.assertEqual(detector.validated_dom_text, value)
        driver._fetch_text_for_turn.assert_awaited_once()
        driver._fetch_end_turn_for_turn.assert_not_awaited()

    async def test_virtualized_old_nonce_cannot_be_accepted(self):
        from chatgpt_web2api.cdp_driver import GenerationStuckError

        b = self.bridge()
        value = (
            '<web2api_response nonce="old">'
            + json.dumps({"content": "Old", "tool_calls": []})
            + "</web2api_response>"
        )
        with self.assertRaises(GenerationStuckError):
            await self.run_dom(value, b, virtualized=True)

    async def test_inline_markdown_that_loses_underscores_is_rejected(self):
        b = self.bridge()
        value = (
            b.opening
            + json.dumps({"content": "$.Name and $.Length", "tool_calls": []})
            + "</web2api_response>"
        )
        with self.assertRaises(ToolProtocolError):
            await self.run_dom(value, b, unsafe_markup=True)

    async def test_literal_code_block_excludes_copy_label_and_preserves_shell_characters(self):
        b = self.bridge()
        content = "items | ForEach-Object { $_.Name; $_.Length }; ** _ ` < > &"
        value = (
            b.opening + json.dumps({"content": content, "tool_calls": []}) + "</web2api_response>"
        )
        result = await self.run_dom("json Copy code " + value, b, literal_text=value)
        self.assertEqual(b.parse(result)["content"], content)

    async def test_unfenced_text_is_rejected_even_without_emphasis_elements(self):
        b = self.bridge()
        value = (
            b.opening
            + json.dumps({"content": "A rendered backslash can also be lost", "tool_calls": []})
            + "</web2api_response>"
        )
        with self.assertRaises(ToolProtocolError):
            await self.run_dom(value, b, literal=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)

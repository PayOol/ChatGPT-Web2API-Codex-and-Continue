import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from chatgpt_web2api.cdp_driver import SendReadinessError
from chatgpt_web2api.chatgpt_dom import SEND_BUTTON_BROAD_SELECTOR, ChatGPTDom
from chatgpt_web2api.composer_transport import click_control, settle_completed_turn, wait_idle


class ComposerTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_busy_or_missing_or_occluded_never_dispatches_input(self):
        for status in ("busy", "missing", "occluded"):
            d = SimpleNamespace(
                _js_strict=AsyncMock(return_value=json.dumps({"status": status})), _cdp=AsyncMock()
            )
            self.assertEqual(await click_control(d, "send"), status)
            d._cdp.assert_not_awaited()

    async def test_send_uses_single_trusted_click(self):
        d = SimpleNamespace(
            _js_strict=AsyncMock(return_value=json.dumps({"status": "ready", "x": 14, "y": 25})),
            _cdp=AsyncMock(),
        )
        self.assertEqual(await click_control(d, "send"), "clicked")
        self.assertEqual(
            [c.args[1]["type"] for c in d._cdp.call_args_list],
            ["mouseMoved", "mousePressed", "mouseReleased"],
        )
        self.assertTrue(all(c.args[0] == "Input.dispatchMouseEvent" for c in d._cdp.call_args_list))
        script = d._js_strict.call_args.args[0]
        self.assertIn("kind==='send'&&stop", script)
        self.assertIn("b.dataset.testid!=='stop-button'", script)
        self.assertNotIn("dispatchEvent", script)

    def test_legacy_fallback_excludes_submit_stop_button(self):
        self.assertEqual(SEND_BUTTON_BROAD_SELECTOR.count(':not([data-testid="stop-button"])'), 2)

    async def test_send_readiness_failure_does_not_claim_sent(self):
        from chatgpt_web2api.breakers import BreakerKind, BreakerRegistry

        d = SimpleNamespace(
            _js_strict=AsyncMock(return_value='{"status":"busy"}'), _cdp=AsyncMock(),
            _capture_selector_diagnostic=AsyncMock(), _breakers=BreakerRegistry(),
        )
        with patch("chatgpt_web2api.chatgpt_dom.SEND_BUTTON_POLL_MAX_WAIT_S", 0):
            with self.assertRaisesRegex(SendReadinessError, "not dispatched"):
                await ChatGPTDom(d).click_send()
        self.assertEqual(len(d._breakers._states[BreakerKind.COMPOSER_SEND_READINESS].recent_failures), 1)
        d._cdp.assert_not_awaited()


    async def test_idle_parser_handles_false_values(self):
        for v in (False, "false", "0", 0):
            self.assertTrue(
                await wait_idle(SimpleNamespace(_js_strict=AsyncMock(return_value=v)), 0)
            )
        self.assertFalse(
            await wait_idle(SimpleNamespace(_js_strict=AsyncMock(return_value="true")), 0)
        )

    async def test_completed_frame_settles_without_navigation_when_stop_works(self):
        d = self.driver()
        with (
            patch(
                "chatgpt_web2api.composer_transport.wait_idle", AsyncMock(side_effect=[False, True])
            ),
            patch(
                "chatgpt_web2api.composer_transport.click_control",
                AsyncMock(return_value="clicked"),
            ) as click,
        ):
            await settle_completed_turn(d, "frame")
            click.assert_awaited_once_with(d, "stop")
        d.navigate_conversation.assert_not_awaited()

    def driver(self, **updates):
        snap = dict(literal=True, paired=True, conversation="same-chat", assistant="frame")
        snap.update(updates)
        return SimpleNamespace(
            _current_conv_id="same-chat",
            read_agent_exchange=AsyncMock(return_value=snap),
            navigate_conversation=AsyncMock(),
        )

    async def test_changed_or_unverified_turn_never_stopped(self):
        for update in (
            {"literal": False},
            {"paired": False},
            {"conversation": "another-chat"},
            {"assistant": "different frame"},
        ):
            d = self.driver(**update)
            with (
                patch(
                    "chatgpt_web2api.composer_transport.wait_idle", AsyncMock(return_value=False)
                ),
                patch("chatgpt_web2api.composer_transport.click_control", AsyncMock()) as click,
            ):
                with self.assertRaises(SendReadinessError):
                    await settle_completed_turn(d, "frame")
                click.assert_not_awaited()
            d.navigate_conversation.assert_not_awaited()

    async def test_stale_stop_reloads_only_same_completed_conversation_once(self):
        d = self.driver()
        with (
            patch(
                "chatgpt_web2api.composer_transport.wait_idle",
                AsyncMock(side_effect=[False, False, True]),
            ),
            patch(
                "chatgpt_web2api.composer_transport.click_control",
                AsyncMock(return_value="clicked"),
            ),
        ):
            await settle_completed_turn(d, "frame")
        d.navigate_conversation.assert_awaited_once_with("same-chat")

    async def test_persistent_busy_ui_is_explicit_error(self):
        d = self.driver()
        with (
            patch("chatgpt_web2api.composer_transport.wait_idle", AsyncMock(return_value=False)),
            patch(
                "chatgpt_web2api.composer_transport.click_control",
                AsyncMock(return_value="clicked"),
            ),
        ):
            with self.assertRaisesRegex(SendReadinessError, "still blocks"):
                await settle_completed_turn(d, "frame")
        self.assertEqual(d.navigate_conversation.await_count, 1)


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from datetime import UTC
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from chatgpt_web2api.backend_client import BackendClient, _ProjectionRateLimit


class ProjectionTests(unittest.IsolatedAsyncioTestCase):
    def client(self, replies):
        driver = SimpleNamespace(
            ensure_token=AsyncMock(),
            _access_token="test-only",
            _breakers=None,
            _js_with_data_strict=AsyncMock(side_effect=[json.dumps(r) for r in replies]),
        )
        return BackendClient(driver), driver

    async def test_429_retries_same_read_and_honors_retry_after(self):
        client, driver = self.client(
            [{"__status": 429, "retry_after": "17"}, {"nodes": {}, "current_node": None}]
        )
        with patch("chatgpt_web2api.backend_client.asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = await client._fetch_recent_conversation_projection("conversation-test")
        self.assertEqual(result["nodes"], {})
        self.assertEqual(driver._js_with_data_strict.call_count, 2)
        self.assertGreater(sleep.call_args.args[0], 16)
        self.assertEqual(
            driver._js_with_data_strict.call_args_list[0],
            driver._js_with_data_strict.call_args_list[1],
        )

    async def test_repeated_429_retains_cooldown_for_next_poll(self):
        client, driver = self.client([{"__status": 429}] * 3 + [{"nodes": {}}])
        with patch("chatgpt_web2api.backend_client.asyncio.sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaises(_ProjectionRateLimit):
                await client._fetch_recent_conversation_projection("same")
            await client._fetch_recent_conversation_projection("same")
        self.assertEqual(sleep.call_count, 3)
        self.assertTrue(all(call.args[0] > 29 for call in sleep.call_args_list))

    async def test_normal_reads_are_throttled(self):
        client, _ = self.client([{"nodes": {}}, {"nodes": {}}])
        with patch("chatgpt_web2api.backend_client.asyncio.sleep", new_callable=AsyncMock) as sleep:
            await client._fetch_recent_conversation_projection("one")
            await client._fetch_recent_conversation_projection("two")
        self.assertEqual(sleep.call_count, 1)
        self.assertGreater(sleep.call_args.args[0], 1)

    async def test_http_date_retry_after(self):
        client, _ = self.client([{"__status": 429, "retry_after": "Mon, 21 Sep 2026 10:00:30 GMT"}])
        from datetime import datetime

        now = datetime(2026, 9, 21, 10, 0, 0, tzinfo=UTC).timestamp()
        with patch("chatgpt_web2api.backend_client.time.time", return_value=now):
            with self.assertRaises(_ProjectionRateLimit) as raised:
                await client._fetch_recent_conversation_projection_once("one")
        self.assertEqual(raised.exception.retry_after, 30)

    async def test_cancel_during_cooldown_does_not_fetch(self):
        import asyncio
        import time

        client, driver = self.client([])
        client._projection_not_before = time.monotonic() + 30
        with patch(
            "chatgpt_web2api.backend_client.asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError,
        ):
            with self.assertRaises(asyncio.CancelledError):
                await client._fetch_recent_conversation_projection("one")
        driver._js_with_data_strict.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "integration/tools/connected"))
import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from codex_rpc import CodexRPC
from server import public_tool, validate_local_refs


class GatewayGuards(unittest.IsolatedAsyncioTestCase):
    async def test_event_stream_hides_reasoning_and_preserves_output(self):
        client = CodexRPC()
        reader = asyncio.StreamReader()
        for item in [
            {
                "method": "item/completed",
                "params": {"item": {"type": "reasoning", "text": "not for the output stream"}},
            },
            {
                "method": "item/completed",
                "params": {"item": {"type": "agentMessage", "text": "Result"}},
            },
            {
                "method": "command/exec/outputDelta",
                "params": {"processId": "test", "deltaBase64": "T0s="},
            },
        ]:
            reader.feed_data((json.dumps(item) + "\n").encode())
        reader.feed_eof()
        client.process = SimpleNamespace(stdout=reader)
        await client.read()
        self.assertEqual(len(client.events), 2)
        self.assertEqual(client.events[0]["params"]["item"]["text"], "Result")
        self.assertNotIn("not for the output stream", json.dumps(client.events))

    async def test_host_permission_request_is_not_approved(self):
        client = CodexRPC()
        reader = asyncio.StreamReader()
        client.send = AsyncMock()
        reader.feed_data(
            json.dumps({"id": 12, "method": "mcpServer/elicitation/request", "params": {}}).encode()
            + b"\n"
        )
        reader.feed_eof()
        client.process = SimpleNamespace(stdout=reader)
        await client.read()
        self.assertEqual(client.send.call_args.args[0]["result"]["action"], "decline")

    def test_remote_schema_and_internal_only_tool_are_excluded(self):
        with self.assertRaises(ValueError):
            validate_local_refs({"properties": {"x": {"$ref": "https://example.com/schema"}}})
        validate_local_refs({"$ref": "#/definitions/Value"})
        self.assertFalse(
            public_tool({"description": "This tool must not be called directly by the model."})
        )
        self.assertTrue(public_tool({"description": "Lists projects."}))


if __name__ == "__main__":
    unittest.main()

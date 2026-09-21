"""Continue text-compatible adapter for the pinned Windows-MCP server.

Images are saved locally, never represented as images seen by a text model.
No remote listener, login task or telemetry is enabled.
"""

import asyncio
import base64
import json
import os
import uuid
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.server import Server
from mcp.server.stdio import stdio_server

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from media_registry import publish

BASE = Path(__file__).resolve().parent
CAPTURES = BASE / "captures"
NAMES = {
    "App",
    "Snapshot",
    "Screenshot",
    "Click",
    "Type",
    "Scroll",
    "Move",
    "Shortcut",
    "Wait",
    "WaitFor",
    "DisplayInventory",
    "MultiSelect",
    "MultiEdit",
    "Clipboard",
    "Notification",
}
server = Server("continue-windows")
upstream = None
catalog = []


def adapt_result(result, capture_dir=CAPTURES):
    content = []
    remaining = 24000
    for item in result.content:
        if item.type == "image":
            data = base64.b64decode(item.data, validate=True)
            if len(data) > 20_000_000:
                content.append(
                    types.TextContent(type="text", text="Screenshot exceeds 20 MB; not saved.")
                )
                continue
            from PIL import Image
            import io

            with Image.open(io.BytesIO(data)) as im:
                im.verify()
            message = json.dumps(publish(data, origin="computer"))
            content.append(types.TextContent(type="text", text=message))
        elif item.type == "text":
            value = item.text
            if len(value) > remaining:
                value = (
                    value[:remaining]
                    + "\n[UI output truncated. Focus a specific application and request a fresh Snapshot.]"
                )
            remaining = max(0, remaining - len(value))
            content.append(types.TextContent(type="text", text=value))
        elif item.type == "resource" and hasattr(item.resource, "text"):
            content.append(types.TextContent(type="text", text=item.resource.text[:remaining]))
            remaining = max(0, remaining - len(item.resource.text))
        else:
            content.append(
                types.TextContent(
                    type="text",
                    text=f"Unsupported {item.type} content omitted; no visual interpretation performed.",
                )
            )
    return types.CallToolResult(content=content, isError=result.isError)


@server.list_tools()
async def list_tools():
    return catalog


@server.call_tool()
async def call_tool(name, arguments):
    if name not in NAMES:
        raise ValueError("Unknown Computer Use tool")
    result = await upstream.call_tool(
        name, arguments, read_timeout_seconds=__import__("datetime").timedelta(seconds=60)
    )
    return adapt_result(result)


async def main():
    global upstream, catalog
    env = dict(
        os.environ,
        ANONYMIZED_TELEMETRY="false",
        WINDOWS_MCP_WATCHDOG="false",
        PYTHONIOENCODING="utf-8",
    )
    params = StdioServerParameters(
        command=os.environ.get(
            "W2A_COMPUTER_PYTHON", str(BASE / ".venv" / "Scripts" / "python.exe")
        ),
        args=["-m", "windows_mcp", "serve", "--tools", ",".join(sorted(NAMES))],
        env=env,
        cwd=os.getcwd(),
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            upstream = session
            catalog = (await session.list_tools()).tools
            actual = {t.name for t in catalog}
            if actual != NAMES:
                raise RuntimeError(f"Unexpected upstream tool catalog: {sorted(actual)}")
            for tool in catalog:
                # This adapter intentionally returns text blocks instead of
                # the upstream structured/image response contract.
                tool.outputSchema = None
                tool.description = (
                    (tool.description or "")
                    + " Use only for the user's authorized task. Observe the target application before input; refresh after each action."
                )
                if tool.name in {"Screenshot", "Snapshot"}:
                    tool.description += " Images are returned as registered local references. The configured Web2API vision bridge attaches their pixels to the next request. Prefer Snapshot(use_vision=false) for text controls; use Screenshot or Snapshot(use_vision=true) when pixels are needed."
            async with stdio_server() as (reader, writer):
                await server.run(reader, writer, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

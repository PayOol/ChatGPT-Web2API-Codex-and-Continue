"""Playwright MCP adapter: preserve tools, deliver images via Web2API registry."""

import asyncio, base64, json, sys, os
from pathlib import Path
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.server import Server
from mcp.server.stdio import stdio_server

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from media_registry import publish
from runtime_paths import node_executable

server = Server("continue-browser")
upstream = None
catalog = []


@server.list_tools()
async def list_tools():
    return catalog


@server.call_tool()
async def call_tool(name, arguments):
    if name not in {t.name for t in catalog}:
        raise ValueError("Unknown browser tool")
    r = await upstream.call_tool(
        name, arguments, read_timeout_seconds=__import__("datetime").timedelta(seconds=90)
    )
    content = []
    remaining = 30000
    for item in r.content:
        if item.type == "image":
            content.append(
                types.TextContent(
                    type="text",
                    text=json.dumps(
                        publish(base64.b64decode(item.data, validate=True), origin="browser")
                    ),
                )
            )
        elif item.type == "text":
            text = item.text[:remaining]
            remaining = max(0, remaining - len(text))
            if len(text) < len(item.text):
                text += "\n[Browser output truncated; use a targeted snapshot or query.]"
            content.append(types.TextContent(type="text", text=text))
        elif item.type == "resource" and hasattr(item.resource, "text"):
            content.append(types.TextContent(type="text", text=item.resource.text[:remaining]))
    return types.CallToolResult(content=content, isError=r.isError)


async def main():
    global upstream, catalog
    args = [
        str(Path(__file__).parent / "node_modules/@playwright/mcp/cli.js"),
        "--headless",
        "--isolated",
        "--image-responses",
        "allow",
    ]
    if os.environ.get("W2A_BROWSER_EXECUTABLE"):
        args += ["--executable-path", os.environ["W2A_BROWSER_EXECUTABLE"]]
    else:
        args += ["--browser", "msedge"]
    p = StdioServerParameters(command=node_executable(), args=args)
    async with stdio_client(p) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            upstream = session
            catalog = (await session.list_tools()).tools
            for tool in catalog:
                tool.outputSchema = None
                if "screenshot" in tool.name:
                    tool.description += " Image pixels are sent via registered references to the configured Web2API vision bridge."
            async with stdio_server() as (reader, writer):
                await server.run(reader, writer, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

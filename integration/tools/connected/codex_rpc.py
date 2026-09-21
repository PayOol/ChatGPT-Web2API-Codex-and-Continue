"""JSONL client for the user's installed Codex App Server. No model turns."""

import asyncio, json, os, tomllib, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runtime_paths import codex_executable, node_executable


class CodexRPC:
    def __init__(self):
        self.process = None
        self.pending = {}
        self.sequence = 0
        self.reader = None
        self.requests = []
        self.events = []
        self.event_sequence = 0

    async def start(self):
        config_path = (
            Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
        )
        config = (
            tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
            if config_path.exists()
            else {}
        )
        args = [str(codex_executable()), "app-server", "--stdio", "-c", "features.apps=true"]
        hostinger = os.environ.get("W2A_HOSTINGER_ENTRY")
        if hostinger and not any(
            name.startswith("hostinger-") for name in config.get("mcp_servers", {})
        ):
            args += [
                "-c",
                "mcp_servers.hostinger-web2api.command=" + json.dumps(node_executable()),
                "-c",
                "mcp_servers.hostinger-web2api.args=" + json.dumps([hostinger]),
                "-c",
                "mcp_servers.hostinger-web2api.startup_timeout_sec=60",
            ]
        for name in config.get("mcp_servers", {}):
            if not name.startswith("hostinger-"):
                args += ["-c", f"mcp_servers.{name}.enabled=false"]
            else:
                values = [
                    v.replace("hostinger-api-mcp@latest", "hostinger-api-mcp@1.63.2")
                    for v in config["mcp_servers"][name].get("args", [])
                ]
                args += ["-c", f"mcp_servers.{name}.args=" + json.dumps(values)]
        self.process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=32 * 1024 * 1024,
            creationflags=0x08000000,
        )
        self.reader = asyncio.create_task(self.read())
        await self.call(
            "initialize",
            {
                "clientInfo": {"name": "continue-connected-tools", "version": "1.0.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        await self.send({"method": "initialized"})

    async def send(self, message):
        self.process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
        await self.process.stdin.drain()

    async def read(self):
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if "method" in message:
                    item = message.get("params", {}).get("item", {})
                    reasoning = message["method"] == "item/completed" and item.get(
                        "type", ""
                    ).lower().startswith("reasoning")
                    if not reasoning and message["method"] in (
                        "turn/completed",
                        "error",
                        "item/completed",
                        "command/exec/outputDelta",
                    ):
                        self.event_sequence += 1
                        self.events.append(
                            {
                                "cursor": self.event_sequence,
                                "method": message["method"],
                                "params": message.get("params", {}),
                            }
                        )
                        self.events = self.events[-500:]
                    if "id" in message:
                        self.requests.append(message["method"])
                        self.requests = self.requests[-20:]
                        # Do not silently grant approvals/permissions requested by a provider.
                        if message["method"] == "mcpServer/elicitation/request":
                            await self.send(
                                {
                                    "id": message["id"],
                                    "result": {"action": "decline", "content": None},
                                }
                            )
                        else:
                            await self.send(
                                {
                                    "id": message["id"],
                                    "error": {
                                        "code": -32000,
                                        "message": "This integration cannot approve host UI requests. Complete this action in the connected application.",
                                    },
                                }
                            )
                elif message.get("id") in self.pending:
                    future = self.pending.pop(message["id"])
                    if not future.done():
                        future.set_result(message)
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("Codex integration connection closed"))
            self.pending.clear()

    async def call(self, method, params, timeout=120):
        self.sequence += 1
        id = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[id] = future
        try:
            await self.send({"id": id, "method": method, "params": params})
            message = await asyncio.wait_for(future, timeout)
            if "error" in message:
                raise RuntimeError(message["error"].get("message", "Codex RPC error"))
            return message.get("result", {})
        finally:
            self.pending.pop(id, None)

    async def close(self):
        if self.process:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 8)
            except TimeoutError:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), 3)
                except TimeoutError:
                    pass
        if self.reader:
            self.reader.cancel()

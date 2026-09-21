"""Read-only installation checks. Real account calls are never used as smoke tests."""

from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import urllib.request


def examine(root: Path, offline=False):
    failures = []
    checks = []

    def check(name, ok):
        checks.append({"check": name, "passed": bool(ok)})
        if not ok:
            failures.append(name)

    manifest = json.loads((root / "installation.json").read_text(encoding="utf-8"))
    env = json.loads((root / "environment.json").read_text(encoding="utf-8"))
    os.environ.update(env)
    check("Managed installation identity", manifest.get("product") == "Web2API-Continue")
    for name in ["user-data", "extensions", "shared-data"]:
        check("Portable editor " + name, (root / "apps/vscode/data" / name).is_dir())
    check("Continue in portable editor", Path(manifest["extension"]).parent.resolve()
          == (root / "apps/vscode/data/extensions").resolve())
    check("Continue managed profile resolver",
          (Path(manifest["extension"]) / "out/web2api-managed-environment.cjs").is_file())
    for name in [
        "venv/Scripts/python.exe",
        "computer-venv/Scripts/python.exe",
        "apps/node/node.exe",
        "apps/git/cmd/git.exe",
        "apps/rg/rg.exe",
        "apps/vscode/Code.exe",
        "tools/local-capabilities/server.py",
        "tools/browser/continue_server.py",
        "tools/computer-use/continue_server.py",
        "tools/vision/server.py",
        "tools/connected/server.py",
    ]:
        check(name, (root / name).is_file())
    check("Browser installed", Path(manifest["browser"]).is_file())
    check("Native Codex installed", Path(manifest["codex"]).is_file())
    import chatgpt_web2api
    from chatgpt_web2api import api_server, vision_bridge

    check("Web2API distribution version", chatgpt_web2api.__version__ == manifest["version"])
    check(
        "Bundled image registry",
        vision_bridge.registry.__name__ == "chatgpt_web2api.media_registry",
    )
    import yaml

    config = yaml.safe_load((root / "continue/config.yaml").read_text(encoding="utf-8"))
    servers = config.get("mcpServers", [])
    check(
        "Continue long generation wait",
        any(
            m.get("name") == "ChatGPT Web2API" and m.get("requestOptions", {}).get("timeout") == 0
            for m in config.get("models", [])
        ),
    )
    check(
        "Continue long wait helper",
        (Path(manifest["extension"]) / "out/continue-long-wait.local.cjs").is_file(),
    )
    from chatgpt_web2api.config import Config
    from chatgpt_web2api.completion_detector import DetectorBudgets

    bridge_config = Config.load(str(root / "config.json"))
    check(
        "Bridge long generation wait",
        bridge_config.server.request_timeout == 0
        and all(
            DetectorBudgets.from_config(bridge_config.chatgpt, model) == DetectorBudgets(0, 0, 0)
            for model in ("auto", "gpt-5-5-thinking")
        ),
    )
    check(
        "Five MCP servers configured",
        {"Local", "Browser", "Computer", "Vision", "Connected"}.issubset(
            {s["name"] for s in servers}
        ),
    )
    for s in servers:
        if s["name"] in {"Local", "Browser", "Computer", "Vision", "Connected"}:
            check(
                s["name"] + " executable and script",
                Path(s["command"]).is_file() and Path(s["args"][1]).is_file(),
            )
    for relative, expected in manifest["continue_patches"].items():
        path = Path(manifest["extension"]) / relative
        check(
            "Continue patch " + relative, hashlib.sha256(path.read_bytes()).hexdigest() == expected
        )
    flags = json.loads((root / "continue/full-access.local.json").read_text())
    check(
        "Automatic access active",
        flags.get("enabled") and flags.get("scope") == "all-configured-tools",
    )
    flags = json.loads((root / "continue/auto-compaction.local.json").read_text())
    check("Automatic compaction active", flags.get("enabled") and flags.get("threshold") == 0.75)
    with sqlite3.connect(
        (root / "apps/vscode/data/user-data/User/globalStorage/state.vscdb").as_uri() + "?mode=ro", uri=True
    ) as conn:
        row = conn.execute(
            "SELECT value FROM ItemTable WHERE key='extensions.donotAutoUpdate'"
        ).fetchone()
    check("Continue auto-update disabled", bool(row) and "continue.continue" in json.loads(row[0]))
    result = {
        "version": manifest["version"],
        "structural_checks": checks,
        "passed": not failures,
        "failures": failures,
    }
    if not offline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{manifest['api_port']}/health", timeout=5
            ) as response:
                health = json.load(response)
            result["service"] = {
                k: health.get(k)
                for k in [
                    "status",
                    "chrome_running",
                    "driver_connected",
                    "image_inputs",
                    "last_error",
                ]
            }
            result["chatgpt_connection"] = (
                "browser-connected; no model request tested"
                if health.get("driver_connected")
                else "login-or-startup-required"
            )
        except Exception as exc:
            result["service"] = {"status": "not-reachable", "detail": str(exc)}
        process = subprocess.run(
            [manifest["codex"], "login", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        result["codex_connection"] = (
            "authenticated"
            if process.returncode == 0
            else "sign-in-required: open Connect-Codex.cmd"
        )
        result["providers"] = (
            "Dependent on each account. Discover from Connected; no provider call performed by this diagnostic."
        )
    return result, servers


async def tool_inventory(servers):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from datetime import timedelta

    expected = {"Local": 17, "Browser": 25, "Computer": 15, "Vision": 1, "Connected": 9}

    async def one(server):
        environment = {**os.environ, **server.get("env", {})}
        parameters = StdioServerParameters(
            command=server["command"], args=server["args"], env=environment, cwd=str(Path.cwd())
        )
        try:
            async with stdio_client(parameters) as (reader, writer):
                async with ClientSession(
                    reader, writer, read_timeout_seconds=timedelta(seconds=90)
                ) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    return {
                        "server": server["name"],
                        "count": len(tools),
                        "expected": expected[server["name"]],
                        "passed": len(tools) == expected[server["name"]],
                        "tools": [t.name for t in tools],
                    }
        except Exception as exc:
            return {"server": server["name"], "passed": False, "error": str(exc)}

    return await asyncio.gather(*(one(s) for s in servers if s["name"] in expected))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--check-tools", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result, servers = examine(args.root.resolve(), args.offline)
    if args.check_tools:
        result["tools"] = asyncio.run(tool_inventory(servers))
        result["passed"] = result["passed"] and all(t["passed"] for t in result["tools"])
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text)
    sys.exit(0 if result["passed"] else 1)

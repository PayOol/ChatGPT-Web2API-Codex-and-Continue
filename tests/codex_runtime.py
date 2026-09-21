"""Verify the model list through the real Codex App Server, without a model turn."""

import argparse
import asyncio
import json
import os
from pathlib import Path


async def verify(binary: Path):
    process = await asyncio.create_subprocess_exec(
        str(binary),
        "app-server",
        "--stdio",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        limit=32 * 1024 * 1024,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )

    async def send(value):
        process.stdin.write((json.dumps(value) + "\n").encode())
        await process.stdin.drain()

    async def call(number, method, params):
        await send({"id": number, "method": method, "params": params})
        while line := await asyncio.wait_for(process.stdout.readline(), 45):
            value = json.loads(line)
            if value.get("id") == number:
                if "error" in value:
                    raise RuntimeError(f"Codex {method} failed: {value['error'].get('code')}")
                return value["result"]
        raise RuntimeError("Codex closed before returning its model list")

    try:
        await call(
            1,
            "initialize",
            {
                "clientInfo": {"name": "web2api-model-check", "version": "0.4.3"},
                "capabilities": {"experimentalApi": True},
            },
        )
        await send({"method": "initialized"})
        models, cursor, number = [], None, 2
        while True:
            page = await call(number, "model/list", {"limit": 100, "cursor": cursor})
            models.extend(page["data"])
            cursor = page.get("nextCursor")
            if not cursor:
                break
            number += 1
        selected = [m for m in models if m.get("model", m.get("id")) == "chatgpt-web2api/auto"]
        if len(selected) != 1:
            raise RuntimeError("ChatGPT Web2API is not unique in the real Codex model list")
        return {
            "passed": True,
            "verification": "native Codex app-server model/list",
            "model": selected[0],
            "model_count": len(models),
            "model_turn_performed": False,
        }
    finally:
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 5)
        except TimeoutError:
            process.terminate()
            await process.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.root / "installation.json").read_text(encoding="utf-8"))
    result = asyncio.run(verify(args.binary or Path(manifest["codex"])))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    (args.root / "logs/codex-runtime.json").write_text(text + "\n", encoding="utf-8")
    # Redirected Windows consoles may still use cp1252; keep the artifact UTF-8
    # and escape non-ASCII characters only in the console transport.
    print(json.dumps(result, ensure_ascii=True, indent=2))

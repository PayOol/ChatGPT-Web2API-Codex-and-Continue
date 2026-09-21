"""Long-lived Chat Completions transport for the OpenCodex model adapter.

Codex owns its tools. This endpoint only carries their schemas, requests and
results through the same validated browser protocol used by the API. The
OpenCodex chat adapter discards SSE comments, so explicitly labelled bridge
status messages keep its upstream watchdog alive while the model is silent.
They are transport status, never purported model reasoning or tool results.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import suppress

from aiohttp import web

HEARTBEAT_SECONDS = 15
ERROR_GRACE_SECONDS = 0.1


class BufferedRequest:
    """Retain the caller's transport/auth; request only a validated full answer."""

    def __init__(self, request, body):
        self.original = request
        self.body = {**body, "stream": False}

    async def json(self):
        return self.body

    def __getattr__(self, name):
        return getattr(self.original, name)


async def models(server, request):
    error = server._check_auth(request)
    if error is not None:
        return error
    return web.json_response(
        {
            "object": "list",
            "data": [
                {
                    "id": "auto",
                    "object": "model",
                    "created": 0,
                    "owned_by": "chatgpt-web",
                    "name": "ChatGPT Web2API",
                }
            ],
        }
    )


async def chat(server, request):
    error = server._check_auth(request)
    if error is not None:
        return error
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        body = None
    if not isinstance(body, dict) or body.get("model", "auto") != "auto":
        return web.json_response(
            {
                "error": {
                    "message": "This Codex route requires an object and model=auto",
                    "type": "invalid_request_error",
                }
            },
            status=400,
        )
    if not body.get("stream", False):
        return await server._handle_chat(BufferedRequest(request, body))

    pending = asyncio.create_task(server._handle_chat(BufferedRequest(request, body)))
    started = time.monotonic()
    common = {
        "id": "chatcmpl-" + uuid.uuid4().hex,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "auto",
    }
    response = web.StreamResponse(
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )

    async def emit(data):
        await response.write(("data: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode())

    async def delta(value, finish=None):
        await emit({**common, "choices": [{"index": 0, "delta": value, "finish_reason": finish}]})

    try:
        # Authentication/validation/circuit errors which arrive immediately retain
        # their HTTP status. Later failures use the OpenAI streaming error shape.
        done, _ = await asyncio.wait({pending}, timeout=ERROR_GRACE_SECONDS)
        if done and pending.result().status >= 400:
            return pending.result()
        await response.prepare(request)
        await response.write(b": ChatGPT Web2API connection ready\n\n")
        while not pending.done():
            done, _ = await asyncio.wait({pending}, timeout=HEARTBEAT_SECONDS)
            if not done:
                await delta(
                    {
                        "reasoning_content": (
                            "[Passerelle ChatGPT Web2API] Reponse attendue ; connexion active "
                            f"depuis {int(time.monotonic() - started)} s.\n"
                        )
                    }
                )
        result = pending.result()
        payload = json.loads(result.body)
        if result.status >= 400:
            await emit(payload)
        else:
            choice = payload["choices"][0]
            message = choice["message"]
            if message.get("content") is not None:
                await delta({"role": "assistant", "content": message["content"]})
            if message.get("tool_calls"):
                await delta(
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {"index": index, **call}
                            for index, call in enumerate(message["tool_calls"])
                        ],
                    }
                )
            await delta({}, choice["finish_reason"])
            await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        return response
    finally:
        if not pending.done():
            pending.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await pending

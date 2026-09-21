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

from .progress import Progress, current
from .responses_codec import ResponsesCodec
from .tool_bridge import ToolRequestError

HEARTBEAT_SECONDS = 15
ERROR_GRACE_SECONDS = 0.1


async def responses(server, request):
    """Native Responses stream with visible, explicitly labelled status summaries.

    The old Chat route remains compatible. Separate reasoning-summary items
    keep transport observations out of model answers and tool history.
    """
    error = server._check_auth(request)
    if error is not None:
        return error
    try:
        body = await request.json()
        codec = ResponsesCodec(body)
    except (ValueError, TypeError, ToolRequestError) as exc:
        return web.json_response({"error": {"message": str(exc), "type": "invalid_request_error"}}, status=400)
    sink = Progress()

    async def work():
        token = current.set(sink)
        try:
            return await server._handle_chat(BufferedRequest(request, codec.chat))
        finally:
            current.reset(token)

    pending = asyncio.create_task(work())
    response_id = "resp_" + uuid.uuid4().hex
    created = int(time.time())
    started = time.monotonic()
    items = []

    def snapshot(status, failure=None):
        value = {"id": response_id, "object": "response", "created_at": created,
                 "model": "auto", "status": status, "output": items,
                 "error": failure, "incomplete_details": None,
                 "usage": None}
        return value

    response = web.StreamResponse(headers={"Content-Type": "text/event-stream",
                                          "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    sequence = 0

    async def emit(kind, **fields):
        nonlocal sequence
        data = {"type": kind, "sequence_number": sequence, **fields}
        sequence += 1
        await response.write((f"event: {kind}\ndata: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode())

    try:
        if not body.get("stream", False):
            result = await pending
            if result.status >= 400:
                return result
            items.extend(codec.output(json.loads(result.body)["choices"][0]["message"]))
            return web.json_response(snapshot("completed"))
        done, _ = await asyncio.wait({pending}, timeout=ERROR_GRACE_SECONDS)
        if done and pending.result().status >= 400:
            return pending.result()
        await response.prepare(request)
        await emit("response.created", response=snapshot("in_progress"))
        await emit("response.in_progress", response=snapshot("in_progress"))
        progress_item = {"type": "reasoning", "id": "rs_" + uuid.uuid4().hex, "summary": []}
        progress_text = ""
        await emit("response.output_item.added", output_index=0, item=progress_item)
        await emit("response.reasoning_summary_part.added", item_id=progress_item["id"], output_index=0,
                   summary_index=0, part={"type": "summary_text", "text": ""})

        async def status(text):
            nonlocal progress_text
            # Only bounded, bridge-authored observations enter this channel.
            line = f"[Web2API · {int(time.monotonic() - started)} s] {text}\n"
            progress_text += line
            await emit("response.reasoning_summary_text.delta", item_id=progress_item["id"],
                       output_index=0, summary_index=0, delta=line)

        await status("Connexion établie. Préparation de la demande.")
        while not pending.done():
            observed = asyncio.create_task(sink.queue.get())
            try:
                ready, _ = await asyncio.wait({pending, observed}, timeout=HEARTBEAT_SECONDS,
                                              return_when=asyncio.FIRST_COMPLETED)
                if observed in ready:
                    await status(observed.result())
                elif not ready:
                    await status(sink.last + " Connexion toujours active.")
            finally:
                if not observed.done():
                    observed.cancel()
                with suppress(asyncio.CancelledError):
                    await observed
        while not sink.queue.empty():
            await status(sink.queue.get_nowait())
        result = pending.result()
        payload = json.loads(result.body)
        progress_item["summary"] = [{"type": "summary_text", "text": progress_text}]
        await emit("response.reasoning_summary_text.done", item_id=progress_item["id"],
                   output_index=0, summary_index=0, text=progress_text)
        await emit("response.reasoning_summary_part.done", item_id=progress_item["id"],
                   output_index=0, summary_index=0, part=progress_item["summary"][0])
        await emit("response.output_item.done", output_index=0, item=progress_item)
        items.append(progress_item)
        if result.status >= 400:
            await emit("response.failed", response=snapshot("failed", payload.get("error")))
        else:
            for item in codec.output(payload["choices"][0]["message"]):
                index = len(items)
                initial = {**item, "status": "in_progress"}
                if item["type"] == "message":
                    initial["content"] = []
                else:
                    field = "input" if item["type"] == "custom_tool_call" else "arguments"
                    initial[field] = ""
                await emit("response.output_item.added", output_index=index, item=initial)
                fields = {"item_id": item["id"], "output_index": index}
                if item["type"] == "message":
                    part = item["content"][0]
                    await emit("response.content_part.added", **fields, content_index=0,
                               part={**part, "text": ""})
                    await emit("response.output_text.delta", **fields, content_index=0, delta=part["text"])
                    await emit("response.output_text.done", **fields, content_index=0, text=part["text"])
                    await emit("response.content_part.done", **fields, content_index=0, part=part)
                else:
                    kind = "custom_tool_call_input" if field == "input" else "function_call_arguments"
                    await emit(f"response.{kind}.delta", **fields, delta=item[field])
                    await emit(f"response.{kind}.done", **fields, **{field: item[field]})
                await emit("response.output_item.done", output_index=index, item=item)
                items.append(item)
            await emit("response.completed", response=snapshot("completed"))
        await response.write_eof()
        return response
    finally:
        if not pending.done():
            pending.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await pending


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

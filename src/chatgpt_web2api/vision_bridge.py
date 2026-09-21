"""Validated image transport from Continue to the ChatGPT composer."""

import copy
import hashlib
import json
from pathlib import Path

from . import media_registry as registry


def normalize_images(messages):
    normalized = copy.deepcopy(messages)
    user_images = {}
    for i, message in enumerate(normalized):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for index, part in enumerate(content):
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            if message.get("role") != "user":
                raise ValueError("Inline images are accepted only in user messages")
            value = part.get("image_url", {})
            url = value.get("url", "") if isinstance(value, dict) else value
            image = registry.data_url(url)
            path = Path(image["image_file"])
            user_images.setdefault(i, []).append(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            content[index] = {
                "type": "text",
                "text": f"[User image SHA256:{digest}; actual pixels attached to its first request]",
            }
    return normalized, user_images


def images_for_turn(messages, user_images, offset):
    images = registry.collect_tool_images(messages[offset:])
    for i, paths in user_images.items():
        if i >= offset:
            images.extend(paths)
    images = list(dict.fromkeys(images))
    if len(images) > 4:
        raise ValueError("At most four new images can be attached per request")
    return [str(p) for p in images]


async def attach_images(driver, paths, timeout=60):
    """Use the observed normal file input; never send before thumbnails are ready."""
    import asyncio
    import time

    if not paths:
        return
    # Refuse to mix in any attachment the user may already be composing.
    before = json.loads(
        await driver._js_strict(
            """JSON.stringify((()=>{const f=document.querySelector('#prompt-textarea')?.closest('form');const i=f?.querySelector('input[type=file]#upload-files');return {ready:!!i&&!i.disabled,images:f?.querySelectorAll('img').length||0,files:i?.files?.length||0,generating:!!document.querySelector('[data-testid=stop-button]')}})())"""
        )
    )
    if not before["ready"] or before["images"] or before["files"] or before["generating"]:
        raise RuntimeError("Image upload requires an idle composer with no existing attachments")
    result = await driver._cdp(
        "Runtime.evaluate",
        {
            "expression": "document.querySelector('#prompt-textarea').closest('form').querySelector('input[type=file]#upload-files')",
            "returnByValue": False,
        },
    )
    object_id = result.get("result", {}).get("result", {}).get("objectId")
    if not object_id:
        raise RuntimeError("ChatGPT attachment input is unavailable")
    try:
        uploaded = await driver._cdp(
            "DOM.setFileInputFiles", {"objectId": object_id, "files": paths}, _retry=False
        )
        if "error" in uploaded:
            raise RuntimeError("ChatGPT file input rejected the image attachment")
    finally:
        await driver._cdp("Runtime.releaseObject", {"objectId": object_id})
    deadline = time.monotonic() + timeout
    stable = 0
    while time.monotonic() < deadline:
        await driver._dom.check_rate_limit()
        state = json.loads(
            await driver._js_strict(
                """JSON.stringify((()=>{const f=document.querySelector('#prompt-textarea')?.closest('form');const imgs=[...(f?.querySelectorAll('img')||[])];const b=f?.querySelector('[data-testid=send-button]');return {images:imgs.filter(i=>i.complete&&i.naturalWidth>0).length,sendReady:!!b&&!b.disabled,progress:!!f?.querySelector('[role=progressbar]'),alerts:[...document.querySelectorAll('[role=alert]')].map(e=>e.textContent).join(' ').slice(0,600)}})())"""
            )
        )
        if state["images"] >= len(paths) and state["sendReady"] and not state["progress"]:
            stable += 1
            if stable >= 3:
                return
        else:
            stable = 0
        await asyncio.sleep(0.4)
    raise RuntimeError(
        "Image attachment did not become ready; no message was sent. Inspect the existing composer before retrying."
    )

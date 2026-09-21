"""Validated image transport from Continue to the ChatGPT composer."""

import copy
import hashlib
import json
import logging
from pathlib import Path

from . import media_registry as registry

logger = logging.getLogger(__name__)


class ImageUploadError(RuntimeError):
    """Image preparation failed before click_send; no prompt was submitted."""


# FileList is the native picker's last selection, not ChatGPT's draft state:
# ChatGPT leaves it populated after submitting an image. Inspect draft chips,
# thumbnails and upload activity instead, including non-image attachments.
COMPOSER_STATE_JS = """(()=>{
    const f=document.querySelector('#prompt-textarea')?.closest('form');
    const input=f?.querySelector('input[type=file]#upload-files');
    const images=[...(f?.querySelectorAll('img')||[])];
    const attachments=[...(f?.querySelectorAll(
        '[data-testid*="attachment"],[data-testid*="file-thumbnail"],[data-testid*="file-pill"]'
    )||[])].length;
    const removals=[...(f?.querySelectorAll('button')||[])].filter(b=>
        /remove|supprimer|retirer/i.test(b.getAttribute('aria-label')||'')).length;
    const send=f?.querySelector('[data-testid=send-button]');
    return {input,state:{ready:!!input&&!input.disabled,
        images:images.length,attachments:attachments+removals,
        loaded:images.filter(i=>i.complete&&i.naturalWidth>0).length,
        files:input?.files?.length||0,
        generating:!!document.querySelector('[data-testid=stop-button]'),
        sendReady:!!send&&!send.disabled,
        progress:!!f?.querySelector('[role=progressbar],[aria-busy=true]')}};
})()"""


def _require_empty_composer(state):
    if not state["ready"]:
        raise RuntimeError("ChatGPT attachment input is unavailable or disabled; no image was sent")
    if state["generating"]:
        raise RuntimeError("ChatGPT is still generating; no image was sent")
    if state["images"] or state.get("attachments") or state.get("progress"):
        raise RuntimeError(
            "ChatGPT composer contains an unsent attachment or an upload in progress; "
            "no image was added. Finish or remove that draft attachment before retrying."
        )


def normalize_images(messages):
    normalized = copy.deepcopy(messages)
    user_images = {}
    known_calls = set()
    for i, message in enumerate(normalized):
        if message.get("role") == "assistant":
            known_calls.update(call.get("id") for call in message.get("tool_calls") or [])
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for index, part in enumerate(content):
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            role = message.get("role")
            if role == "tool":
                call_id = message.get("tool_call_id")
                if not call_id or call_id not in known_calls:
                    raise ValueError("Tool image requires a matching preceding tool call")
            elif role != "user":
                raise ValueError("Inline images require a user message or a matched tool result")
            value = part.get("image_url", {})
            url = value.get("url", "") if isinstance(value, dict) else value
            image = registry.data_url(url)
            path = Path(image["image_file"])
            user_images.setdefault(i, []).append(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            content[index] = {
                "type": "text",
                "text": f"[{role.title()} image SHA256:{digest}; actual pixels attached to its first request]",
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
    before = json.loads(await driver._js_strict(f"JSON.stringify(({COMPOSER_STATE_JS}).state)"))
    _require_empty_composer(before)
    if before["files"]:
        logger.info("Image upload: resetting stale file picker selection (%d)", before["files"])
    result = await driver._cdp(
        "Runtime.evaluate",
        {
            # Recheck and reset in the same evaluation. Clearing the native
            # input (without a change event) does not remove React attachments.
            # It also makes re-uploading the SAME screenshot fire a change event.
            "expression": "(()=>{const {input,state}=" + COMPOSER_STATE_JS + ";"
            "if(!state.ready||state.generating||state.images||state.attachments||state.progress)"
            "return null;input.value='';return input;})()",
            "returnByValue": False,
        },
    )
    object_id = result.get("result", {}).get("result", {}).get("objectId")
    if not object_id:
        raise RuntimeError("ChatGPT composer changed before image upload; no image was added")
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
        state = json.loads(await driver._js_strict(f"JSON.stringify(({COMPOSER_STATE_JS}).state)"))
        if state["generating"]:
            raise RuntimeError(
                "ChatGPT started generating during image upload; no send was clicked"
            )
        if state["loaded"] >= len(paths) and state["sendReady"] and not state["progress"]:
            stable += 1
            if stable >= 3:
                return
        else:
            stable = 0
        await asyncio.sleep(0.4)
    raise RuntimeError(
        "Image attachment did not become ready; no message was sent. Inspect the existing composer before retrying."
    )

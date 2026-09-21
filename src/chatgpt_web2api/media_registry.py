"""Opaque local image references shared by Continue MCP tools and Web2API."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import time
import uuid
from pathlib import Path

from PIL import Image

ROOT = Path(
    os.environ.get(
        "W2A_MEDIA_DIR",
        str(Path(os.environ.get("CONTINUE_GLOBAL_DIR", str(Path.home() / ".continue"))) / "media"),
    )
)
PATTERN = re.compile(r"\[\[continue-image:([0-9a-f]{32})\]\]")
MAX_BYTES = 12 * 1024 * 1024


def publish(data: bytes, origin: str = "tool") -> dict:
    if len(data) > MAX_BYTES:
        raise ValueError("Image exceeds 12 MB")
    with Image.open(io.BytesIO(data)) as im:
        width, height = im.size
        if width * height > 25000000:
            raise ValueError("Image exceeds 25 megapixels")
        fmt = im.format
        im.verify()
    extension = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp", "GIF": "gif"}.get(fmt)
    if extension is None:
        raise ValueError("Only PNG, JPEG, WEBP and GIF images are supported")
    ROOT.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    index = ROOT / (digest + ".index")
    if index.exists():
        try:
            prior = index.read_text(encoding="ascii").strip()
            prior_path = resolve(prior)
            return dict(
                image_reference=f"[[continue-image:{prior}]]",
                image_file=str(prior_path),
                width=width,
                height=height,
                delivery="Web2API must attach this registered image to the next model request; this text is not the image itself.",
            )
        except (ValueError, OSError, KeyError, json.JSONDecodeError):
            pass
    token = uuid.uuid4().hex
    # Use the same canonical path on first publication and cache reuse.
    # Windows can expose TEMP under both an 8.3 alias and its long name.
    path = (ROOT / (token + "." + extension)).resolve()
    path.write_bytes(data)
    meta = dict(
        file=path.name,
        sha256=digest,
        created=time.time(),
        width=width,
        height=height,
        origin=origin,
    )
    (ROOT / (token + ".json")).write_text(json.dumps(meta), encoding="utf-8")
    index.write_text(token, encoding="ascii")
    return dict(
        image_reference=f"[[continue-image:{token}]]",
        image_file=str(path),
        width=width,
        height=height,
        delivery="Web2API must attach this registered image to the next model request; this text is not the image itself.",
    )


def resolve(token: str) -> Path:
    if not re.fullmatch("[0-9a-f]{32}", token):
        raise ValueError("Invalid image reference")
    meta = json.loads((ROOT / (token + ".json")).read_text(encoding="utf-8"))
    if time.time() - meta["created"] > 86400:
        raise ValueError("Image reference expired; capture/read the image again")
    path = (ROOT / meta["file"]).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError("Image path escapes registry")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Registered image exceeds limit")
    if hashlib.sha256(path.read_bytes()).hexdigest() != meta["sha256"]:
        raise ValueError("Image changed since publication")
    return path


def data_url(url: str) -> dict:
    match = re.fullmatch(r"data:image/(png|jpeg|webp|gif);base64,([A-Za-z0-9+/=\r\n]+)", url)
    if not match:
        raise ValueError("Only inline PNG/JPEG/WEBP/GIF image data URLs are supported")
    if len(match[2]) > MAX_BYTES * 4 // 3 + 1024:
        raise ValueError("Encoded image exceeds limit")
    return publish(base64.b64decode(match[2], validate=True), origin="user-image")


def collect_tool_images(messages: list[dict]) -> list[Path]:
    """Only registered references from matched tool results, never source text."""
    calls = {}
    images = []
    for message in messages:
        for call in message.get("tool_calls") or []:
            calls[call.get("id")] = (call.get("function") or {}).get("name", "")
        if message.get("role") != "tool":
            continue
        name = calls.get(message.get("tool_call_id"), "")
        if not (
            name.startswith(("computer_", "browser_"))
            or name in ("local_view_image", "vision_view_image")
        ):
            continue
        content = message.get("content") or ""
        if not isinstance(content, str):
            continue
        for token in PATTERN.findall(content):
            path = resolve(token)
            if path not in images:
                images.append(path)
    if len(images) > 4:
        raise ValueError("At most four new images can be attached per request")
    return images

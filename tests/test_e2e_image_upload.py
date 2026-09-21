"""Opt-in: three actual uploads of the SAME file in an isolated owned chat."""

import asyncio
import json
import uuid

import pytest
from PIL import Image

from chatgpt_web2api.cdp_driver import CDPDriver
from chatgpt_web2api.composer_transport import settle_completed_turn
from chatgpt_web2api.lock_resolver import MutationLock
from chatgpt_web2api.tool_bridge import ToolBridge
from chatgpt_web2api.vision_bridge import COMPOSER_STATE_JS


@pytest.mark.e2e
async def test_repeated_identical_images_after_submitted_picker_selection(tmp_path):
    picture = tmp_path / "fixture.png"
    Image.new("RGB", (200, 120), "blue").save(picture)
    driver = CDPDriver(instance_id="vision-regression-" + uuid.uuid4().hex)
    try:
        await driver.connect()
        async with MutationLock(9222, None):
            for index in range(3):
                if index:
                    await asyncio.sleep(20)
                    frame = getattr(driver, "_agent_completed_frame", None)
                    if frame:
                        await settle_completed_turn(driver, frame)
                    state = json.loads(
                        await driver._js_strict(f"JSON.stringify(({COMPOSER_STATE_JS}).state)")
                    )
                    print("Before image", index + 1, ":", json.dumps(state), flush=True)
                    assert state["images"] == 0 and not state["generating"]
                    # React may remount the input when the first send creates
                    # the chat URL. Later turns can keep its stale FileList.
                    # Both browser behaviors must accept the next image.
                bridge = ToolBridge([], choice="none")
                prompt = bridge.prompt(
                    [
                        {
                            "role": "user",
                            "content": "Inspect the actual attached image. Answer in English with only its dominant color.",
                        }
                    ]
                )
                parts = []
                async for chunk in driver.send_and_stream(
                    prompt,
                    image_paths=[str(picture)],
                    response_validator=bridge.validated_frame,
                    response_marker=bridge.opening,
                ):
                    parts.append(chunk.delta)
                message = bridge.parse("".join(parts))
                print("Image", index + 1, "answer:", message["content"], flush=True)
                assert "blue" in message["content"].lower()
    finally:
        await driver.close()

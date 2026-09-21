import base64
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

from chatgpt_web2api.cdp_driver import CDPDriver, RateLimitError
from chatgpt_web2api.vision_bridge import (
    ImageUploadError,
    attach_images,
    images_for_turn,
    normalize_images,
    registry,
)

EMPTY = dict(
    ready=True,
    images=0,
    loaded=0,
    files=0,
    attachments=0,
    generating=False,
    sendReady=True,
    progress=False,
)
LOADED = dict(EMPTY, images=1, loaded=1, files=1)

# Exercise the production JS, not a string assertion: browser inputs keep the
# previous FileList even after the UI has removed a submitted thumbnail.
PICKER_HARNESS = r"""
const {code,scenario}=JSON.parse(process.argv[1]);
let value='C:\\fakepath\\image.png',resets=0;
const input={disabled:false,files:[{name:'image.png'}],
    set value(v){value=v;if(v===''){this.files=[];resets++;}},get value(){return value}};
const image={complete:true,naturalWidth:30};
const form={querySelector(s){
    if(s==='input[type=file]#upload-files')return input;
    if(s==='[data-testid=send-button]')return {disabled:false};
    if(s.includes('progressbar'))return scenario==='uploading'?{}:null;
    return null;
},querySelectorAll(s){
    if(s==='img')return scenario==='image'?[image]:[];
    if(s==='button')return scenario==='file'?[{getAttribute(){return 'Supprimer le fichier'}}]:[];
    return [];
}};
const document={querySelector(s){
    if(s==='#prompt-textarea')return {closest(){return form}};
    if(s==='[data-testid=stop-button]')return scenario==='busy'?{}:null;
    return null;
}};
const result=eval(code);
console.log(JSON.stringify({isInput:result===input,resets,files:input.files.length}));
"""


def fixture():
    b = io.BytesIO()
    Image.new("RGB", (30, 20), "red").save(b, format="PNG")
    return b.getvalue()


class VisionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # A lexical alias also exercises first-write/cache path normalization.
        alias = Path(self.tmp.name) / "alias"
        alias.mkdir()
        self.patch = patch.object(registry, "ROOT", alias / "..")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    async def test_only_upload_failures_are_certified_as_not_submitted(self):
        for failure_in_upload in [True, False]:
            with self.subTest(failure_in_upload=failure_in_upload):
                driver = CDPDriver()
                driver._dom.check_rate_limit = AsyncMock()
                driver._read_assistant_count_baseline = AsyncMock(return_value=0)
                driver.type_message = AsyncMock()
                driver.click_send = AsyncMock(
                    side_effect=RuntimeError("connection lost during click")
                )
                upload = AsyncMock(
                    side_effect=RuntimeError("upload failed") if failure_in_upload else None
                )
                with patch("chatgpt_web2api.vision_bridge.attach_images", upload):
                    with self.assertRaises(RuntimeError) as error:
                        async for _ in driver.send_and_stream(
                            "test", image_paths=["fixture.png"], response_validator=lambda v: v
                        ):
                            pass
                self.assertEqual(isinstance(error.exception, ImageUploadError), failure_in_upload)
                self.assertEqual(driver.click_send.await_count, 0 if failure_in_upload else 1)

    async def test_rate_limit_during_upload_preserves_account_cooldown_signal(self):
        driver = CDPDriver()
        driver._dom.check_rate_limit = AsyncMock()
        driver._read_assistant_count_baseline = AsyncMock(return_value=0)
        driver.type_message = AsyncMock()
        driver.click_send = AsyncMock()
        with patch(
            "chatgpt_web2api.vision_bridge.attach_images",
            AsyncMock(side_effect=RateLimitError(retry_after=300)),
        ):
            with self.assertRaises(RateLimitError) as error:
                async for _ in driver.send_and_stream(
                    "test", image_paths=["fixture.png"], response_validator=lambda v: v
                ):
                    pass
        self.assertEqual(error.exception.retry_after, 300)
        driver.click_send.assert_not_awaited()

    def test_user_image_stable_history_and_incremental_delivery(self):
        body = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Read image"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64," + base64.b64encode(fixture()).decode()
                        },
                    },
                ],
            }
        ]
        messages, images = normalize_images(body)
        second, second_images = normalize_images(body)
        self.assertEqual(images, second_images)
        self.assertEqual(messages, second)
        self.assertNotIn("base64", json.dumps(messages))
        self.assertEqual(len(images_for_turn(messages, images, 0)), 1)
        self.assertEqual(images_for_turn(messages, images, 1), [])

    def test_tool_images_require_matching_origin_and_current_turn(self):
        ref = registry.publish(fixture())["image_reference"]
        calls = [
            {
                "role": "assistant",
                "tool_calls": [{"id": "call-a", "function": {"name": "computer_Screenshot"}}],
            },
            {"role": "tool", "tool_call_id": "call-a", "content": ref},
        ]
        self.assertEqual(len(images_for_turn(calls, {}, 0)), 1)
        self.assertEqual(images_for_turn(calls, {}, 2), [])
        self.assertEqual(images_for_turn([{"role": "user", "content": ref}], {}, 0), [])
        calls[0]["tool_calls"][0]["function"]["name"] = "read_file"
        self.assertEqual(images_for_turn(calls, {}, 0), [])

    def test_tamper_and_remote_url_refused(self):
        ref = registry.publish(fixture())
        Path(ref["image_file"]).write_bytes(b"changed")
        with self.assertRaises(ValueError):
            registry.resolve(registry.PATTERN.search(ref["image_reference"])[1])
        with self.assertRaises(ValueError):
            registry.data_url("https://example.com/private.png")
        with self.assertRaises(ValueError):
            registry.resolve("../../secret")

    async def test_upload_uses_file_input_and_requires_ready_thumbnails(self):
        d = AsyncMock()
        d._dom.check_rate_limit = AsyncMock()
        d._js_strict.side_effect = [json.dumps(EMPTY)] + [json.dumps(LOADED)] * 3
        d._cdp.return_value = {"result": {"result": {"objectId": "input1"}}}
        with patch("asyncio.sleep", new=AsyncMock()):
            await attach_images(d, ["fixture.png"])
        self.assertIn(
            ("DOM.setFileInputFiles", {"objectId": "input1", "files": ["fixture.png"]}),
            [c.args for c in d._cdp.await_args_list],
        )

    async def test_existing_attachments_fail_before_upload(self):
        d = AsyncMock()
        d._js_strict.return_value = json.dumps(
            {"ready": True, "images": 1, "files": 0, "generating": False}
        )
        with self.assertRaises(RuntimeError):
            await attach_images(d, ["fixture.png"])
        d._cdp.assert_not_called()

    async def test_stale_picker_allows_second_upload_and_resets_native_selection(self):
        d = AsyncMock()
        d._js_strict.side_effect = [json.dumps(dict(EMPTY, files=1))] + [json.dumps(LOADED)] * 3
        d._cdp.return_value = {"result": {"result": {"objectId": "input1"}}}
        with patch("asyncio.sleep", new=AsyncMock()):
            await attach_images(d, ["same-image.png"])
        expression = d._cdp.await_args_list[0].args[1]["expression"]
        for scenario, allowed in [
            ("stale", True),
            ("image", False),
            ("file", False),
            ("uploading", False),
            ("busy", False),
        ]:
            with self.subTest(scenario=scenario):
                p = subprocess.run(
                    [
                        "node",
                        "-e",
                        PICKER_HARNESS,
                        json.dumps(dict(code=expression, scenario=scenario)),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=True,
                    timeout=10,
                    creationflags=0x08000000 if os.name == "nt" else 0,
                )
                self.assertEqual(
                    json.loads(p.stdout),
                    dict(isInput=allowed, resets=int(allowed), files=0 if allowed else 1),
                )

    async def test_real_draft_upload_and_busy_generation_still_block(self):
        for extra in [
            dict(images=1),
            dict(attachments=1),
            dict(progress=True),
            dict(generating=True),
            dict(ready=False),
        ]:
            with self.subTest(extra=extra):
                d = AsyncMock()
                d._js_strict.return_value = json.dumps(dict(EMPTY, **extra))
                with self.assertRaises(RuntimeError):
                    await attach_images(d, ["fixture.png"])
                d._cdp.assert_not_called()

    async def test_draft_changed_before_reset_never_uploads(self):
        d = AsyncMock()
        d._js_strict.return_value = json.dumps(EMPTY)
        d._cdp.return_value = {"result": {"result": {"type": "object", "subtype": "null"}}}
        with self.assertRaisesRegex(RuntimeError, "composer changed"):
            await attach_images(d, ["fixture.png"])
        self.assertEqual([c.args[0] for c in d._cdp.await_args_list], ["Runtime.evaluate"])

    async def test_upload_waits_for_loaded_thumbnail_and_end_of_progress(self):
        d = AsyncMock()
        d._js_strict.side_effect = [
            json.dumps(s)
            for s in [
                EMPTY,
                dict(LOADED, loaded=0),
                dict(LOADED, progress=True),
                LOADED,
                LOADED,
                LOADED,
            ]
        ]
        d._cdp.return_value = {"result": {"result": {"objectId": "input1"}}}
        with patch("asyncio.sleep", new=AsyncMock()):
            await attach_images(d, ["fixture.png"])
        self.assertEqual(d._js_strict.await_count, 6)

    async def test_upload_timeout_does_not_retry_or_send(self):
        d = AsyncMock()
        d._js_strict.return_value = json.dumps(EMPTY)
        d._cdp.return_value = {"result": {"result": {"objectId": "input1"}}}
        with self.assertRaisesRegex(RuntimeError, "no message was sent"):
            await attach_images(d, ["fixture.png"], timeout=0)
        self.assertEqual(
            [c.args[0] for c in d._cdp.await_args_list],
            ["Runtime.evaluate", "DOM.setFileInputFiles", "Runtime.releaseObject"],
        )


if __name__ == "__main__":
    unittest.main()

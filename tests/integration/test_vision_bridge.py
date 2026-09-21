import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

from chatgpt_web2api.vision_bridge import attach_images, images_for_turn, normalize_images, registry


def fixture():
    b = io.BytesIO()
    Image.new("RGB", (30, 20), "red").save(b, format="PNG")
    return b.getvalue()


class VisionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(registry, "ROOT", Path(self.tmp.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

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
        d._js_strict.side_effect = [
            json.dumps({"ready": True, "images": 0, "files": 0, "generating": False})
        ] + [json.dumps({"images": 1, "sendReady": True, "progress": False, "alerts": ""})] * 3
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


if __name__ == "__main__":
    unittest.main()

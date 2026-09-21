import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from chatgpt_web2api.backend_client import BackendClient
from chatgpt_web2api.identity_listener import hash_sent_text
from chatgpt_web2api.turn_anchor import user_text_matches_sent


class ComposerNormalizationTests(unittest.TestCase):
    def test_continue_indentation_matches_browser_serialization(self):
        sent = "[System Instructions]\n<important_rules>\n  You are in chat mode.\n\n  Preserve the code.\n</important_rules>\n\n[User]\nRéponds BONJOUR921"
        submitted = sent.replace("\n  ", "\n\u00a0 ")
        self.assertEqual(hash_sent_text(sent), hash_sent_text(submitted))
        self.assertTrue(user_text_matches_sent(submitted, sent))

    def test_different_request_is_not_accepted(self):
        sent = "[User]\n  Read file A"
        submitted = "[User]\n\u00a0 Read file B"
        self.assertNotEqual(hash_sent_text(sent), hash_sent_text(submitted))
        self.assertFalse(user_text_matches_sent(submitted, sent))

    def test_indentation_count_remains_significant(self):
        self.assertNotEqual(hash_sent_text("  code"), hash_sent_text("\u00a0code"))
        self.assertFalse(user_text_matches_sent("x\n\u00a0code", "x\n  code"))


class ConversationURLTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_web_url_is_retried(self):
        driver = SimpleNamespace(
            _js_strict=AsyncMock(
                return_value="https://chatgpt.com/c/WEB:12345678-1234-1234-1234-123456789012"
            )
        )
        self.assertEqual(await BackendClient(driver)._conversation_id_from_url(), "")

    async def test_encoded_transient_web_url_is_retried(self):
        driver = SimpleNamespace(
            _js_strict=AsyncMock(
                return_value="https://chatgpt.com/c/WEB%3A12345678-1234-1234-1234-123456789012"
            )
        )
        self.assertEqual(await BackendClient(driver)._conversation_id_from_url(), "")

    async def test_persisted_conversation_url_is_retained(self):
        driver = SimpleNamespace(
            _js_strict=AsyncMock(
                return_value="https://chatgpt.com/c/12345678-1234-1234-1234-123456789012?model=auto"
            )
        )
        self.assertEqual(
            await BackendClient(driver)._conversation_id_from_url(),
            "12345678-1234-1234-1234-123456789012",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from chatgpt_web2api.cdp_driver import RateLimitError
from chatgpt_web2api.chatgpt_dom import ChatGPTDom
from chatgpt_web2api.completion_detector import is_rate_limited_text

NOTICE = "Trop de requêtes. Vous envoyez des demandes trop rapidement. Nous avons temporairement restreint l’accès à vos conversations pour protéger vos données. Veuillez attendre quelques minutes avant de réessayer. J’ai compris"


class FrenchRateLimitTests(unittest.IsolatedAsyncioTestCase):
    def test_observed_french_popup_is_recognized(self):
        self.assertTrue(is_rate_limited_text(NOTICE))
        self.assertTrue(is_rate_limited_text("Too many requests"))
        self.assertFalse(is_rate_limited_text("Analyse le moteur de paiement et ses limites."))

    async def test_blocking_popup_raises_rate_limit_before_send(self):
        driver = SimpleNamespace(_js_strict=AsyncMock(return_value=NOTICE))
        with self.assertRaises(RateLimitError) as caught:
            await ChatGPTDom(driver).check_rate_limit()
        self.assertGreater(caught.exception.retry_after, 0)
        self.assertIn("[role=dialog]", driver._js_strict.call_args.args[0])

    async def test_absent_popup_allows_send(self):
        await ChatGPTDom(SimpleNamespace(_js_strict=AsyncMock(return_value=""))).check_rate_limit()

    async def test_dismissal_is_verified(self):
        for remaining, expected in [("", True), (NOTICE, False)]:
            driver = SimpleNamespace(
                _js_strict=AsyncMock(
                    side_effect=['{"clicked":true}', __import__("json").dumps({"text": remaining})]
                )
            )
            self.assertEqual(await ChatGPTDom(driver).dismiss_rate_limit(), expected)
            script = driver._js_strict.call_args_list[0].args[0]
            self.assertIn("trop de requêtes", script)
            self.assertIn("ai compris", script)


if __name__ == "__main__":
    unittest.main()

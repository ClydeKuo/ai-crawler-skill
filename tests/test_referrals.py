import unittest

from tests import FIXTURES  # noqa: F401
from ai_crawler_log.bots import BotRegistry
from ai_crawler_log.referrals import ReferralDetector


class ReferralTest(unittest.TestCase):
    def setUp(self):
        self.d = ReferralDetector(BotRegistry.load().referrals)

    def test_referer_hosts(self):
        self.assertEqual(self.d.detect("https://chatgpt.com/", "/x").source, "ChatGPT")
        self.assertEqual(self.d.detect("https://www.perplexity.ai/search?q=a", "/x").source, "Perplexity")
        self.assertEqual(self.d.detect("https://gemini.google.com/app", "/x").source, "Gemini")
        self.assertEqual(self.d.detect("https://claude.ai/chat/abc", "/x").operator, "Anthropic")

    def test_utm_source(self):
        self.assertEqual(self.d.detect("-", "/post/?utm_source=chatgpt.com").source, "ChatGPT")
        self.assertEqual(self.d.detect("", "/post/?foo=1&utm_source=perplexity").source, "Perplexity")

    def test_non_ai(self):
        self.assertIsNone(self.d.detect("https://www.google.com/", "/x"))
        self.assertIsNone(self.d.detect("-", "/x?utm_source=newsletter"))
        self.assertIsNone(self.d.detect("https://notchatgpt.com/", "/x"))


if __name__ == "__main__":
    unittest.main()

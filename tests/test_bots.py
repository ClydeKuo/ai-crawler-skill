import unittest

from tests import FIXTURES  # noqa: F401  (sets sys.path)
from ai_crawler_log.bots import BotRegistry


class BotMatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = BotRegistry.load()

    def m(self, ua):
        bot = self.reg.match(ua)
        return bot.name if bot else None

    def test_real_world_user_agents(self):
        cases = {
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)": "GPTBot",
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot": "ChatGPT-User",
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot": "OAI-SearchBot",
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)": "ClaudeBot",
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; +Claude-User@anthropic.com)": "Claude-User",
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)": "PerplexityBot",
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user)": "Perplexity-User",
            "Mozilla/5.0 (Linux; Android 5.0) AppleWebKit/537.36 (KHTML, like Gecko) Mobile Safari/537.36 (compatible; Bytespider; spider-feedback@bytedance.com)": "Bytespider",
            "CCBot/2.0 (https://commoncrawl.org/faq/)": "CCBot",
            "meta-externalagent/1.1 (+https://developers.facebook.com/docs/sharing/webmasters/crawler)": "meta-externalagent",
            "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)": "Googlebot",
            "Googlebot-Image/1.0": "Googlebot",
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm) Chrome/116.0.1938.76 Safari/537.36": "Bingbot",
        }
        for ua, expected in cases.items():
            with self.subTest(ua=ua):
                self.assertEqual(self.m(ua), expected)

    def test_humans_and_lookalikes_do_not_match(self):
        for ua in [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
            "facebookexternalhit/1.1",
            "",
            "-",
        ]:
            with self.subTest(ua=ua):
                self.assertIsNone(self.m(ua))

    def test_policy_tokens_are_not_crawlers(self):
        self.assertIsNone(self.m("Google-Extended"))
        self.assertIn("Google-Extended", [p["token"] for p in self.reg.policy_tokens])

    def test_categories(self):
        self.assertEqual(self.reg.get("ChatGPT-User").category, "user")
        self.assertEqual(self.reg.get("OAI-SearchBot").category, "search")
        self.assertEqual(self.reg.get("GPTBot").category, "training")
        self.assertEqual(self.reg.get("Googlebot").category, "classic-search")

    def test_operator_cleanup(self):
        clean = BotRegistry.clean_operator
        self.assertEqual(clean("[ElevenLabs](https://elevenlabs.io)"), "ElevenLabs")
        self.assertEqual(clean("Unclear at this time."), "")
        self.assertEqual(clean("Naget Inc (founded by Chris, headquarter in Amherst)"), "Naget Inc")
        self.assertEqual(clean("Querit that indexes web content for their search API service, which is long"), "Querit")
        self.assertLessEqual(len(clean("x" * 100)), 40)

    def test_extra_bots_from_ai_robots_txt(self):
        raw = {
            "NewShinyBot": {"operator": "Shiny", "function": "AI Search Crawlers"},
            "Spider": {"operator": "?", "function": "AI Data Scrapers"},
            "GPTBot": {"operator": "OpenAI", "function": "AI Data Scrapers"},
            "Foo-Extended": {"operator": "Foo", "function": "AI Data Scrapers"},
            "__usage_ai-training": {"operator": "n/a", "function": "AI Data Scrapers"},
        }
        extra = BotRegistry.convert_ai_robots_txt(raw, existing=self.reg)
        names = [b["name"] for b in extra["bots"]]
        self.assertEqual(names, ["NewShinyBot"])
        self.assertEqual(extra["bots"][0]["category"], "search")
        self.assertEqual([p["token"] for p in extra["policy_tokens"]], ["Foo-Extended"])
        reg2 = BotRegistry.load(extra=extra)
        self.assertEqual(reg2.match("Mozilla/5.0 (compatible; NewShinyBot/0.1)").name, "NewShinyBot")


if __name__ == "__main__":
    unittest.main()

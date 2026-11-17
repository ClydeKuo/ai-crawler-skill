import os
import tempfile
import unittest

from tests import FIXTURES  # noqa: F401
from ai_crawler_log.analyze import AnalyzeOptions, LogSource, analyze
from ai_crawler_log.bots import BotRegistry
from ai_crawler_log.parsers import ProxyResolver
from ai_crawler_log.sitefiles import Robots, SiteInfo

L = '{ip} - - [{d}/Nov/2026:{t} +0000] "GET {path} HTTP/1.1" {st} 100 "{ref}" "{ua}"{extra}'
GPT = "Mozilla/5.0 (compatible; GPTBot/1.2; +https://openai.com/gptbot)"
CGU = "Mozilla/5.0 (compatible; ChatGPT-User/1.0; +https://openai.com/bot)"
CLAUDE = "Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)"
PPLX = "Mozilla/5.0 (compatible; PerplexityBot/1.0)"
GOOG = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
HUMAN = "Mozilla/5.0 (Windows NT 10.0) Chrome/130"


def line(ip, d, path, ua, st=200, ref="-", t="10:00:00", extra=""):
    return L.format(ip=ip, d=d, t=t, path=path, st=st, ref=ref, ua=ua, extra=extra)


LINES = [
    line("20.171.207.1", 10, "/hello-world/", GPT),
    line("20.171.207.1", 10, "/robots.txt", GPT),
    line("20.171.207.1", 11, "/llms.txt", GPT),
    line("20.171.207.2", 11, "/about/", GPT),
    line("6.6.6.6", 11, "/hello-world/", GPT),            # spoofed
    line("23.98.142.1", 12, "/hello-world/?x=1", CGU),
    line("172.70.1.2", 12, "/about/", CLAUDE, extra=' "216.73.216.10"'),
    line("172.70.1.3", 12, "/hello-world/", CLAUDE),       # CF without XFF
    line("18.97.1.228", 12, "/hello-world/", PPLX, st=403),
    line("66.249.66.1", 12, "/second/", GOOG),
    line("9.9.9.9", 12, "/hello-world/?utm_source=chatgpt.com", HUMAN),
    line("9.9.9.8", 12, "/about/", HUMAN, ref="https://www.perplexity.ai/search"),
    line("9.9.9.7", 12, "/about/", HUMAN, ref="https://www.google.com/"),
    "garbage line",
]

STATES = {("GPTBot", "6.6.6.6"): "spoofed", ("ChatGPT-User", "23.98.142.1"): "verified", ("ClaudeBot", "172.70.1.3"): "unknown"}


class FakeVerifier:
    range_status = {}
    offline = False

    def verify_many(self, items):
        return {(b.name, ip): STATES.get((b.name, ip), "verified") for b, ip, via in items}


class FakeSiteFiles:
    def collect(self, site, sitemap=None, robots=None):
        info = SiteInfo(site=site)
        info.robots = Robots("User-agent: GPTBot\nDisallow: /about/\n")
        info.robots_found = True
        info.sitemap_paths = {"/hello-world", "/about", "/second", "/never"}
        info.llms = {"llms.txt": True, "llms-full.txt": False}
        return info


class AnalyzeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(cls.tmp.name, "access.log")
        with open(path, "w") as f:
            f.write("\n".join(LINES) + "\n")
        opts = AnalyzeOptions(proxy=ProxyResolver.default())
        cls.res = analyze([LogSource(path, site="example.com")], BotRegistry.load(), FakeVerifier(), FakeSiteFiles(), opts)
        cls.s = cls.res["sites"]["example.com"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_lines(self):
        self.assertEqual(self.s["lines"], {"total": 14, "parsed": 13, "unparsed": 1})
        self.assertEqual(self.s["period"]["start"], "2026-11-10")
        self.assertEqual(self.s["period"]["end"], "2026-11-12")

    def test_bot_counts_exclude_spoofed(self):
        b = self.s["bots"]["GPTBot"]
        self.assertEqual(b["requests"], 4)
        self.assertEqual(b["verification"]["spoofed"], 1)
        self.assertEqual(b["robots_txt_fetches"], 1)
        self.assertEqual(b["llms_txt_fetches"], 1)
        self.assertEqual(self.s["spoofed"]["total"], 1)
        self.assertEqual(self.s["spoofed"]["top_ips"][0]["ip"], "6.6.6.6")

    def test_categories_and_daily(self):
        c = self.s["categories"]
        self.assertEqual(c["user"]["requests"], 1)
        self.assertEqual(c["training"]["requests"], 6)  # 4 GPTBot + 2 ClaudeBot
        self.assertEqual(c["search"]["requests"], 1)
        self.assertEqual(c["classic-search"]["requests"], 1)
        self.assertEqual(self.s["daily"]["2026-11-12"]["user"], 1)
        self.assertEqual(self.s["ai_requests"], 8)

    def test_status_blocked(self):
        self.assertEqual(self.s["bots"]["PerplexityBot"]["status"]["403"], 1)
        self.assertEqual(self.s["blocked"]["requests"], 1)

    def test_proxy_warning(self):
        self.assertEqual(self.s["proxy"]["behind_proxy"], 2)
        self.assertEqual(self.s["proxy"]["unresolved"], 1)
        w = [w for w in self.res["warnings"] if w["code"] == "proxy_unresolved"][0]
        self.assertTrue(w["spoofed_unreliable"])

    def test_pages_and_coverage(self):
        top_user = self.s["top_pages"]["user"]
        self.assertEqual(top_user[0]["path"], "/hello-world")
        cov = self.s["coverage"]
        self.assertEqual(cov["sitemap_total"], 4)
        self.assertEqual(sorted(cov["never_crawled"]), ["/never", "/second"])  # 403 doesn't count, Googlebot isn't AI
        self.assertEqual(cov["by_category"]["classic-search"], 1)

    def test_referrals(self):
        r = self.s["referrals"]
        self.assertEqual(r["total"], 2)
        self.assertEqual(r["by_source"]["ChatGPT"]["visits"], 1)
        self.assertEqual(r["by_source"]["Perplexity"]["visits"], 1)
        self.assertEqual(r["human_pageviews"], 3)
        openai = [x for x in self.s["operators"] if x["operator"] == "OpenAI"][0]
        self.assertEqual(openai["crawls"], 5)
        self.assertEqual(openai["referrals"], 1)

    def test_robots(self):
        rb = self.s["robots"]
        gpt = [t for t in rb["tokens"] if t["token"] == "GPTBot"][0]
        self.assertTrue(gpt["explicit"])
        self.assertTrue(gpt["allowed_root"])
        self.assertEqual(gpt["violations"], 1)
        self.assertIn("Google-Extended", [t["token"] for t in rb["policy_tokens"]])
        self.assertEqual(self.s["llms"]["exists"]["llms.txt"], True)

    def test_no_human_ips_in_output(self):
        import json
        dumped = json.dumps(self.res)
        for ip in ("9.9.9.9", "9.9.9.8", "9.9.9.7"):
            self.assertNotIn(ip, dumped)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest

from tests import FIXTURES  # noqa: F401
from ai_crawler_log.bots import Bot
from ai_crawler_log.verify import Verifier, extract_prefixes

RANGES = {"https://x/gptbot.json": {"creationTime": "t", "prefixes": [{"ipv4Prefix": "20.171.207.0/24"}, {"ipv6Prefix": "2600:1f28::/32"}]}}
GPTBOT = Bot(name="GPTBot", operator="OpenAI", category="training", ua=["GPTBot"], ip_ranges=["https://x/gptbot.json"])
GOOGLEBOT = Bot(name="Googlebot", operator="Google", category="classic-search", ua=["Googlebot"], rdns=["googlebot.com", "google.com"])
BYTESPIDER = Bot(name="Bytespider", operator="ByteDance", category="training", ua=["Bytespider"])

PTR = {"66.249.66.1": "crawl-66-249-66-1.googlebot.com", "6.6.6.6": "evil.example.net", "7.7.7.7": "fake.googlebot.com.evil.net",
       "8.8.8.1": "crawl-x.googlebot.com"}
FWD = {"crawl-66-249-66-1.googlebot.com": ["66.249.66.1"], "crawl-x.googlebot.com": ["1.1.1.1"]}


def fake_fetch(url):
    if url in RANGES:
        return json.dumps(RANGES[url]).encode()
    raise OSError("network down")


class VerifyTest(unittest.TestCase):
    def make(self, **kw):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        kw.setdefault("fetch", fake_fetch)
        kw.setdefault("reverse", lambda ip: PTR.get(ip))
        kw.setdefault("forward", lambda host: FWD.get(host, []))
        return Verifier(cache_dir=self.tmp.name, **kw)

    def test_extract_prefixes(self):
        self.assertEqual(extract_prefixes(RANGES["https://x/gptbot.json"]), ["20.171.207.0/24", "2600:1f28::/32"])

    def test_ip_ranges(self):
        v = self.make()
        res = v.verify_many([(GPTBOT, "20.171.207.5", False), (GPTBOT, "5.5.5.5", False), (GPTBOT, "2600:1f28::1", False)])
        self.assertEqual(res[("GPTBot", "20.171.207.5")], "verified")
        self.assertEqual(res[("GPTBot", "5.5.5.5")], "spoofed")
        self.assertEqual(res[("GPTBot", "2600:1f28::1")], "verified")

    def test_fcrdns(self):
        v = self.make()
        res = v.verify_many([(GOOGLEBOT, ip, False) for ip in ["66.249.66.1", "6.6.6.6", "7.7.7.7", "8.8.8.1", "9.9.9.9"]])
        self.assertEqual(res[("Googlebot", "66.249.66.1")], "verified")
        self.assertEqual(res[("Googlebot", "6.6.6.6")], "spoofed")
        self.assertEqual(res[("Googlebot", "7.7.7.7")], "spoofed")   # suffix trick
        self.assertEqual(res[("Googlebot", "8.8.8.1")], "spoofed")   # forward lookup mismatch
        self.assertEqual(res[("Googlebot", "9.9.9.9")], "spoofed")   # no PTR

    def test_unverifiable_and_proxy(self):
        v = self.make()
        res = v.verify_many([(BYTESPIDER, "1.2.3.4", False), (GPTBOT, "172.70.1.2", True)])
        self.assertEqual(res[("Bytespider", "1.2.3.4")], "unverifiable")
        self.assertEqual(res[("GPTBot", "172.70.1.2")], "unknown")

    def test_offline_without_cache_is_unknown(self):
        v = self.make(offline=True)
        res = v.verify_many([(GPTBOT, "20.171.207.5", False), (GOOGLEBOT, "66.249.66.1", False)])
        self.assertEqual(res[("GPTBot", "20.171.207.5")], "unknown")
        self.assertEqual(res[("Googlebot", "66.249.66.1")], "unknown")

    def test_cache_survives_offline(self):
        v = self.make()
        v.verify_many([(GPTBOT, "20.171.207.5", False)])
        v2 = Verifier(cache_dir=self.tmp.name, offline=True, fetch=fake_fetch)
        self.assertEqual(v2.verify_many([(GPTBOT, "20.171.207.5", False)])[("GPTBot", "20.171.207.5")], "verified")

    def test_fetch_failure_is_unknown(self):
        bot = Bot(name="X", operator="", category="training", ua=["X"], ip_ranges=["https://down/x.json"])
        v = self.make()
        self.assertEqual(v.verify_many([(bot, "1.1.1.1", False)])[("X", "1.1.1.1")], "unknown")


if __name__ == "__main__":
    unittest.main()

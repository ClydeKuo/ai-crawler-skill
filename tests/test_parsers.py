import gzip
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from tests import FIXTURES  # noqa: F401
from ai_crawler_log.parsers import LogParser, open_log, ProxyResolver

COMBINED = '203.0.113.9 - - [10/Nov/2026:13:55:36 +0800] "GET /blog/hello/?utm_source=chatgpt.com HTTP/1.1" 200 5123 "https://chatgpt.com/" "Mozilla/5.0 (Windows NT 10.0) Chrome/130"'
ESCAPED = '20.171.207.1 - - [10/Nov/2026:13:55:37 +0000] "GET /a HTTP/1.1" 403 0 "-" "Mozilla/5.0 \\"quoted\\" GPTBot/1.2"'
VHOST = 'www.example.com:443 66.249.66.1 - - [10/Nov/2026:00:00:01 +0000] "GET / HTTP/1.1" 200 10 "-" "Googlebot/2.1"'
CF_XFF = '172.70.1.2 - - [11/Nov/2026:01:02:03 +0000] "GET /p HTTP/2.0" 200 99 "-" "ClaudeBot/1.0" "216.73.216.10"'
CF_NO_XFF = '172.70.1.2 - - [11/Nov/2026:01:02:03 +0000] "GET /p HTTP/2.0" 200 99 "-" "ClaudeBot/1.0"'
JSONLINE = json.dumps({"time_iso8601": "2026-11-12T08:00:00+00:00", "remote_addr": "1.2.3.4", "request": "GET /j?x=1 HTTP/1.1",
                       "status": "200", "body_bytes_sent": "5", "http_referer": "", "http_user_agent": "PerplexityBot/1.0", "host": "Example.com"})
CF_LOGPUSH = json.dumps({"ClientIP": "18.97.1.228", "ClientRequestHost": "example.com", "ClientRequestMethod": "GET",
                         "ClientRequestURI": "/cf/page?a=1", "EdgeResponseStatus": 200, "EdgeResponseBytes": 1234,
                         "ClientRequestReferer": "", "ClientRequestUserAgent": "PerplexityBot/1.0", "EdgeStartTimestamp": 1794470400000000000})


class ParserTest(unittest.TestCase):
    def setUp(self):
        self.p = LogParser()

    def test_combined(self):
        r = self.p.parse_line(COMBINED)
        self.assertEqual(r.ip, "203.0.113.9")
        self.assertEqual(r.method, "GET")
        self.assertEqual(r.target, "/blog/hello/?utm_source=chatgpt.com")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.bytes, 5123)
        self.assertEqual(r.referer, "https://chatgpt.com/")
        self.assertEqual(r.ts, datetime(2026, 11, 10, 13, 55, 36, tzinfo=timezone(timedelta(hours=8))))
        self.assertIsNone(r.host)

    def test_escaped_quotes(self):
        r = self.p.parse_line(ESCAPED)
        self.assertIn("GPTBot", r.ua)
        self.assertEqual(r.status, 403)

    def test_vhost_combined(self):
        r = self.p.parse_line(VHOST)
        self.assertEqual(r.host, "www.example.com")
        self.assertEqual(r.ip, "66.249.66.1")

    def test_json_and_cloudflare(self):
        r = self.p.parse_line(JSONLINE)
        self.assertEqual((r.ip, r.target, r.status, r.host), ("1.2.3.4", "/j?x=1", 200, "example.com"))
        r = self.p.parse_line(CF_LOGPUSH)
        self.assertEqual((r.ip, r.target, r.status, r.host, r.bytes), ("18.97.1.228", "/cf/page?a=1", 200, "example.com", 1234))
        self.assertEqual(r.ts.year, 2026)

    def test_garbage(self):
        self.assertIsNone(self.p.parse_line("not a log line"))
        self.assertIsNone(self.p.parse_line(""))


class ProxyTest(unittest.TestCase):
    def test_cloudflare_with_xff(self):
        p = LogParser(proxy=ProxyResolver.default())
        r = p.parse_line(CF_XFF)
        self.assertEqual(r.ip, "216.73.216.10")
        self.assertFalse(r.via_proxy)

    def test_cloudflare_without_xff_is_flagged(self):
        p = LogParser(proxy=ProxyResolver.default())
        r = p.parse_line(CF_NO_XFF)
        self.assertEqual(r.ip, "172.70.1.2")
        self.assertTrue(r.via_proxy)

    def test_rightmost_untrusted(self):
        pr = ProxyResolver(["10.0.0.0/8"], include_cloudflare=True)
        self.assertEqual(pr.resolve("10.0.0.5", "9.9.9.9, 8.8.8.8, 172.70.1.1"), ("8.8.8.8", False))
        self.assertEqual(pr.resolve("8.8.4.4", "1.1.1.1"), ("8.8.4.4", False))

    def test_disabled(self):
        p = LogParser(proxy=ProxyResolver([], include_cloudflare=False))
        r = p.parse_line(CF_XFF)
        self.assertEqual(r.ip, "172.70.1.2")
        self.assertFalse(r.via_proxy)


class OpenTest(unittest.TestCase):
    def test_gzip_and_plain(self):
        with tempfile.TemporaryDirectory() as d:
            gz = os.path.join(d, "access.log.2.gz")
            with gzip.open(gz, "wt") as f:
                f.write(COMBINED + "\n")
            plain = os.path.join(d, "access.log")
            with open(plain, "w") as f:
                f.write(COMBINED + "\n")
            for path in (gz, plain):
                with open_log(path) as f:
                    self.assertEqual(f.read().strip(), COMBINED)


if __name__ == "__main__":
    unittest.main()

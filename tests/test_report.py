import json
import re
import unittest

from tests import FIXTURES  # noqa: F401
from ai_crawler_log.report import render_html
from tests.test_analyze import AnalyzeTest


class ReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        AnalyzeTest.setUpClass()
        cls.res = AnalyzeTest.res
        evil = "/</script><script>alert(1)</script>"
        cls.res["sites"]["example.com"]["top_pages"]["user"].append({"path": evil, "requests": 1})

    @classmethod
    def tearDownClass(cls):
        AnalyzeTest.tearDownClass()

    def test_self_contained(self):
        html = render_html(self.res, lang="zh")
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertNotRegex(html, r'<script[^>]+src=|<link[^>]+href="http')
        self.assertIn("AI", html)

    def test_no_script_breakout(self):
        html = render_html(self.res, lang="en")
        self.assertNotIn("<script>alert(1)", html)
        self.assertEqual(len(re.findall(r"</script>", html, re.I)), html.lower().count("<script"))

    def test_data_roundtrip(self):
        html = render_html(self.res, lang="en")
        m = re.search(r'<script type="application/json" id="report-data">(.*?)</script>', html, re.S)
        data = json.loads(m.group(1))
        self.assertEqual(data["sites"]["example.com"]["ai_requests"], 8)

    def test_no_inner_html_with_data(self):
        html = render_html(self.res, lang="en")
        self.assertNotIn("innerHTML", html)


if __name__ == "__main__":
    unittest.main()

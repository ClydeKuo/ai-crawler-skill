import json
import os
import subprocess
import sys
import tempfile
import unittest

from tests import FIXTURES, ROOT  # noqa: F401

LAUNCHER = os.path.join(ROOT, "skills", "ai-crawler-log", "scripts", "ai-crawler-log.py")
GENERATOR = os.path.join(ROOT, "examples", "generate_sample.py")


class CliTest(unittest.TestCase):
    def test_end_to_end_offline(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([sys.executable, GENERATOR, "--out", d, "--days", "5"], check=True, capture_output=True)
            out = os.path.join(d, "r.html")
            js = os.path.join(d, "r.json")
            proc = subprocess.run([
                sys.executable, LAUNCHER, "analyze", os.path.join(d, "access.log*"), "--site", "demo-blog.example",
                "--sitemap", "demo-blog.example=" + os.path.join(d, "sitemap.xml"),
                "--robots", "demo-blog.example=" + os.path.join(d, "robots.txt"),
                "--offline", "--cache-dir", os.path.join(d, "cache"), "-o", out, "--json", js,
                "--csv-dir", os.path.join(d, "csv"), "--lang", "en"], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("AI requests", proc.stderr)
            with open(js) as f:
                r = json.load(f)
            s = r["sites"]["demo-blog.example"]
            self.assertGreater(s["categories"]["user"]["requests"], 0)
            self.assertEqual(s["bots"]["GPTBot"]["verification"]["verified"], 0)  # offline → unknown
            self.assertTrue(any(w["code"] == "offline" for w in r["warnings"]))
            self.assertTrue(os.path.exists(os.path.join(d, "csv", "never_crawled.csv")))
            self.assertGreater(os.path.getsize(out), 10000)

    def test_bots_command(self):
        proc = subprocess.run([sys.executable, LAUNCHER, "bots", "--cache-dir", tempfile.gettempdir() + "/aicl-none"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("GPTBot", proc.stdout)
        self.assertIn("Google-Extended", proc.stdout)

    def test_no_logs_is_an_error(self):
        proc = subprocess.run([sys.executable, LAUNCHER, "analyze"], capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()

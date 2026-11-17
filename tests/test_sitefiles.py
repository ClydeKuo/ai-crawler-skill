import gzip
import os
import tempfile
import unittest

from tests import FIXTURES  # noqa: F401
from ai_crawler_log.sitefiles import Robots, SiteFiles

ROBOTS = """# test
User-agent: *
Disallow: /wp-admin/
Allow: /wp-admin/admin-ajax.php
Disallow: /*?s=
Disallow: /*.pdf$

User-agent: GPTBot
User-agent: CCBot
Disallow: /

User-agent: Google-Extended
Disallow: /private/
Allow: /private/ok

Sitemap: https://example.com/sitemap_index.xml
"""

INDEX = b"""<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://example.com/post-sitemap.xml</loc></sitemap>
<sitemap><loc>https://example.com/page-sitemap.xml.gz</loc></sitemap>
</sitemapindex>"""
POSTS = b"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://example.com/hello-world/</loc></url><url><loc>https://www.example.com/second/</loc></url>
<url><loc>https://example.com/wp-content/uploads/a.jpg</loc></url></urlset>"""
PAGES = gzip.compress(b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/</loc></url>
<url><loc>https://example.com/about/</loc></url></urlset>""")


def fake_get(url, timeout=20):
    table = {
        "https://example.com/robots.txt": (200, "text/plain", ROBOTS.encode()),
        "https://example.com/sitemap_index.xml": (200, "application/xml", INDEX),
        "https://example.com/post-sitemap.xml": (200, "application/xml", POSTS),
        "https://example.com/page-sitemap.xml.gz": (200, "application/x-gzip", PAGES),
        "https://example.com/llms.txt": (200, "text/plain", b"# Example\n> hi\n"),
        "https://example.com/llms-full.txt": (200, "text/html", b"<!doctype html><html>404</html>"),
    }
    return table.get(url, (404, "text/html", b""))


class RobotsTest(unittest.TestCase):
    def setUp(self):
        self.r = Robots(ROBOTS)

    def test_groups(self):
        self.assertFalse(self.r.allowed("GPTBot", "/anything"))
        self.assertFalse(self.r.allowed("ccbot", "/"))
        self.assertTrue(self.r.explicit("GPTBot"))
        self.assertFalse(self.r.explicit("ClaudeBot"))

    def test_star_group_and_longest_match(self):
        self.assertTrue(self.r.allowed("ClaudeBot", "/blog/x"))
        self.assertFalse(self.r.allowed("ClaudeBot", "/wp-admin/options.php"))
        self.assertTrue(self.r.allowed("ClaudeBot", "/wp-admin/admin-ajax.php"))
        self.assertFalse(self.r.allowed("ClaudeBot", "/?s=hello"))
        self.assertFalse(self.r.allowed("ClaudeBot", "/files/a.pdf"))
        self.assertTrue(self.r.allowed("ClaudeBot", "/files/a.pdf?x=1"))

    def test_policy_token(self):
        self.assertFalse(self.r.allowed("Google-Extended", "/private/a"))
        self.assertTrue(self.r.allowed("Google-Extended", "/private/ok"))
        self.assertTrue(self.r.allowed("Google-Extended", "/wp-admin/"))  # own group replaces *

    def test_sitemaps(self):
        self.assertEqual(self.r.sitemaps, ["https://example.com/sitemap_index.xml"])

    def test_empty(self):
        self.assertTrue(Robots("").allowed("GPTBot", "/x"))


class SiteFilesTest(unittest.TestCase):
    def test_remote_discovery(self):
        sf = SiteFiles(get=fake_get)
        info = sf.collect("example.com")
        self.assertTrue(info.robots_found)
        self.assertEqual(info.sitemap_paths, {"/hello-world", "/second", "/", "/about"})
        self.assertTrue(info.llms["llms.txt"])
        self.assertFalse(info.llms["llms-full.txt"])

    def test_local_files_and_offline(self):
        with tempfile.TemporaryDirectory() as d:
            sm = os.path.join(d, "sitemap.xml")
            with open(sm, "wb") as f:
                f.write(POSTS)
            rb = os.path.join(d, "robots.txt")
            with open(rb, "w") as f:
                f.write(ROBOTS)
            sf = SiteFiles(get=fake_get, offline=True)
            info = sf.collect("example.com", sitemap=sm, robots=rb)
            self.assertEqual(info.sitemap_paths, {"/hello-world", "/second"})
            self.assertTrue(info.robots_found)
            self.assertIsNone(info.llms["llms.txt"])

    def test_offline_no_files(self):
        info = SiteFiles(get=fake_get, offline=True).collect("example.com")
        self.assertIsNone(info.sitemap_paths)
        self.assertFalse(info.robots_found)

    def test_non_domain_site(self):
        info = SiteFiles(get=fake_get).collect("default")
        self.assertIsNone(info.sitemap_paths)


if __name__ == "__main__":
    unittest.main()

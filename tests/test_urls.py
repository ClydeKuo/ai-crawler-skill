import unittest

from tests import FIXTURES  # noqa: F401
from ai_crawler_log.urls import normalize_path, path_kind


class UrlTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_path("/blog/post/?utm_source=x&a=1"), "/blog/post")
        self.assertEqual(normalize_path("/blog/post"), "/blog/post")
        self.assertEqual(normalize_path("https://Example.com/a/b/#frag"), "/a/b")
        self.assertEqual(normalize_path("/"), "/")
        self.assertEqual(normalize_path(""), "/")
        self.assertEqual(normalize_path("//a//b/"), "/a/b")
        self.assertEqual(normalize_path("/%E4%B8%AD%E6%96%87/"), "/%E4%B8%AD%E6%96%87")
        self.assertEqual(normalize_path("/中文/"), "/%E4%B8%AD%E6%96%87")
        self.assertEqual(normalize_path("/?p=123"), "/")
        self.assertEqual(normalize_path("/?p=123", keep_query=True), "/?p=123")
        self.assertEqual(normalize_path("/x?b=2&a=1&utm_medium=z", keep_query=True), "/x?a=1&b=2")

    def test_kind(self):
        self.assertEqual(path_kind("/blog/post"), "page")
        self.assertEqual(path_kind("/"), "page")
        self.assertEqual(path_kind("/files/whitepaper.pdf"), "page")
        self.assertEqual(path_kind("/wp-content/uploads/a.jpg"), "asset")
        self.assertEqual(path_kind("/static/app.js"), "asset")
        self.assertEqual(path_kind("/robots.txt"), "special")
        self.assertEqual(path_kind("/llms.txt"), "special")
        self.assertEqual(path_kind("/llms-full.txt"), "special")
        self.assertEqual(path_kind("/wp-sitemap.xml"), "special")
        self.assertEqual(path_kind("/sitemap_index.xml"), "special")
        self.assertEqual(path_kind("/feed"), "feed")
        self.assertEqual(path_kind("/blog/feed"), "feed")
        self.assertEqual(path_kind("/wp-admin/admin-ajax.php"), "admin")
        self.assertEqual(path_kind("/wp-json/wp/v2/posts"), "admin")
        self.assertEqual(path_kind("/xmlrpc.php"), "admin")
        self.assertEqual(path_kind("/wp-login.php"), "admin")


if __name__ == "__main__":
    unittest.main()

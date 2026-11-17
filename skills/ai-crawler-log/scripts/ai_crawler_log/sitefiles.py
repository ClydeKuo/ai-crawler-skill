"""Fetch and interpret robots.txt (RFC 9309), sitemaps, and llms.txt for a site."""

import gzip
import html
import os
import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

from .netutil import http_get
from .urls import normalize_path, path_kind

DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9-]{1,63}\.)+[a-z]{2,63}$", re.IGNORECASE)
LOC_RE = re.compile(rb"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE | re.DOTALL)


# --------------------------------------------------------------------------- robots.txt
class Robots:
    """Minimal RFC 9309 robots.txt evaluator: grouped agents, longest match, Allow wins ties, * and $."""

    def __init__(self, text):
        self.groups = []  # list of (set(agents), [(allow, pattern)])
        self.sitemaps = []
        agents, rules, last_was_agent = set(), [], False
        for raw in (text or "").splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                if not last_was_agent and agents:
                    self.groups.append((agents, rules))
                    agents, rules = set(), []
                agents.add(value.split("/", 1)[0].strip().lower())
                last_was_agent = True
            elif key in ("allow", "disallow"):
                last_was_agent = False
                if agents and (value or key == "allow"):
                    rules.append((key == "allow", value))
            elif key == "sitemap":
                self.sitemaps.append(value)
            else:
                last_was_agent = False
        if agents:
            self.groups.append((agents, rules))

    def _rules(self, token):
        token = token.lower()
        own = [r for a, rs in self.groups if token in a for r in rs]
        if any(token in a for a, _ in self.groups):
            return own
        return [r for a, rs in self.groups if "*" in a for r in rs]

    def explicit(self, token):
        return any(token.lower() in a for a, _ in self.groups)

    @staticmethod
    def _match(pattern, path):
        regex = "".join(".*" if c == "*" else re.escape(c) for c in pattern.rstrip("$"))
        if pattern.endswith("$"):
            regex += "$"
        return re.match(regex, path) is not None

    def allowed(self, token, path):
        path = unquote(path or "/")
        best = None
        for allow, pattern in self._rules(token):
            if pattern == "" or self._match(unquote(pattern), path):
                length = len(pattern)
                if best is None or length > best[0] or (length == best[0] and allow):
                    best = (length, allow)
        return True if best is None else best[1]


# --------------------------------------------------------------------------- collector
@dataclass
class SiteInfo:
    site: str
    robots_found: bool = False
    robots: Robots = None
    robots_source: str = ""
    sitemap_paths: set = None
    sitemap_sources: list = field(default_factory=list)
    llms: dict = field(default_factory=lambda: {"llms.txt": None, "llms-full.txt": None})
    errors: list = field(default_factory=list)
    explicit_sitemap: bool = False


def _same_site(host, site):
    strip = lambda h: (h or "").lower().removeprefix("www.")
    return strip(host) == strip(site)


class SiteFiles:
    def __init__(self, get=None, offline=False, max_sitemaps=200, max_urls=500000, keep_query=False):
        self.get = get or http_get
        self.offline = offline
        self.max_sitemaps = max_sitemaps
        self.max_urls = max_urls
        self.keep_query = keep_query

    def _read(self, source):
        """Return (body_bytes, content_type) from a local path or URL, or (None, reason)."""
        if source and not source.startswith(("http://", "https://")):
            try:
                with open(os.path.expanduser(source), "rb") as f:
                    return f.read(), ""
            except OSError as e:
                return None, str(e)
        if self.offline:
            return None, "offline"
        try:
            status, ctype, body = self.get(source)
        except OSError as e:
            return None, str(e)
        if status != 200:
            return None, "HTTP %s" % status
        return body, ctype

    def collect(self, site, sitemap=None, robots=None):
        info = SiteInfo(site=site)
        is_domain = bool(DOMAIN_RE.match(site or ""))
        base = "https://%s" % site
        # robots.txt
        src = robots or (base + "/robots.txt" if is_domain else None)
        if src:
            body, err = self._read(src)
            if body is not None:
                info.robots = Robots(body.decode("utf-8", "replace"))
                info.robots_found = True
                info.robots_source = src
            elif robots:
                info.errors.append("robots.txt %s: %s" % (src, err))
        # sitemap
        candidates = []
        if sitemap:
            candidates = [sitemap]
            info.explicit_sitemap = True
        elif is_domain:
            candidates = (info.robots.sitemaps if info.robots else []) + [
                base + "/sitemap.xml", base + "/sitemap_index.xml", base + "/wp-sitemap.xml"]
        for cand in dict.fromkeys(candidates):
            paths = self._sitemap(cand, site if is_domain else None, info)
            if paths:
                info.sitemap_paths = paths
                break
        # llms.txt
        if is_domain and not self.offline:
            for name in info.llms:
                body, ctype = self._read(base + "/" + name)
                info.llms[name] = bool(body) and "html" not in (ctype or "") and not body.lstrip().startswith(b"<")
        return info

    def _sitemap(self, start, site, info):
        paths, queue, seen = set(), [start], set()
        while queue and len(seen) < self.max_sitemaps and len(paths) < self.max_urls:
            src = queue.pop(0)
            if src in seen:
                continue
            seen.add(src)
            body, err = self._read(src)
            if body is None:
                if src == start and info.explicit_sitemap:
                    info.errors.append("sitemap %s: %s" % (src, err))
                continue
            if body[:2] == b"\x1f\x8b":
                try:
                    body = gzip.decompress(body)
                except OSError:
                    continue
            locs = [html.unescape(m.decode("utf-8", "replace")) for m in LOC_RE.findall(body)]
            if b"<sitemapindex" in body[:4096].lower():
                queue.extend(locs)
                continue
            info.sitemap_sources.append(src)
            for loc in locs:
                host = urlsplit(loc).hostname
                if site and host and not _same_site(host, site):
                    continue
                p = normalize_path(loc, keep_query=self.keep_query)
                if path_kind(p) == "page":
                    paths.add(p)
        return paths

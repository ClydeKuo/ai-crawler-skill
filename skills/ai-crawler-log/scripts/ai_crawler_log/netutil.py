"""Tiny HTTP helper (stdlib only)."""

import urllib.request

from . import __version__

USER_AGENT = "ai-crawler-log/%s (access-log analyzer)" % __version__


def http_get(url, timeout=20, max_bytes=50 * 1024 * 1024):
    """GET a URL; return (status, content_type, body_bytes). Raises OSError on network failure."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read(max_bytes)
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "") if e.headers else "", b""


def fetch_bytes(url, timeout=20):
    status, _, body = http_get(url, timeout=timeout)
    if status != 200:
        raise OSError("HTTP %s for %s" % (status, url))
    return body

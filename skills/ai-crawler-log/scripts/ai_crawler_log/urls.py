"""URL normalisation and path classification."""

import posixpath
import re
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

ASSET_EXT = {
    "css", "js", "mjs", "map", "png", "jpg", "jpeg", "gif", "webp", "avif", "svg", "ico", "bmp", "tif", "tiff",
    "woff", "woff2", "ttf", "otf", "eot", "mp4", "webm", "mov", "mp3", "wav", "ogg", "m4a", "zip", "gz", "rar",
    "7z", "tar", "exe", "dmg", "apk", "json", "webmanifest",
}
SPECIAL_RE = re.compile(
    r"^/(robots\.txt|llms\.txt|llms-full\.txt|ads\.txt|app-ads\.txt|security\.txt|humans\.txt|favicon\.ico"
    r"|\.well-known/.*|[\w-]*sitemap[\w-]*\.xml(\.gz)?|sitemap[\w/-]*\.xml)$",
    re.IGNORECASE,
)
ADMIN_RE = re.compile(
    r"^/(wp-admin(/|$)|wp-json(/|$)|wp-includes/|wp-login\.php|xmlrpc\.php|wp-cron\.php|wp-content/(plugins|themes)/"
    r"|cgi-bin/|\.env|\.git/|admin(/|$)|user/login)",
    re.IGNORECASE,
)
FEED_RE = re.compile(r"(^|/)(feed|rss|rss2|atom)(/[\w-]*)?$|\.(rss|atom)$|/feed\.xml$", re.IGNORECASE)
TRACKING_PARAMS = re.compile(r"^(utm_\w+|gclid|fbclid|msclkid|yclid|mc_cid|mc_eid|_ga|ref|replytocom)$", re.IGNORECASE)


def normalize_path(target, keep_query=False):
    """Return a canonical path key: no scheme/host/fragment, no trailing slash, query dropped by default."""
    if not target:
        return "/"
    if target.startswith(("http://", "https://")):
        parts = urlsplit(target)
        path, query = parts.path, parts.query
    else:
        path, _, query = target.partition("?")
        path = path.split("#", 1)[0]
        query = query.split("#", 1)[0]
    path = re.sub(r"/{2,}", "/", path or "/")
    if not path.startswith("/"):
        path = "/" + path
    path = quote(unquote(path), safe="/:@!$&'()*+,;=-._~%")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    if keep_query and query:
        pairs = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)]
        if pairs:
            path += "?" + urlencode(sorted(pairs))
    return path


def path_kind(path):
    """Classify a normalised path: page | asset | feed | special | admin."""
    p = path.split("?", 1)[0]
    if SPECIAL_RE.match(p):
        return "special"
    if ADMIN_RE.match(p):
        return "admin"
    if FEED_RE.search(p):
        return "feed"
    ext = posixpath.splitext(p)[1].lower().lstrip(".")
    if ext in ASSET_EXT or p.startswith("/wp-content/uploads/") and ext not in ("pdf", "html", "htm"):
        return "asset"
    return "page"

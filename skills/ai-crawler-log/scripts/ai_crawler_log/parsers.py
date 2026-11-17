"""Access-log parsing: nginx/Apache combined (+vhost, +extra fields), JSON logs, Cloudflare Logpush."""

import gzip
import io
import ipaddress
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from .bots import DATA_DIR

Q = r'"((?:[^"\\]|\\.)*)"'
COMBINED_RE = re.compile(
    r"^(?:(?P<vhost>\S+)\s+)?(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] "
    + Q.replace("((", "(?P<request>(", 1)
    + r" (?P<status>\d{3}) (?P<bytes>\S+)"
    + r"(?: " + Q.replace("((", "(?P<referer>(", 1) + r" " + Q.replace("((", "(?P<ua>(", 1) + r")?"
    + r"(?P<rest>.*)$"
)
QUOTED_RE = re.compile(Q)
IPLIST_RE = re.compile(r"^[0-9a-fA-F:.]+(\s*,\s*[0-9a-fA-F:.]+)*$")

JSON_KEYS = {
    "ip": ["ClientIP", "remote_addr", "client_ip", "ip", "remote_ip", "clientIp", "c-ip"],
    "xff": ["http_x_forwarded_for", "x_forwarded_for", "xff", "http_cf_connecting_ip"],
    "host": ["ClientRequestHost", "host", "http_host", "server_name", "vhost"],
    "method": ["ClientRequestMethod", "request_method", "method"],
    "uri": ["ClientRequestURI", "request_uri", "uri", "path", "ClientRequestPath"],
    "request": ["request"],
    "status": ["EdgeResponseStatus", "status", "OriginResponseStatus", "response_status", "sc-status"],
    "bytes": ["EdgeResponseBytes", "body_bytes_sent", "bytes_sent", "bytes", "size"],
    "referer": ["ClientRequestReferer", "http_referer", "referer", "referrer"],
    "ua": ["ClientRequestUserAgent", "http_user_agent", "user_agent", "ua", "useragent"],
    "time": ["EdgeStartTimestamp", "time_iso8601", "time_local", "timestamp", "time", "@timestamp", "datetime", "date"],
}


@dataclass
class Record:
    ts: datetime
    ip: str
    method: str
    target: str
    status: int
    bytes: int
    referer: str
    ua: str
    host: str = None
    via_proxy: bool = False      # arrived from a trusted proxy and the real client IP could not be restored
    behind_proxy: bool = False   # arrived from a trusted proxy (Cloudflare etc.)


def _unescape(s):
    if "\\" not in s:
        return s
    return s.replace('\\"', '"').replace("\\x22", '"').replace("\\\\", "\\")


def _clean_host(h):
    if not h or h == "-":
        return None
    h = h.strip().lower()
    if h.startswith("["):
        return h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def parse_time(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        n = int(value)
        if n > 10**17:
            n = n / 1e9
        elif n > 10**14:
            n = n / 1e6
        elif n > 10**11:
            n = n / 1e3
        return datetime.fromtimestamp(n, tz=timezone.utc)
    for fmt in ("%d/%b/%Y:%H:%M:%S %z",):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


class ProxyResolver:
    """Restore the real client IP when requests arrive through Cloudflare or other trusted proxies."""

    def __init__(self, trusted_cidrs=(), include_cloudflare=True):
        nets = [ipaddress.ip_network(c.strip(), strict=False) for c in trusted_cidrs if c.strip()]
        if include_cloudflare:
            with open(os.path.join(DATA_DIR, "cloudflare_ips.txt")) as f:
                nets += [ipaddress.ip_network(line.strip()) for line in f if line.strip()]
        self.nets = nets
        self._cache = {}

    @classmethod
    def default(cls):
        return cls([], include_cloudflare=True)

    def is_trusted(self, ip):
        if ip in self._cache:
            return self._cache[ip]
        try:
            addr = ipaddress.ip_address(ip)
            hit = any(addr in n for n in self.nets)
        except ValueError:
            hit = False
        if len(self._cache) < 200000:
            self._cache[ip] = hit
        return hit

    def resolve(self, remote, xff):
        """Return (client_ip, via_proxy_unresolved)."""
        if not self.nets or not self.is_trusted(remote):
            return remote, False
        if xff and xff != "-":
            for candidate in reversed([x.strip() for x in xff.split(",") if x.strip()]):
                if not self.is_trusted(candidate):
                    return candidate, False
        return remote, True


class LogParser:
    def __init__(self, proxy=None):
        self.proxy = proxy

    def parse_line(self, line):
        line = line.strip()
        if not line:
            return None
        if line.startswith("{"):
            return self._parse_json(line)
        return self._parse_combined(line)

    def _finish(self, ip, xff, **kw):
        via = behind = False
        if self.proxy is not None:
            behind = self.proxy.is_trusted(ip) if self.proxy.nets else False
            ip, via = self.proxy.resolve(ip, xff)
        return Record(ip=ip, via_proxy=via, behind_proxy=behind, **kw)

    def _parse_combined(self, line):
        m = COMBINED_RE.match(line)
        if not m:
            return None
        ts = parse_time(m.group("time"))
        if ts is None:
            return None
        parts = _unescape(m.group("request")).split(" ")
        if len(parts) >= 2:
            method, target = parts[0], parts[1]
        else:
            method, target = "-", parts[0]
        xff = None
        rest = m.group("rest") or ""
        for q in QUOTED_RE.findall(rest):
            if q and IPLIST_RE.match(q.strip()):
                xff = q
                break
        return self._finish(
            m.group("ip"), xff,
            ts=ts, method=method, target=target, status=int(m.group("status")), bytes=_int(m.group("bytes")),
            referer=_unescape(m.group("referer") or "-"), ua=_unescape(m.group("ua") or "-"),
            host=_clean_host(m.group("vhost")),
        )

    def _parse_json(self, line):
        try:
            d = json.loads(line)
        except ValueError:
            return None
        if not isinstance(d, dict):
            return None

        def get(key):
            for k in JSON_KEYS[key]:
                if k in d and d[k] not in (None, ""):
                    return d[k]
            return None

        ip, ts = get("ip"), parse_time(get("time"))
        if not ip or ts is None:
            return None
        method, target = get("method"), get("uri")
        req = get("request")
        if req and (not target or not method):
            parts = str(req).split(" ")
            method = method or parts[0]
            target = target or (parts[1] if len(parts) > 1 else "/")
        return self._finish(
            str(ip), get("xff"),
            ts=ts, method=str(method or "GET"), target=str(target or "/"), status=_int(get("status")),
            bytes=_int(get("bytes")), referer=str(get("referer") or "-"), ua=str(get("ua") or "-"),
            host=_clean_host(get("host")),
        )


def open_log(path):
    """Open a plain or gzip log as text (utf-8, replacing bad bytes). '-' means stdin."""
    if path == "-":
        return io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    with open(path, "rb") as f:
        magic = f.read(2)
    if magic == b"\x1f\x8b":
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", errors="replace")
    return open(path, encoding="utf-8", errors="replace")

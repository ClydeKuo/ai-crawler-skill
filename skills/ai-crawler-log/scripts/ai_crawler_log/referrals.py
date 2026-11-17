"""Detect human visits that came from AI products (Referer header or utm_source)."""

from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit


@dataclass(frozen=True)
class Referral:
    source: str
    operator: str
    via: str  # "referer" | "utm"


class ReferralDetector:
    def __init__(self, referral_defs):
        self._hosts = []
        self._utm = {}
        for d in referral_defs:
            for h in d.get("hosts", []):
                self._hosts.append((h.lower(), d))
            for u in d.get("utm", []):
                self._utm[u.lower()] = d

    def _host_match(self, host):
        host = host.lower().split(":", 1)[0]
        for h, d in self._hosts:
            if host == h or host.endswith("." + h):
                return d
        return None

    def detect(self, referer, target):
        if referer and referer != "-":
            try:
                host = urlsplit(referer if "//" in referer else "//" + referer).hostname or ""
            except ValueError:
                host = ""
            d = self._host_match(host) if host else None
            if d:
                return Referral(d["source"], d["operator"], "referer")
        if target and "utm_source=" in target:
            query = target.split("?", 1)[1] if "?" in target else ""
            for value in parse_qs(query).get("utm_source", []):
                d = self._utm.get(value.lower()) or self._host_match(value)
                if d:
                    return Referral(d["source"], d["operator"], "utm")
        return None

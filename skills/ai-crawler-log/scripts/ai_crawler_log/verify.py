"""Crawler identity verification: official IP ranges + forward-confirmed reverse DNS (FCrDNS).

Result states:
  verified      IP in an official range, or FCrDNS hostname matches an official suffix
  spoofed       verification methods exist, all ran, none passed
  unverifiable  the operator publishes no verification method
  unknown       a method exists but could not run (offline, download/DNS failure, IP is a CDN proxy)
"""

import hashlib
import ipaddress
import json
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor

from .netutil import fetch_bytes

STATES = ["verified", "unverifiable", "unknown", "spoofed"]
RANGES_TTL = 24 * 3600
RDNS_TTL = 7 * 24 * 3600


def extract_prefixes(obj):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("ipv4Prefix", "ipv6Prefix", "ip_prefix", "ipv6_prefix") and isinstance(v, str):
                out.append(v)
            else:
                out.extend(extract_prefixes(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(extract_prefixes(v))
    return out


def default_reverse(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except (OSError, UnicodeError):
        return None


def default_forward(host):
    try:
        return list({ai[4][0] for ai in socket.getaddrinfo(host, None)})
    except (OSError, UnicodeError):
        return []


def default_cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "ai-crawler-log")


class Verifier:
    def __init__(self, cache_dir=None, offline=False, use_dns=True, fetch=None, reverse=None, forward=None,
                 workers=32, dns_timeout=3.0, log=None):
        self.cache_dir = cache_dir or default_cache_dir()
        self.offline = offline
        self.use_dns = use_dns and not offline
        self.fetch = fetch or fetch_bytes
        self.reverse = reverse or default_reverse
        self.forward = forward or default_forward
        self.workers = workers
        self.dns_timeout = dns_timeout
        self.log = log or (lambda msg: None)
        self._ranges = {}
        self._rdns_path = os.path.join(self.cache_dir, "rdns.json")
        self._rdns = self._load_json(self._rdns_path) or {}
        self.range_status = {}  # url -> "fresh" | "cached" | "stale" | "missing"

    # -- cache helpers --------------------------------------------------------
    @staticmethod
    def _load_json(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _save_json(self, path, data):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, path)
        except OSError:
            pass

    # -- IP ranges ------------------------------------------------------------
    def networks(self, url):
        """Return list of ip_network for url, or None if unavailable."""
        if url in self._ranges:
            return self._ranges[url]
        path = os.path.join(self.cache_dir, "ipranges", hashlib.sha1(url.encode()).hexdigest()[:16] + ".json")
        cached = self._load_json(path)
        prefixes = None
        if cached and (self.offline or time.time() - cached.get("fetched", 0) < RANGES_TTL):
            prefixes = cached["prefixes"]
            self.range_status[url] = "cached"
        elif not self.offline:
            try:
                prefixes = extract_prefixes(json.loads(self.fetch(url)))
                if prefixes:
                    self._save_json(path, {"url": url, "fetched": time.time(), "prefixes": prefixes})
                    self.range_status[url] = "fresh"
                else:
                    prefixes = None
            except (OSError, ValueError) as e:
                self.log("warning: could not download %s (%s)" % (url, e))
            if prefixes is None and cached:
                prefixes = cached["prefixes"]
                self.range_status[url] = "stale"
        if prefixes is None:
            self.range_status[url] = "missing"
            self._ranges[url] = None
            return None
        nets = []
        for p in prefixes:
            try:
                nets.append(ipaddress.ip_network(p, strict=False))
            except ValueError:
                pass
        self._ranges[url] = nets
        return nets

    # -- reverse DNS ----------------------------------------------------------
    def _fcrdns(self, ip):
        """Return forward-confirmed hostname, '' if none/mismatch, or None if DNS failed to run."""
        entry = self._rdns.get(ip)
        if entry and time.time() - entry[1] < RDNS_TTL:
            return entry[0]
        if not self.use_dns:
            return entry[0] if entry else None
        host = self.reverse(ip)
        confirmed = ""
        if host:
            host = host.rstrip(".").lower()
            if ip in self.forward(host):
                confirmed = host
        self._rdns[ip] = [confirmed, time.time()]
        return confirmed

    @staticmethod
    def _suffix_ok(host, suffixes):
        return any(host == s or host.endswith("." + s) for s in suffixes)

    # -- main -----------------------------------------------------------------
    def verify_many(self, items):
        """items: iterable of (Bot, ip, via_proxy). Returns {(bot.name, ip): state}."""
        items = list({(b.name, ip): (b, ip, via) for b, ip, via in items}.values())
        result, need_dns = {}, []
        for bot, ip, via in items:
            key = (bot.name, ip)
            if not bot.verifiable:
                result[key] = "unverifiable"
                continue
            if via:
                result[key] = "unknown"
                continue
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                result[key] = "spoofed"
                continue
            range_known = False
            matched = False
            for url in bot.ip_ranges:
                nets = self.networks(url)
                if nets is None:
                    continue
                range_known = True
                if any(addr.version == n.version and addr in n for n in nets):
                    matched = True
                    break
            if matched:
                result[key] = "verified"
            elif bot.rdns:
                need_dns.append((bot, ip, range_known))
            else:
                result[key] = "spoofed" if range_known else "unknown"
        if need_dns:
            ips = sorted({ip for _, ip, _ in need_dns})
            old = socket.getdefaulttimeout()
            socket.setdefaulttimeout(self.dns_timeout)
            try:
                with ThreadPoolExecutor(max_workers=self.workers) as ex:
                    hosts = dict(zip(ips, ex.map(self._fcrdns, ips)))
            finally:
                socket.setdefaulttimeout(old)
            for bot, ip, range_known in need_dns:
                host = hosts.get(ip)
                if host is None:
                    result[(bot.name, ip)] = "unknown"
                elif host and self._suffix_ok(host, bot.rdns):
                    result[(bot.name, ip)] = "verified"
                else:
                    result[(bot.name, ip)] = "spoofed"
            self._save_json(self._rdns_path, self._rdns)
        return result

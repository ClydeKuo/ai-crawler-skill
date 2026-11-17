"""Command-line interface: analyze | bots | update-bots."""

import argparse
import json
import os
import sys
from datetime import date

from . import __version__
from .analyze import AnalyzeOptions, analyze, expand_sources, site_key
from .bots import BotRegistry
from .export import write_csvs, write_json
from .netutil import fetch_bytes
from .parsers import ProxyResolver
from .report import render_html
from .sitefiles import SiteFiles
from .verify import Verifier, default_cache_dir

AI_ROBOTS_URL = "https://raw.githubusercontent.com/ai-robots-txt/ai.robots.txt/main/robots.json"


def _kv(values, flag):
    out = {}
    for v in values or []:
        if "=" not in v:
            raise SystemExit("%s expects SITE=VALUE, got %r" % (flag, v))
        k, val = v.split("=", 1)
        out[site_key(k)] = val
    return out


def _date(s):
    return date.fromisoformat(s)


def _extra_path(cache_dir):
    return os.path.join(cache_dir, "ai_robots_txt_bots.json")


def load_registry(cache_dir, use_extra=True):
    extra = None
    p = _extra_path(cache_dir)
    if use_extra and os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            extra = json.load(f)
    return BotRegistry.load(extra=extra)


def build_parser():
    p = argparse.ArgumentParser(prog="ai-crawler-log", description="See which AI crawlers read your website, from raw access logs.")
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("analyze", help="analyze access logs and write an HTML report")
    a.add_argument("logs", nargs="*", help="log files, globs, directories, or - for stdin (.gz supported)")
    a.add_argument("--log", action="append", metavar="SITE=PATH", help="log file/glob for a specific site (repeatable)")
    a.add_argument("--site", help="site name for logs without a host field (default: 'default')")
    a.add_argument("--sitemap", action="append", metavar="SITE=URL|FILE", help="sitemap override (repeatable)")
    a.add_argument("--robots", action="append", metavar="SITE=URL|FILE", help="robots.txt override (repeatable)")
    a.add_argument("-o", "--output", default="ai-crawler-report.html", help="HTML report path (default: %(default)s)")
    a.add_argument("--json", metavar="PATH", help="also write the full result as JSON")
    a.add_argument("--csv-dir", metavar="DIR", help="also write CSV tables into DIR")
    a.add_argument("--lang", default="zh", choices=["zh", "en"], help="report language (default: %(default)s)")
    a.add_argument("--since", type=_date, metavar="YYYY-MM-DD")
    a.add_argument("--until", type=_date, metavar="YYYY-MM-DD")
    a.add_argument("--keep-query", action="store_true", help="treat ?query variants as distinct pages (tracking params still dropped)")
    a.add_argument("--trusted-proxy", action="append", metavar="CIDR", help="extra reverse-proxy ranges whose X-Forwarded-For is trusted")
    a.add_argument("--no-cloudflare", action="store_true", help="do not treat Cloudflare IPs as a trusted proxy")
    a.add_argument("--offline", action="store_true", help="no network at all: no IP-range download, DNS, robots/sitemap/llms fetch")
    a.add_argument("--no-dns", action="store_true", help="skip reverse-DNS verification")
    a.add_argument("--no-site-fetch", action="store_true", help="do not fetch robots.txt / sitemap / llms.txt from the site")
    a.add_argument("--no-extra-bots", action="store_true", help="ignore bots imported with update-bots")
    a.add_argument("--top", type=int, default=50, help="top-N pages kept per category (default: %(default)s)")
    a.add_argument("--cache-dir", default=default_cache_dir())
    a.add_argument("-q", "--quiet", action="store_true")

    b = sub.add_parser("bots", help="list known crawlers")
    b.add_argument("--cache-dir", default=default_cache_dir())
    b.add_argument("--json", action="store_true")

    u = sub.add_parser("update-bots", help="import the community list from ai-robots-txt/ai.robots.txt")
    u.add_argument("--cache-dir", default=default_cache_dir())
    u.add_argument("--url", default=AI_ROBOTS_URL)
    return p


def cmd_analyze(args):
    log = (lambda m: None) if args.quiet else (lambda m: print(m, file=sys.stderr))
    specs = [(None, x) for x in args.logs] + [(site_key(k), v) for k, v in _kv(args.log, "--log").items()]
    if not specs:
        raise SystemExit("no logs given (pass files/globs/directories, --log SITE=PATH, or - for stdin)")
    sources = expand_sources(specs)
    registry = load_registry(args.cache_dir, use_extra=not args.no_extra_bots)
    verifier = Verifier(cache_dir=args.cache_dir, offline=args.offline, use_dns=not args.no_dns, log=log)
    sitefiles = SiteFiles(offline=args.offline or args.no_site_fetch, keep_query=args.keep_query)
    opts = AnalyzeOptions(
        default_site=args.site or "default", since=args.since, until=args.until, keep_query=args.keep_query,
        sitemaps=_kv(args.sitemap, "--sitemap"), robots=_kv(args.robots, "--robots"), top_n=args.top,
        proxy=ProxyResolver(args.trusted_proxy or [], include_cloudflare=not args.no_cloudflare),
    )
    result = analyze(sources, registry, verifier, sitefiles, opts, log=log)
    if not result["sites"]:
        raise SystemExit("no log lines were read")
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(render_html(result, lang=args.lang))
    log("report: %s" % os.path.abspath(args.output))
    if args.json:
        write_json(result, args.json)
        log("json:   %s" % os.path.abspath(args.json))
    if args.csv_dir:
        write_csvs(result, args.csv_dir)
        log("csv:    %s" % os.path.abspath(args.csv_dir))
    _print_summary(result, log)
    return 0


def _print_summary(result, log):
    for name, r in result["sites"].items():
        log("\n[%s] %s → %s, %d lines parsed" % (name, r["period"]["start"], r["period"]["end"], r["lines"]["parsed"]))
        log("  AI requests: %d  (user-triggered %d, search %d, training %d)  spoofed: %d  blocked: %.1f%%  AI referrals: %d" % (
            r["ai_requests"], r["categories"]["user"]["requests"], r["categories"]["search"]["requests"],
            r["categories"]["training"]["requests"], r["spoofed"]["total"], r["blocked"]["share"] * 100, r["referrals"]["total"]))
        if r["coverage"]:
            c = r["coverage"]
            log("  sitemap coverage by AI: %d / %d" % (c["crawled_by_ai"], c["sitemap_total"]))
    for w in result["warnings"]:
        log("warning: %s" % json.dumps(w, ensure_ascii=False))


def cmd_bots(args):
    reg = load_registry(args.cache_dir)
    if args.json:
        print(json.dumps([{"name": b.name, "operator": b.operator, "category": b.category, "ua": b.ua,
                           "ip_ranges": b.ip_ranges, "rdns": b.rdns, "source": b.source} for b in reg.bots], indent=1))
        return 0
    print("%-30s %-14s %-15s %-10s %s" % ("NAME", "OPERATOR", "CATEGORY", "VERIFY", "SOURCE"))
    for b in reg.bots:
        v = "+".join(x for x, ok in (("ip", b.ip_ranges), ("rdns", b.rdns)) if ok) or "-"
        print("%-30s %-14s %-15s %-10s %s" % (b.name, b.operator[:14], b.category, v, b.source))
    print("\npolicy tokens (robots.txt only): " + ", ".join(p["token"] for p in reg.policy_tokens))
    return 0


def cmd_update_bots(args):
    raw = json.loads(fetch_bytes(args.url))
    extra = BotRegistry.convert_ai_robots_txt(raw, existing=BotRegistry.load())
    os.makedirs(args.cache_dir, exist_ok=True)
    with open(_extra_path(args.cache_dir), "w", encoding="utf-8") as f:
        json.dump(extra, f, ensure_ascii=False, indent=1)
    print("imported %d extra crawlers and %d policy tokens from %s" % (len(extra["bots"]), len(extra["policy_tokens"]), args.url))
    return 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "analyze":
        return cmd_analyze(args)
    if args.cmd == "bots":
        return cmd_bots(args)
    if args.cmd == "update-bots":
        return cmd_update_bots(args)
    parser.print_help()
    return 1

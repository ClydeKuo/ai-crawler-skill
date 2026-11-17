"""Stream access logs, classify, verify, aggregate. Produces a JSON-serialisable result dict."""

import glob
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

from . import __version__
from .bots import AI_CATEGORIES, CATEGORIES
from .parsers import LogParser, ProxyResolver, open_log
from .referrals import ReferralDetector
from .urls import normalize_path, path_kind
from .verify import STATES

ALL = "*"
GENERIC_BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|fetch|scan|curl|wget|python|java/|go-http|okhttp|httpclient|axios|node-fetch|headless|lighthouse|monitor|preview",
    re.IGNORECASE,
)
LLMS_PATHS = {"/llms.txt", "/llms-full.txt"}
PROXY_WARN_SHARE = 0.05


@dataclass
class LogSource:
    path: str
    site: str = None


@dataclass
class AnalyzeOptions:
    default_site: str = "default"
    since: date = None
    until: date = None
    keep_query: bool = False
    sitemaps: dict = field(default_factory=dict)
    robots: dict = field(default_factory=dict)
    top_n: int = 50
    proxy: ProxyResolver = None
    progress: object = None


def expand_sources(specs):
    """specs: list of (site_or_None, path_or_glob_or_dir). Returns LogSource list."""
    out = []
    for site, spec in specs:
        if spec == "-":
            out.append(LogSource("-", site))
            continue
        if os.path.isdir(spec):
            paths = sorted(p for p in glob.glob(os.path.join(spec, "*")) if os.path.isfile(p) and re.search(r"access|\.log", os.path.basename(p)))
        else:
            paths = sorted(glob.glob(os.path.expanduser(spec))) or [spec]
        out.extend(LogSource(p, site) for p in paths)
    return out


def site_key(host):
    host = (host or "").lower().strip().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def status_bucket(st):
    if st in (403, 429):
        return str(st)
    return "%dxx" % (st // 100) if 100 <= st < 600 else "other"


class SiteAgg:
    def __init__(self, name, registry, top_n):
        self.name = name
        self.registry = registry
        self.top_n = top_n
        self.lines = Counter()
        self.first = None
        self.last = None
        self.proxy = Counter()
        self.bot = defaultdict(lambda: {
            "requests": 0, "verification": Counter(), "status": Counter(), "kinds": Counter(), "daily": Counter(),
            "pages": set(), "first_seen": None, "last_seen": None, "robots_txt_fetches": 0, "llms_txt_fetches": 0,
            "bytes": 0, "spoofed_ips": Counter(), "violations": 0, "violation_paths": Counter(),
        })
        self.daily = defaultdict(Counter)
        self.page_hits = defaultdict(Counter)       # category -> Counter(path)
        self.read_paths = defaultdict(set)          # category -> set(path) (status < 400)
        self.ref_daily = defaultdict(Counter)       # source -> Counter(date)
        self.ref_landing = defaultdict(Counter)     # source -> Counter(path)
        self.ref_operator = {}
        self.ref_via = Counter()
        self.human_pv = Counter()                   # date -> pageviews
        self.site_info = None

    def seen(self, ts):
        d = ts.date()
        if self.first is None or d < self.first:
            self.first = d
        if self.last is None or d > self.last:
            self.last = d

    def add_bot_hit(self, bot, ip, state, day, path, kind, status, nbytes, ts, violation):
        b = self.bot[bot.name]
        b["verification"][state] += 1
        if state == "spoofed":
            b["spoofed_ips"][ip] += 1
            return
        b["requests"] += 1
        b["status"][status_bucket(status)] += 1
        b["kinds"][kind] += 1
        b["daily"][day] += 1
        b["bytes"] += nbytes
        tsu = ts.astimezone(timezone.utc).isoformat(timespec="seconds")
        b["first_seen"] = min(b["first_seen"] or tsu, tsu)
        b["last_seen"] = max(b["last_seen"] or tsu, tsu)
        if path == "/robots.txt":
            b["robots_txt_fetches"] += 1
        if path in LLMS_PATHS:
            b["llms_txt_fetches"] += 1
        if violation:
            b["violations"] += 1
            b["violation_paths"][path] += 1
        self.daily[day][bot.category] += 1
        if kind == "page":
            b["pages"].add(path)
            if status < 400:
                self.page_hits[bot.category][path] += 1
                self.read_paths[bot.category].add(path)

    def add_referral(self, ref, day, path):
        self.ref_daily[ref.source][day] += 1
        self.ref_landing[ref.source][path] += 1
        self.ref_operator[ref.source] = ref.operator
        self.ref_via[ref.via] += 1

    # ------------------------------------------------------------------ finalize
    def finalize(self, policy_tokens):
        reg = self.registry
        bots = {}
        for name, b in sorted(self.bot.items(), key=lambda kv: -kv[1]["requests"]):
            bot = reg.get(name)
            bots[name] = {
                "operator": bot.operator, "category": bot.category, "source": bot.source,
                "verifiable": bot.verifiable, "robots_token": bot.robots_token,
                "requests": b["requests"], "unique_pages": len(b["pages"]),
                "verification": {s: b["verification"].get(s, 0) for s in STATES},
                "status": dict(b["status"]), "kinds": dict(b["kinds"]), "daily": dict(sorted(b["daily"].items())),
                "first_seen": b["first_seen"], "last_seen": b["last_seen"], "bytes": b["bytes"],
                "robots_txt_fetches": b["robots_txt_fetches"], "llms_txt_fetches": b["llms_txt_fetches"],
                "violations": b["violations"],
                "violation_paths": [{"path": p, "requests": n} for p, n in b["violation_paths"].most_common(10)],
            }
        categories = {c: {"requests": 0, "bots": 0} for c in CATEGORIES}
        for name, b in bots.items():
            c = categories[b["category"]]
            c["requests"] += b["requests"]
            c["bots"] += 1 if b["requests"] else 0
        ai_requests = sum(categories[c]["requests"] for c in AI_CATEGORIES)
        blocked = sum(b["status"].get("403", 0) + b["status"].get("429", 0)
                      for b in bots.values() if b["category"] in AI_CATEGORIES)

        spoofed_ips = Counter()
        spoofed_by_bot = {}
        for name, b in self.bot.items():
            if b["spoofed_ips"]:
                spoofed_by_bot[name] = sum(b["spoofed_ips"].values())
                for ip, n in b["spoofed_ips"].items():
                    spoofed_ips[(ip, name)] += n

        # referrals & operator ratios
        by_source = {}
        for src, daily in sorted(self.ref_daily.items(), key=lambda kv: -sum(kv[1].values())):
            by_source[src] = {
                "operator": self.ref_operator[src], "visits": sum(daily.values()), "daily": dict(sorted(daily.items())),
                "landing_pages": [{"path": p, "visits": n} for p, n in self.ref_landing[src].most_common(self.top_n)],
            }
        ref_total = sum(s["visits"] for s in by_source.values())
        ops = defaultdict(lambda: {"crawls": 0, "user_fetches": 0, "referrals": 0})
        for b in bots.values():
            if b["category"] in AI_CATEGORIES and b["operator"]:
                ops[b["operator"]]["crawls"] += b["requests"]
                if b["category"] == "user":
                    ops[b["operator"]]["user_fetches"] += b["requests"]
        for s in by_source.values():
            ops[s["operator"]]["referrals"] += s["visits"]
        operators = []
        for op, v in ops.items():
            v = dict(v, operator=op)
            v["crawls_per_referral"] = round(v["crawls"] / v["referrals"], 1) if v["referrals"] else None
            operators.append(v)
        operators.sort(key=lambda v: (-v["crawls"], -v["referrals"]))

        # coverage
        info = self.site_info
        coverage = None
        if info is not None and info.sitemap_paths:
            sm = info.sitemap_paths
            ai_read = set().union(*(self.read_paths[c] for c in AI_CATEGORIES))
            coverage = {
                "sitemap_total": len(sm), "sitemap_sources": info.sitemap_sources,
                "crawled_by_ai": len(sm & ai_read),
                "by_category": {c: len(sm & self.read_paths[c]) for c in CATEGORIES},
                "never_crawled": sorted(sm - ai_read),
                "not_in_sitemap": len(ai_read - sm),
            }

        # robots / llms
        robots = None
        if info is not None:
            tokens = []
            if info.robots_found:
                seen = set()
                for name, b in bots.items():
                    tok = b["robots_token"]
                    if tok in seen:
                        continue
                    seen.add(tok)
                    tokens.append({
                        "token": tok, "operator": b["operator"], "category": b["category"],
                        "explicit": info.robots.explicit(tok), "allowed_root": info.robots.allowed(tok, "/"),
                        "violations": sum(x["violations"] for x in bots.values() if x["robots_token"] == tok),
                    })
            policy = []
            for p in policy_tokens:
                policy.append(dict(p, explicit=info.robots.explicit(p["token"]) if info.robots_found else False,
                                   allowed_root=info.robots.allowed(p["token"], "/") if info.robots_found else None))
            robots = {"found": info.robots_found, "source": info.robots_source, "tokens": tokens,
                      "policy_tokens": policy, "errors": info.errors}
        llms = {
            "exists": dict(info.llms) if info is not None else {"llms.txt": None, "llms-full.txt": None},
            "fetches": {n: b["llms_txt_fetches"] for n, b in bots.items() if b["llms_txt_fetches"]},
            "robots_fetches": {n: b["robots_txt_fetches"] for n, b in bots.items() if b["robots_txt_fetches"]},
        }

        days = (self.last - self.first).days + 1 if self.first else 0
        return {
            "site": self.name,
            "period": {"start": self.first.isoformat() if self.first else None,
                       "end": self.last.isoformat() if self.last else None, "days": days},
            "lines": {"total": self.lines["total"], "parsed": self.lines["parsed"], "unparsed": self.lines["total"] - self.lines["parsed"]},
            "proxy": {"behind_proxy": self.proxy["behind"], "unresolved": self.proxy["unresolved"]},
            "ai_requests": ai_requests,
            "blocked": {"requests": blocked, "share": round(blocked / ai_requests, 4) if ai_requests else 0},
            "categories": categories,
            "daily": {d: dict(c) for d, c in sorted(self.daily.items())},
            "bots": bots,
            "top_pages": {c: [{"path": p, "requests": n} for p, n in self.page_hits[c].most_common(self.top_n)] for c in CATEGORIES},
            "coverage": coverage,
            "referrals": {"total": ref_total, "via": dict(self.ref_via), "by_source": by_source,
                          "human_pageviews": sum(self.human_pv.values()), "human_daily": dict(sorted(self.human_pv.items()))},
            "operators": operators,
            "robots": robots,
            "llms": llms,
            "spoofed": {"total": sum(spoofed_by_bot.values()), "by_bot": spoofed_by_bot,
                        "top_ips": [{"ip": ip, "bot": name, "requests": n} for (ip, name), n in spoofed_ips.most_common(20)]},
        }


def analyze(sources, registry, verifier, sitefiles, options=None, log=None):
    opt = options or AnalyzeOptions()
    log = log or (lambda msg: None)
    parser = LogParser(proxy=opt.proxy)
    referrals = ReferralDetector(registry.referrals)
    aggs = {}

    def agg(site):
        if site not in aggs:
            aggs[site] = SiteAgg(site, registry, opt.top_n)
        return aggs[site]

    hits = []  # (site, bot, ip, via_proxy, day, path, kind, status, bytes, ts, target_path)
    path_cache = {}
    for src in sources:
        log("reading %s" % src.path)
        try:
            fh = open_log(src.path)
        except OSError as e:
            log("warning: cannot open %s: %s" % (src.path, e))
            continue
        with fh:
            for raw in fh:
                rec = parser.parse_line(raw)
                site = site_key(src.site) if src.site else None
                if rec is not None:
                    site = site or site_key(rec.host) or site_key(opt.default_site)
                a = agg(site or site_key(opt.default_site))
                a.lines["total"] += 1
                if rec is None:
                    continue
                d = rec.ts.date()
                if (opt.since and d < opt.since) or (opt.until and d > opt.until):
                    a.lines["total"] -= 1
                    continue
                a.lines["parsed"] += 1
                a.seen(rec.ts)
                if rec.behind_proxy:
                    a.proxy["behind"] += 1
                if rec.via_proxy:
                    a.proxy["unresolved"] += 1
                key = (rec.target, opt.keep_query)
                pk = path_cache.get(key)
                if pk is None:
                    p = normalize_path(rec.target, keep_query=opt.keep_query)
                    pk = (p, path_kind(p))
                    if len(path_cache) < 500000:
                        path_cache[key] = pk
                path, kind = pk
                day = d.isoformat()
                bot = registry.match(rec.ua)
                if bot is not None:
                    hits.append((a.name, bot, rec.ip, rec.via_proxy, day, path, kind, rec.status, rec.bytes, rec.ts,
                                 rec.target.split("#", 1)[0]))
                    continue
                if kind != "page" or rec.status >= 400 or rec.method not in ("GET", "HEAD") or GENERIC_BOT_RE.search(rec.ua or ""):
                    continue
                a.human_pv[day] += 1
                ref = referrals.detect(rec.referer, rec.target)
                if ref is not None:
                    a.add_referral(ref, day, path)

    log("verifying %d unique crawler IPs" % len({(h[1].name, h[2]) for h in hits}))
    states = verifier.verify_many((h[1], h[2], h[3]) for h in hits)

    for name, a in aggs.items():
        if a.lines["parsed"]:
            src = opt.sitemaps.get(name), opt.robots.get(name)
            log("collecting robots.txt / sitemap / llms.txt for %s" % name)
            a.site_info = sitefiles.collect(name, sitemap=src[0], robots=src[1])

    multi = len([a for a in aggs.values() if a.lines["parsed"]]) > 1
    total = SiteAgg(ALL, registry, opt.top_n) if multi else None
    allowed_cache = {}
    for site, bot, ip, via, day, path, kind, status, nbytes, ts, target in hits:
        a = aggs[site]
        state = states.get((bot.name, ip), "unknown")
        violation = False
        if state != "spoofed" and a.site_info is not None and a.site_info.robots_found and path != "/robots.txt":
            ck = (site, bot.robots_token, target)
            if ck not in allowed_cache:
                allowed_cache[ck] = a.site_info.robots.allowed(bot.robots_token, _robots_target(target))
            violation = not allowed_cache[ck]
        a.add_bot_hit(bot, ip, state, day, path, kind, status, nbytes, ts, violation)
        if total is not None:
            total.add_bot_hit(bot, ip, state, day, site + path, kind, status, nbytes, ts, violation)

    results = {}
    for name, a in sorted(aggs.items(), key=lambda kv: -sum(b["requests"] for b in kv[1].bot.values())):
        if a.lines["total"]:
            results[name] = a.finalize(registry.policy_tokens)

    all_result = None
    if total is not None:
        for a in aggs.values():
            total.lines.update(a.lines)
            total.proxy.update(a.proxy)
            total.human_pv.update(a.human_pv)
            for d in (a.first, a.last):
                if d:
                    total.seen(datetime(d.year, d.month, d.day))
            for src_name, daily in a.ref_daily.items():
                total.ref_daily[src_name].update(daily)
                total.ref_landing[src_name].update({a.name + p: n for p, n in a.ref_landing[src_name].items()})
                total.ref_operator[src_name] = a.ref_operator[src_name]
            total.ref_via.update(a.ref_via)
        all_result = total.finalize(registry.policy_tokens)
        all_result["coverage"] = _merge_coverage(results)

    return {
        "tool": {"name": "ai-crawler-log", "version": __version__},
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": [s.path for s in sources],
        "sites": results,
        "all": all_result,
        "verification": {"offline": getattr(verifier, "offline", False), "ranges": dict(getattr(verifier, "range_status", {}))},
        "warnings": _warnings(results, verifier),
    }


def _robots_target(target):
    if target.startswith(("http://", "https://")):
        parts = urlsplit(target)
        return (parts.path or "/") + ("?" + parts.query if parts.query else "")
    return target or "/"


def _merge_coverage(results):
    covs = [(s, r["coverage"]) for s, r in results.items() if r.get("coverage")]
    if not covs:
        return None
    out = {"sitemap_total": 0, "crawled_by_ai": 0, "by_category": Counter(), "never_crawled": [], "not_in_sitemap": 0, "sitemap_sources": []}
    for site, c in covs:
        out["sitemap_total"] += c["sitemap_total"]
        out["crawled_by_ai"] += c["crawled_by_ai"]
        out["by_category"].update(c["by_category"])
        out["never_crawled"] += [site + p for p in c["never_crawled"]]
        out["not_in_sitemap"] += c["not_in_sitemap"]
    out["by_category"] = dict(out["by_category"])
    return out


def _warnings(results, verifier):
    w = []
    for site, r in results.items():
        bp, un = r["proxy"]["behind_proxy"], r["proxy"]["unresolved"]
        # A few Cloudflare-range IPs are normal (WARP users); only warn when it is systematic.
        if un and un / max(r["lines"]["parsed"], 1) >= PROXY_WARN_SHARE:
            # When the log systematically records proxy IPs, "spoofed" verdicts on the remaining
            # requests are suspect too (the logged address may not be the client at all).
            w.append({"code": "proxy_unresolved", "site": site, "count": un,
                      "share": round(un / max(r["lines"]["parsed"], 1), 4), "spoofed_unreliable": True})
        lines = r["lines"]
        if lines["total"] and lines["unparsed"] / lines["total"] > 0.05:
            w.append({"code": "unparsed_lines", "site": site, "count": lines["unparsed"],
                      "share": round(lines["unparsed"] / lines["total"], 4)})
        if r["coverage"] is None:
            w.append({"code": "no_sitemap", "site": site})
        if r["robots"] is not None and not r["robots"]["found"]:
            w.append({"code": "no_robots", "site": site})
    missing = [u for u, s in getattr(verifier, "range_status", {}).items() if s == "missing"]
    if getattr(verifier, "offline", False):
        w.append({"code": "offline"})
    elif missing:
        w.append({"code": "ranges_missing", "urls": missing})
    return w

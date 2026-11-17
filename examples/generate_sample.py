#!/usr/bin/env python3
"""Generate a realistic synthetic nginx access log (+ robots.txt + sitemap.xml) for demos and tests.

IPs for real crawlers are taken from the operators' official ranges, so online verification gives real answers.

    python3 examples/generate_sample.py --out /tmp/demo
    python3 skills/ai-crawler-log/scripts/ai-crawler-log.py analyze /tmp/demo/access.log* \
        --site demo-blog.example --sitemap demo-blog.example=/tmp/demo/sitemap.xml \
        --robots demo-blog.example=/tmp/demo/robots.txt -o /tmp/demo/report.html
"""

import argparse
import gzip
import os
import random
from datetime import datetime, timedelta, timezone

SITE = "demo-blog.example"
PAGES = ["/"] + ["/blog/%s/" % s for s in [
    "what-is-geo", "llms-txt-guide", "robots-txt-for-ai", "best-wordpress-cache", "nginx-real-ip-cloudflare",
    "schema-markup-faq", "ai-overviews-traffic", "chatgpt-search-seo", "perplexity-citations", "content-freshness",
    "internal-linking", "core-web-vitals-2026", "image-seo", "hreflang-guide", "log-file-analysis",
    "crawl-budget", "e-e-a-t-checklist", "topic-clusters", "featured-snippets", "local-seo-basics"]] + [
    "/about/", "/contact/", "/pricing/", "/docs/getting-started/", "/docs/api/", "/docs/faq/"]
ASSETS = ["/wp-content/uploads/2026/10/cover.jpg", "/wp-content/themes/x/style.css", "/wp-includes/js/jquery.min.js"]
POPULAR = PAGES[1:8]

CRAWLERS = [
    # (ua, ips, daily_mean, page_pool, status_weights)
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)",
     ["132.196.86.%d" % i for i in range(10, 30)], 60, PAGES, {200: 95, 304: 3, 404: 2}),
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot",
     ["135.234.64.%d" % i for i in range(5, 15)], 18, PAGES, {200: 100}),
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot",
     ["104.210.139.%d" % i for i in range(193, 206)], 9, POPULAR, {200: 100}),
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)",
     ["216.73.216.%d" % i for i in range(20, 60)], 80, PAGES, {200: 97, 404: 3}),
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; +Claude-User@anthropic.com)",
     ["216.73.217.%d" % i for i in range(1, 9)], 3, POPULAR, {200: 100}),
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)",
     ["18.97.1.228", "107.20.236.150", "18.210.92.235"], 14, PAGES, {200: 40, 403: 60}),
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user)",
     ["18.97.43.80", "18.97.43.81", "18.97.43.82"], 4, POPULAR, {200: 100}),
    ("Mozilla/5.0 (Linux; Android 5.0) AppleWebKit/537.36 (KHTML, like Gecko) Mobile Safari/537.36 (compatible; Bytespider; spider-feedback@bytedance.com)",
     ["110.249.201.%d" % i for i in range(1, 50)], 120, PAGES + ASSETS, {200: 90, 429: 10}),
    ("CCBot/2.0 (https://commoncrawl.org/faq/)", ["18.97.9.170", "18.97.14.82"], 6, PAGES, {200: 100}),
    ("meta-externalagent/1.1 (+https://developers.facebook.com/docs/sharing/webmasters/crawler)",
     ["57.141.0.%d" % i for i in range(1, 20)], 25, PAGES, {200: 100}),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15 (Applebot/0.1; +http://www.apple.com/go/applebot)",
     ["17.241.208.%d" % i for i in range(161, 170)], 10, PAGES, {200: 100}),
    ("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", ["66.249.66.1", "66.249.66.2", "66.249.66.3"], 70, PAGES, {200: 97, 304: 3}),
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm) Chrome/116.0.1938.76 Safari/537.36",
     ["157.55.39.%d" % i for i in range(1, 20)], 30, PAGES, {200: 100}),
    # spoofers: claim to be GPTBot / ClaudeBot from random hosting IPs
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)",
     ["45.140.17.%d" % i for i in range(2, 6)], 15, PAGES, {200: 100}),
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)",
     ["91.92.243.7"], 8, PAGES, {200: 100}),
]
HUMAN_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]
REFERERS = ["-"] * 30 + ["https://www.google.com/"] * 40 + ["https://www.bing.com/"] * 5 + [
    "https://chatgpt.com/"] * 4 + ["https://www.perplexity.ai/"] * 2 + ["https://claude.ai/"] + ["https://gemini.google.com/"] + [
    "https://copilot.microsoft.com/"]


def fmt(ip, _ts, method, path, status, size, ref, ua):
    """Line template; the timestamp is filled in after sorting."""
    return '%s - - [None] "%s %s HTTP/1.1" %d %d "%s" "%s"\n' % (ip, method, path, status, size, ref, ua)


def pick_status(rng, weights):
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def generate(out, days, seed):
    rng = random.Random(seed)
    tz = timezone(timedelta(hours=8))
    end = datetime(2026, 11, 16, tzinfo=tz)
    start = end - timedelta(days=days)
    lines = []
    for d in range(days):
        day = start + timedelta(days=d)
        growth = 1 + d / days  # AI traffic grows over the month
        for ua, ips, mean, pool, sw in CRAWLERS:
            n = max(0, int(rng.gauss(mean * (growth if "User" in ua or "Search" in ua else 1), mean * 0.2)))
            if rng.random() < 0.2:
                lines.append((day + timedelta(seconds=rng.randrange(86400)), fmt(rng.choice(ips), None, "GET", "/robots.txt", 200, 300, "-", ua)))
            if "GPTBot" in ua and rng.random() < 0.15 and not ips[0].startswith("45."):
                lines.append((day + timedelta(seconds=rng.randrange(86400)), fmt(rng.choice(ips), None, "GET", "/llms.txt", 404, 0, "-", ua)))
            for _ in range(n):
                path = rng.choice(pool)
                if "Bytespider" in ua and rng.random() < 0.1:
                    path = "/wp-admin/admin-ajax.php"
                lines.append((day + timedelta(seconds=rng.randrange(86400)),
                              fmt(rng.choice(ips), None, "GET", path, pick_status(rng, sw), rng.randrange(3000, 90000), "-", ua)))
        for _ in range(int(rng.gauss(900, 80))):
            ref = rng.choice(REFERERS)
            path = rng.choice(POPULAR if ref != "-" and "google" not in ref else PAGES)
            if ref == "https://chatgpt.com/" and rng.random() < 0.5:
                ref, path = "-", path + "?utm_source=chatgpt.com"
            ip = "%d.%d.%d.%d" % (rng.randrange(1, 223), rng.randrange(256), rng.randrange(256), rng.randrange(1, 255))
            ts = day + timedelta(seconds=rng.randrange(86400))
            ua = rng.choice(HUMAN_UAS)
            lines.append((ts, fmt(ip, None, "GET", path, 200, rng.randrange(8000, 60000), ref, ua)))
            for a in ASSETS[:2]:
                lines.append((ts + timedelta(seconds=1), fmt(ip, None, "GET", a, 200, 20000, "https://%s%s" % (SITE, path), ua)))
    lines.sort(key=lambda x: x[0])
    rendered = [line.replace("[None]", "[%s]" % ts.strftime("%d/%b/%Y:%H:%M:%S %z"), 1) for ts, line in lines]
    os.makedirs(out, exist_ok=True)
    half = len(rendered) // 2
    with gzip.open(os.path.join(out, "access.log.1.gz"), "wt") as f:
        f.writelines(rendered[:half])
    with open(os.path.join(out, "access.log"), "w") as f:
        f.writelines(rendered[half:])
    with open(os.path.join(out, "robots.txt"), "w") as f:
        f.write("User-agent: *\nDisallow: /wp-admin/\nAllow: /wp-admin/admin-ajax.php\n\n"
                "User-agent: Bytespider\nDisallow: /\n\n"
                "User-agent: Google-Extended\nDisallow: /docs/\n\n"
                "Sitemap: https://%s/sitemap.xml\n" % SITE)
    with open(os.path.join(out, "sitemap.xml"), "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for p in PAGES + ["/blog/old-post-%d/" % i for i in range(1, 13)]:
            f.write("  <url><loc>https://%s%s</loc></url>\n" % (SITE, p))
        f.write("</urlset>\n")
    return len(rendered)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="sample")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    n = generate(a.out, a.days, a.seed)
    print("wrote %d lines to %s/access.log{,.1.gz} plus robots.txt and sitemap.xml" % (n, a.out))


if __name__ == "__main__":
    main()

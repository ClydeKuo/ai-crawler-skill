---
name: ai-crawler-log
description: Use when someone wants to know which AI crawlers or bots (GPTBot, ClaudeBot, PerplexityBot, ChatGPT-User, Bytespider, Google-Extended, etc.) visit or read their website, whether those bots are genuine or spoofed, which pages AI reads or never reads, whether AI products send them traffic, or wants a GEO / AI-visibility report from nginx, Apache, JSON, or Cloudflare access logs.
---

# ai-crawler-log

## Overview

A bundled, stdlib-only Python tool turns raw access logs into a self-contained HTML report (+ JSON/CSV): AI crawlers by purpose, verification against official IP ranges and FCrDNS, user-triggered AI fetches, AI referral traffic, sitemap pages never read by AI, 403/429 blocking, robots.txt policy and violations, llms.txt.

**Run the tool instead of hand-rolling grep/regex/Python.** Hand-rolled analyses take minutes, skip sitemap coverage and robots.txt compliance, and disagree with each other on which operators publish IP ranges. The tool already knows the sources: OpenAI, Anthropic (`claude.com/crawling/bots.json`), Perplexity, Google, Apple, Bing, Common Crawl, DuckDuckGo, and Mistral.

## Steps

1. **Find the logs.** Typical locations are `/var/log/nginx/access.log*`, `/var/log/apache2/access.log*`, `/var/log/httpd/*access*`, and per-vhost files. On cPanel/Plesk check `~/logs/` and `/var/www/vhosts/*/logs/`. Rotated `.gz` files are fine. Run `head -3` on one file to see the format and whether lines carry a host.
2. **Know the site domain.** If the log lines carry no host, pass `--site example.com`; the tool needs it to fetch robots.txt, the sitemap, and llms.txt. For several sites in separate files, pass `--log site=path` once per site.
3. **Run the tool** (`SKILL_DIR` is this skill's directory):
   ```bash
   python3 SKILL_DIR/scripts/ai-crawler-log.py analyze LOGS... --site example.com \
       -o ai-crawler-report.html --json ai-crawler.json --csv-dir ai-crawler-csv
   ```
   - Pass `--sitemap site=FILE|URL` and `--robots site=FILE|URL` when the site is not publicly reachable or uses a non-standard sitemap location.
   - `--offline` means no network at all. Every verifiable crawler then shows as `unknown`, so say so when you report.
   - `--lang en` gives an English report; the default is Chinese.
   - `--since/--until YYYY-MM-DD` limits the date window.
4. **Read the results.** The summary goes to stderr. For exact numbers, read `ai-crawler.json` (`sites.<site>.bots`, `categories`, `referrals`, `coverage`, `robots`, `spoofed`, and top-level `warnings`). Do not re-derive numbers with your own scripts.
5. **Answer in this shape.** Lead with the user's actual question, then:
   1. **Warnings that change the meaning of the numbers.** Report these first (see the table below).
   2. **User-triggered AI fetches.** Give the count, which AI products, and which pages. This is the closest signal to "AI cites me".
   3. **AI search and training crawlers.** Give the top crawlers and the trend. Note how many days the log covers; under 14 days, a "trend" is only noise.
   4. **AI referral visits** and the crawls-per-referral ratio per operator.
   5. **Pages never read by AI**, compared with Googlebot coverage.
   6. **Fixes, ranked.** Cover accidental 403/429s on search or user-triggered bots, spoofed IPs to block, robots.txt lines, llms.txt, and the nginx real_ip setup.
   7. **The report path.**

## Warnings that change the meaning

| `warnings[].code` | What to tell the user |
|---|---|
| `proxy_unresolved` | The log records CDN (Cloudflare) IPs, so verification is impossible for those requests, and **the spoofed counts are unreliable**. Give the nginx `set_real_ip_from` + `real_ip_header CF-Connecting-IP` fix. Do not recommend blocking "spoofed" IPs from this run. |
| `offline` / `ranges_missing` | Verification did not run fully, so `unknown` does not mean fake. |
| `no_sitemap` / `no_robots` | Coverage or robots.txt checks are missing. Rerun with `--sitemap` / `--robots`. |
| `unparsed_lines` | The log format is custom. Show the user one unparsed line and ask for their `log_format`. |

## Quick reference

| Fact | Consequence |
|---|---|
| `Google-Extended` and `Applebot-Extended` are robots.txt tokens, not crawlers | They never appear in logs. Googlebot and Applebot do the fetching. Answer "0 in logs, by design" and point to the robots.txt section. |
| Categories: `user` > `search` > `training` for GEO value | Never recommend blocking `user` or `search` bots to save bandwidth. Blocking training bots is a policy choice, not a fix. |
| Verification states | `verified` = official IP range or FCrDNS match. `unverifiable` = the operator publishes nothing (e.g. Bytespider, Meta), so this is not evidence of fakery. `unknown` = could not check. `spoofed` = checked and failed; excluded from all counts. |
| Origin logs miss CDN cache hits | Crawler counts are a lower bound when HTML is cached at the edge. |
| robots.txt violations use today's robots.txt | If the rules changed during the log window, violations may be stale. |
| New or long-tail crawlers | Run `python3 SKILL_DIR/scripts/ai-crawler-log.py update-bots` to import ai-robots-txt/ai.robots.txt. Run `... bots` to list what is known. |

## Common mistakes

- **Treating a short window as a trend.** One week shows day-to-day noise; say how many days the log covers.
- **Calling `unverifiable` "fake".** Only `spoofed` is evidence. Bytespider and Meta cannot be verified by anyone.
- **Sending IPs to third-party lookup sites** (ipinfo, whois APIs) to "verify" a crawler. The tool's official-range and FCrDNS checks are the evidence. Never send human visitor IPs anywhere.
- **Recommending IP blocks while `proxy_unresolved` is present.** The logged IPs belong to the CDN, not the visitor.

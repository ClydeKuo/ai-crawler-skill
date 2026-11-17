# ai-crawler-log

**See which AI crawlers read your website — from your raw access logs.**
GA and other JS analytics never see crawlers. Your server logs do.

[中文说明](#中文说明)

```bash
python3 skills/ai-crawler-log/scripts/ai-crawler-log.py analyze /var/log/nginx/access.log* -o report.html
```

One self-contained HTML report (no external assets), plus optional JSON and CSV.

## What it answers

| Question | How |
|---|---|
| Which AI crawlers came, how often, trending up? | 60+ curated crawlers grouped by **purpose**: user-triggered fetch, AI search index, training, agent; Googlebot/Bingbot shown as a baseline |
| Are they real? | Official IP ranges (OpenAI, Anthropic, Perplexity, Google, Apple, Bing, Common Crawl, DuckDuckGo, Mistral) + forward-confirmed reverse DNS. Four states: verified / unverifiable / unknown / **spoofed** (excluded from counts) |
| Is AI actually *using* my content? | **User-triggered fetches** (ChatGPT-User, Claude-User, Perplexity-User…) — someone asked an AI and it read your page live |
| Is AI sending me visitors? | Human visits with Referer / `utm_source` from ChatGPT, Perplexity, Claude, Gemini, Copilot, DeepSeek, Kimi, Doubao… and the **crawl-to-referral ratio** per operator |
| What do they read, what do they never read? | Top pages per purpose; sitemap pages never fetched by any AI (vs Googlebot coverage) |
| Am I blocking AI by accident? | 403/429 share per crawler (WAF / rate limits), robots.txt policy per crawler (RFC 9309 matcher with `*`/`$`), robots.txt violations, llms.txt presence and fetches |

> `Google-Extended` and `Applebot-Extended` are robots.txt **policy tokens**, not crawlers. They never appear in logs — Googlebot/Applebot do the fetching. The report shows them in the robots.txt section only.

## Install

Python ≥ 3.9, standard library only.

```bash
pip install .                      # provides the `ai-crawler-log` command
# or run without installing:
python3 skills/ai-crawler-log/scripts/ai-crawler-log.py --help
```

As a Claude Code plugin / skill: this repo is a plugin (`.claude-plugin/plugin.json`) with the skill in `skills/ai-crawler-log/`. Or copy `skills/ai-crawler-log/` into `~/.claude/skills/`.

## Usage

```bash
# one site, rotated + gzipped logs
ai-crawler-log analyze /var/log/nginx/access.log* --site example.com -o report.html

# many sites: vhost-style logs are split automatically by host; or map files to sites
ai-crawler-log analyze --log blog.example.com=/var/log/nginx/blog.access.log* \
                       --log shop.example.com=/var/log/nginx/shop.access.log* -o all.html

# Cloudflare Logpush (NDJSON) works the same
ai-crawler-log analyze logpush/*.log.gz -o report.html

# extra outputs, English report, date window
ai-crawler-log analyze access.log* --json out.json --csv-dir csv/ --lang en --since 2026-10-01

# refresh the long-tail crawler list from ai-robots-txt/ai.robots.txt
ai-crawler-log update-bots
ai-crawler-log bots
```

Key options:

| Option | Meaning |
|---|---|
| `--site NAME` | Site for logs without a host field (needed to fetch robots.txt / sitemap / llms.txt) |
| `--sitemap SITE=URL\|FILE`, `--robots SITE=URL\|FILE` | Override auto-discovery |
| `--trusted-proxy CIDR` | Extra reverse proxies whose `X-Forwarded-For` is trusted (Cloudflare is built in; `--no-cloudflare` disables) |
| `--offline` | No network: no IP-range download, DNS, or site fetches (uses cache if present) |
| `--no-dns` / `--no-site-fetch` | Skip only reverse DNS / only robots-sitemap-llms fetching |
| `--keep-query` | Treat `?query` variants as different pages (tracking params are always dropped) |

### Supported log formats (auto-detected per line)

- nginx / Apache **combined** and common, with optional leading vhost (`%v:%p` / `$host`) and extra quoted fields (e.g. `"$http_x_forwarded_for"`)
- JSON lines (nginx `escape=json`, Caddy-like, custom) with common key names
- Cloudflare **Logpush** HTTP requests (`ClientIP`, `ClientRequestURI`, `EdgeStartTimestamp`, …)
- plain or `.gz`, files / globs / directories / stdin (`-`)

### Behind Cloudflare or another CDN?

If nginx logs the CDN's IP instead of the visitor's, no crawler can be verified. The tool restores the real IP from `X-Forwarded-For` when present, and otherwise warns loudly. Fix it at the source:

```nginx
# one set_real_ip_from per range in https://www.cloudflare.com/ips-v4 and /ips-v6
set_real_ip_from 173.245.48.0/20;
# ...
real_ip_header CF-Connecting-IP;
```

Also remember that CDN cache hits never reach the origin, so origin logs undercount crawler traffic.

## Privacy

Human visitor IPs are never written to the report, JSON, or CSV. Only crawler IPs (and spoofer IPs) appear.

## Development

```bash
python3 -m unittest discover -s tests -t .
python3 examples/generate_sample.py --out /tmp/demo     # synthetic 30-day log using real crawler IP ranges
```

Layout: `skills/ai-crawler-log/scripts/ai_crawler_log/` (package), `data/bots.json` (curated crawler list, edit to add bots), `tests/`, `docs/design.md`.

---

## 中文说明

**从服务器原始日志里看清哪些 AI 爬虫在读你的网站。** GA 这类基于 JS 的统计工具看不到爬虫，服务器日志可以。

- 识别 60+ 个 AI 爬虫，按 **用途** 分类：用户实时触发、AI 搜索索引、训练采集、AI Agent；Googlebot / Bingbot 作为对照基线。
- **真伪校验**：比对官方 IP 段，再用正反向 DNS 双重校验（FCrDNS）。结果分四态：已验证 / 无法验证 / 未知 / 伪装，伪装的请求不计入统计。
- **AI 有没有真的在用你的内容**：统计用户触发的抓取（ChatGPT-User、Claude-User、Perplexity-User 等）。
- **AI 带来的真人流量**：识别来自 ChatGPT、Perplexity、Claude、Gemini、Copilot、DeepSeek、Kimi、豆包等的 Referer 和 utm_source，计算各家 AI 的“抓取 / 引流比”。
- **最常被抓的页面**，以及 sitemap 中**从没被 AI 抓过的页面**。
- **有没有误挡 AI**：403/429 比例、robots.txt 策略（按 RFC 9309 实现）、是否违规抓取、llms.txt 是否存在以及有没有被读取。
- 输出单文件 HTML 报告（中/英文，支持深色模式），可同时导出 JSON 和 CSV。

```bash
python3 skills/ai-crawler-log/scripts/ai-crawler-log.py analyze /var/log/nginx/access.log* --site example.com -o report.html
```

注意：`Google-Extended` 只是写在 robots.txt 里的标记，不是爬虫，日志里永远不会出现。网站接了 Cloudflare 时，nginx 必须配置 `real_ip`，否则日志里全是 CDN 的 IP，无法校验爬虫真伪。

## License

MIT

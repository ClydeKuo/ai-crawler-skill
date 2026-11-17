# ai-crawler-log 设计

## 目标

输入 nginx / Apache / JSON / Cloudflare Logpush 访问日志，回答做 GEO 的人最关心的问题：

1. 哪些 AI 爬虫来了、来了多少次、趋势如何（按 **用途** 分类，而不仅是按厂商）。
2. 哪些是真的、哪些是伪装 UA（官方 IP 段 + FCrDNS 校验，结果分四态）。
3. 读了哪些页面、哪些页面从没被读过（对比 sitemap）。
4. AI 真的“用”了我的内容吗：用户触发型抓取（ChatGPT-User 等）+ 来自 AI 产品的真人引流（Referer / utm_source）。
5. 有没有把 AI 挡在门外：403/429 比例、robots.txt 策略、爬虫是否遵守 robots.txt、llms.txt 是否存在/被读取。

输出：自包含单文件 HTML 报告（无外部依赖、内联 SVG 图表）+ JSON + CSV。

## 形态

- 纯 Python 标准库 CLI（`python3 scripts/ai-crawler-log.py` 或 `pip install` 后 `ai-crawler-log`）。
- 外面包一层 Claude skill（`skills/ai-crawler-log/SKILL.md`）：负责定位日志、判断格式、检查反代真实 IP 配置、跑脚本、解读结果并给出 robots.txt / WAF 建议。
- 仓库同时是一个 Claude Code plugin（`.claude-plugin/plugin.json`）。

## 爬虫分类

| category | 含义 |
|---|---|
| `user` | 用户实时触发的抓取（ChatGPT-User、Claude-User、Perplexity-User…），最接近“被 AI 引用” |
| `search` | AI 搜索索引（OAI-SearchBot、Claude-SearchBot、PerplexityBot…） |
| `training` | 训练数据采集（GPTBot、ClaudeBot、CCBot、Bytespider…） |
| `agent` | 代用户操作网页的 AI agent（ChatGPT Agent、Google-Agent…） |
| `other-ai` | 其他 AI 相关（从 ai.robots.txt 导入、用途不明） |
| `classic-search` | 传统搜索引擎（Googlebot、Bingbot），作为对照基线 |

`Google-Extended`、`Applebot-Extended` 等是 **robots.txt 策略标记**，不会出现在日志 UA 里，只在 robots.txt 检查中出现。

## 校验四态

| 状态 | 条件 |
|---|---|
| `verified` | IP 命中官方 IP 段，或 FCrDNS 主机名后缀匹配 |
| `spoofed` | 有可用校验方法，全部执行且全部不通过 |
| `unverifiable` | 该爬虫没有公开校验方法 |
| `unknown` | 校验方法存在但无法执行（离线 / 下载失败 / DNS 失败 / IP 是 CDN 反代 IP） |

反代：若 remote IP 属于 Cloudflare（或 `--trusted-proxy`）且日志带 X-Forwarded-For，则取 XFF 中最右侧非可信 IP；否则记为“反代 IP”，校验为 `unknown`，并在报告顶部给出 nginx `real_ip` 配置告警。

## 模块

| 模块 | 职责 |
|---|---|
| `bots.py` | 加载 `data/bots.json` + 可选 ai.robots.txt 导入数据；UA 匹配 |
| `parsers.py` | 多格式解析、gzip、真实 IP 还原 |
| `urls.py` | URL 规范化、路径类型（page/asset/feed/special/admin） |
| `referrals.py` | AI 产品引流识别 |
| `verify.py` | IP 段下载缓存、FCrDNS、四态判定 |
| `sitefiles.py` | sitemap / robots.txt / llms.txt 获取与解析 |
| `analyze.py` | 单遍流式聚合（多站点 + 全部汇总） |
| `report.py` | HTML 报告（中/英） |
| `export.py` | JSON / CSV |
| `cli.py` | 命令行 |

## 不做

- 不存储/展示真人访客 IP。
- 不做实时监控，只做离线日志分析。

"""Render the self-contained HTML report (data embedded as JSON, rendered client-side with textContent only)."""

import html
import json
import os

from .bots import DATA_DIR


def _safe_json(data):
    # Keep the JSON inert inside <script>: log-derived strings (URLs, UAs) are attacker-controlled.
    return (json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def render_html(result, lang="zh"):
    with open(os.path.join(DATA_DIR, "report_template.html"), encoding="utf-8") as f:
        tpl = f.read()
    sites = list(result.get("sites", {}))
    name = "all sites" if len(sites) > 1 else (sites[0] if sites else "")
    title = ("AI 爬虫访问报告 · " if lang.startswith("zh") else "AI crawler report · ") + name
    return (tpl.replace("__LANG__", "zh-CN" if lang.startswith("zh") else "en")
               .replace("__TITLE__", html.escape(title))
               .replace("__DATA__", _safe_json(result)))

"""AI crawler registry: curated data/bots.json + optional entries imported from ai.robots.txt."""

import json
import os
import re
from dataclasses import dataclass, field

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

CATEGORIES = ["user", "search", "training", "agent", "other-ai", "classic-search"]
AI_CATEGORIES = ["user", "search", "training", "agent", "other-ai"]

# Names in ai.robots.txt that are too generic to match safely as UA substrings.
GENERIC_NAMES = {
    "spider", "code", "dot", "muse", "scrapy", "cursor", "operator", "openai", "lcc", "yak",
    "instinct", "trae", "devin", "codex", "opencode", "andibot", "anomura", "terra cotta",
    "terracotta", "brightbot 1.0", "iaskspider/2.0", "mistralai-user/1.0", "lightpanda",
}

FUNCTION_TO_CATEGORY = [
    ("assistant", "user"),
    ("agent", "agent"),
    ("search", "search"),
    ("train", "training"),
    ("scrap", "training"),
    ("data provider", "training"),
    ("dataset", "training"),
]


@dataclass
class Bot:
    name: str
    operator: str
    category: str
    ua: list = field(default_factory=list)
    ip_ranges: list = field(default_factory=list)
    rdns: list = field(default_factory=list)
    robots_token: str = ""
    note: str = ""
    source: str = "curated"

    @property
    def verifiable(self):
        return bool(self.ip_ranges or self.rdns)


def _token_regex(token):
    return r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])"


class BotRegistry:
    def __init__(self, bots, policy_tokens, referrals):
        self.bots = bots
        self.policy_tokens = policy_tokens
        self.referrals = referrals
        self._by_name = {b.name: b for b in bots}
        alternatives = []
        self._group_to_bot = {}
        self._priority = {b.name: i for i, b in enumerate(bots)}
        for i, b in enumerate(bots):
            group = "b%d" % i
            self._group_to_bot[group] = b
            alternatives.append("(?P<%s>%s)" % (group, "|".join(_token_regex(t) for t in b.ua)))
        self._re = re.compile("|".join(alternatives), re.IGNORECASE) if alternatives else None
        self._cache = {}

    @classmethod
    def load(cls, path=None, extra=None):
        with open(path or os.path.join(DATA_DIR, "bots.json"), encoding="utf-8") as f:
            data = json.load(f)
        bots = [cls._bot_from_dict(d, "curated") for d in data["bots"]]
        policy = list(data.get("policy_tokens", []))
        if extra:
            known = {t.lower() for b in bots for t in b.ua}
            for d in extra.get("bots", []):
                if d["name"].lower() not in known:
                    bots.append(cls._bot_from_dict(d, "ai.robots.txt"))
            known_policy = {p["token"].lower() for p in policy}
            policy += [p for p in extra.get("policy_tokens", []) if p["token"].lower() not in known_policy]
        return cls(bots, policy, data.get("referrals", []))

    @staticmethod
    def _bot_from_dict(d, source):
        v = d.get("verify", {})
        return Bot(
            name=d["name"],
            operator=d.get("operator", ""),
            category=d.get("category", "other-ai"),
            ua=list(d.get("ua") or [d["name"]]),
            ip_ranges=list(v.get("ip_ranges", [])),
            rdns=[s.lower().lstrip(".") for s in v.get("rdns", [])],
            robots_token=d.get("robots_token", d["name"]),
            note=d.get("note", ""),
            source=source,
        )

    def get(self, name):
        return self._by_name.get(name)

    def match(self, ua):
        """Return the Bot whose token appears in the User-Agent (earliest-listed bot wins)."""
        if not ua or ua == "-" or self._re is None:
            return None
        if ua in self._cache:
            return self._cache[ua]
        best = None
        for m in self._re.finditer(ua):
            bot = self._group_to_bot[m.lastgroup]
            if best is None or self._priority[bot.name] < self._priority[best.name]:
                best = bot
        if len(self._cache) < 100000:
            self._cache[ua] = best
        return best

    @staticmethod
    def clean_operator(text):
        """ai.robots.txt operators are free text / markdown; reduce to a short name."""
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text or "").strip()
        if text.lower().startswith(("unclear", "not applicable", "n/a", "unknown")):
            return ""
        text = re.split(r"\s*\(|\s+that\s|\s+which\s|[,;.]\s", text, maxsplit=1)[0].strip()
        return text[:40]

    @staticmethod
    def convert_ai_robots_txt(raw, existing=None):
        """Convert ai.robots.txt robots.json into our extra-bots format."""
        known = set()
        if existing is not None:
            known = {t.lower() for b in existing.bots for t in b.ua}
            known |= {p["token"].lower() for p in existing.policy_tokens}
        bots, policy = [], []
        for name, info in raw.items():
            low = name.lower()
            if name.startswith("__") or low in known or low in GENERIC_NAMES:
                continue
            if low.endswith("-extended"):
                policy.append({"token": name, "operator": info.get("operator", ""), "meaning": "robots.txt policy token"})
                continue
            func = (info.get("function") or "").lower()
            category = "other-ai"
            for needle, cat in FUNCTION_TO_CATEGORY:
                if needle in func:
                    category = cat
                    break
            bots.append({"name": name, "operator": BotRegistry.clean_operator(info.get("operator", "")), "category": category})
        return {"bots": bots, "policy_tokens": policy}

"""JSON and CSV exports."""

import csv
import json
import os


def write_json(result, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)


def write_csvs(result, directory):
    os.makedirs(directory, exist_ok=True)
    written = []

    def w(name, header, rows):
        p = os.path.join(directory, name)
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            cw = csv.writer(f)
            cw.writerow(header)
            cw.writerows(rows)
        written.append(p)

    sites = result["sites"]
    w("bots.csv", ["site", "bot", "operator", "category", "requests", "unique_pages", "verified", "unverifiable", "unknown",
                   "spoofed", "status_403", "status_429", "robots_txt_fetches", "llms_txt_fetches", "robots_violations",
                   "first_seen", "last_seen"],
      [[s, n, b["operator"], b["category"], b["requests"], b["unique_pages"], *(b["verification"][k] for k in
        ("verified", "unverifiable", "unknown", "spoofed")), b["status"].get("403", 0), b["status"].get("429", 0),
        b["robots_txt_fetches"], b["llms_txt_fetches"], b["violations"], b["first_seen"], b["last_seen"]]
       for s, r in sites.items() for n, b in r["bots"].items()])
    w("bot_daily.csv", ["site", "date", "bot", "category", "requests"],
      [[s, d, n, b["category"], c] for s, r in sites.items() for n, b in r["bots"].items() for d, c in b["daily"].items()])
    w("top_pages.csv", ["site", "category", "path", "requests"],
      [[s, cat, p["path"], p["requests"]] for s, r in sites.items() for cat, ps in r["top_pages"].items() for p in ps])
    w("never_crawled.csv", ["site", "path"],
      [[s, p] for s, r in sites.items() if r["coverage"] for p in r["coverage"]["never_crawled"]])
    w("referrals.csv", ["site", "source", "operator", "date", "visits"],
      [[s, src, v["operator"], d, n] for s, r in sites.items() for src, v in r["referrals"]["by_source"].items()
       for d, n in v["daily"].items()])
    w("operators.csv", ["site", "operator", "crawls", "user_fetches", "referrals", "crawls_per_referral"],
      [[s, o["operator"], o["crawls"], o["user_fetches"], o["referrals"], o["crawls_per_referral"]]
       for s, r in sites.items() for o in r["operators"]])
    w("spoofed_ips.csv", ["site", "ip", "bot", "requests"],
      [[s, x["ip"], x["bot"], x["requests"]] for s, r in sites.items() for x in r["spoofed"]["top_ips"]])
    return written

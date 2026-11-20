"""Build examples/sample-report.{md,html} from synthetic data, through the real pipeline, with no network.

    python3 scripts/make_sample.py

A fake client stands in for looot and answers six weekly runs for a made-up site, so the charts have
history. Nothing here calls the API or spends money.
"""

import datetime as dt
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from seo_monitor.monitor import check_and_write  # noqa: E402

DOMAIN = "example.com"
RIVALS = ["rival-one.example", "rival-two.example"]
KEYWORDS = ["crm for startups", "best crm for small teams", "crm with email tracking", "free crm",
            "crm pipeline template", "sales crm api"]
PRICES = {"google.serp.organic": 0.0009, "google.serp.ai-overview": 0.0018, "search.chatgpt": 0.004,
          "google.keywords.volume": 0.09}


class FakeLooot:
    has_token = True

    def __init__(self, week):
        self.week = week
        self.rng = random.Random(week)

    def jobs(self):
        return [{"id": k, "cheapestPerCall": v} for k, v in PRICES.items()]

    def balance(self):
        return {"available": 12.0, "reserved": 0}

    def _pos(self, kw, who):
        base = {DOMAIN: 12, RIVALS[0]: 3, RIVALS[1]: 6}[who] + (sum(map(ord, kw)) % 5) - 2
        trend = -self.week if who == DOMAIN else self.week // 3
        return max(1, base + trend + self.rng.choice((-1, 0, 0, 1)))

    def run_job(self, job, payload, wait=30, max_cost=None, day=""):
        cost = PRICES[job]
        if job == "google.serp.organic":
            kw = payload["query"]
            hits = {self._pos(kw, d): d for d in [RIVALS[1], RIVALS[0], DOMAIN]}
            rows = []
            filler = iter(["reviews-hub.example", "forum.example", "software-list.example", "news-site.example",
                           "wiki.example", "video.example", "blog-network.example", "qa-site.example",
                           "directory.example", "guide-site.example", "deals.example", "tech-mag.example"])
            for pos in range(1, 11):
                host = hits.get(pos) or next(filler)
                rows.append({"position": pos, "link": f"https://{host}/{kw.replace(' ', '-')}", "title": kw})
            result = {"output": {"data": {"results": rows}}}
        elif job == "google.serp.ai-overview":
            cited = self.week >= 3 and len(payload["prompt"]) % 2 == 0
            result = {"output": {"data": {"answer": "Rival-one is a common pick." + (" Example also fits." if self.week >= 2 else ""),
                                          "citations": [{"url": "https://docs.example.com/x"}] if cited else [{"url": "https://rival-one.example/a"}]}}}
        elif job == "search.chatgpt":
            named = self.week >= 4 and "crm" in payload["q"] and len(payload["q"]) % 3 != 0
            result = {"markdown": "Options: Rival-two, Rival-one" + (", Example" if named else "") + ".", "reference_links": []}
        else:
            result = {"tasks": [{"result": [{"keyword": k, "search_volume": v, "cpc": c} for k, v, c in
                                            zip(payload["keywords"], (2400, 1300, 590, 9900, 320, 210), (6.1, 7.4, 5.2, 3.9, 2.8, 8.6))]}]}
        return {"status": "completed", "actualCost": cost, "result": result}


def main():
    here = os.path.join(os.path.dirname(__file__), "..", "examples")
    start = dt.date(2026, 10, 9)
    with tempfile.TemporaryDirectory() as d:
        hist = os.path.join(d, "rankings.json")
        for week in range(6):
            last = week == 5
            surfaces = ["rank", "ai_overview", "chatgpt"] + (["volume"] if last else [])
            check_and_write(
                FakeLooot(week), DOMAIN, KEYWORDS, surfaces, 0.50, competitors=RIVALS,
                md_path=os.path.join(here, "sample-report.md") if last else None,
                html_path=os.path.join(here, "sample-report.html") if last else None,
                history_path=hist, today=(start + dt.timedelta(weeks=week)).isoformat(),
            )
    print("Wrote examples/sample-report.md and examples/sample-report.html")


if __name__ == "__main__":
    main()

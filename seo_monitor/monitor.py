"""Rank lookup, history and the markdown report."""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from .client import Looot

JOB = "google.serp.organic"


def clean_domain(raw: str) -> str:
    d = raw.strip().lower()
    for prefix in ("https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    if d.startswith("www."):
        d = d[4:]
    return d.split("/")[0].split("?")[0].split("#")[0]


def parse_keywords(text: str) -> List[str]:
    seen: List[str] = []
    for line in text.splitlines():
        k = line.strip()
        if k and not k.startswith("#") and k not in seen:
            seen.append(k)
    return seen


def _host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def extract_organic(result: Any, depth: int = 0) -> List[Dict[str, Any]]:
    """First list of result-like dicts (a link plus a title) anywhere in a SERP answer."""
    if depth > 5 or not isinstance(result, (dict, list)):
        return []
    if isinstance(result, list):
        rows = [r for r in result if isinstance(r, dict) and (r.get("link") or r.get("url"))]
        if rows:
            return rows
        for item in result:
            nested = extract_organic(item, depth + 1)
            if nested:
                return nested
        return []
    # Prefer a key that is literally called organic.
    for key in ("organic", "organic_results", "organicResults", "results", "items"):
        if key in result:
            nested = extract_organic(result[key], depth + 1)
            if nested:
                return nested
    for value in result.values():
        nested = extract_organic(value, depth + 1)
        if nested:
            return nested
    return []


def find_rank(result: Any, domain: str) -> Tuple[Optional[int], str]:
    """Position (1-based) and URL of the first result on `domain` or a subdomain, else (None, '')."""
    rows = extract_organic(result)
    for index, row in enumerate(rows, start=1):
        url = str(row.get("link") or row.get("url") or "")
        host = _host(url)
        if host == domain or host.endswith("." + domain):
            pos = row.get("position") or row.get("rank") or row.get("rank_absolute")
            return (int(pos) if isinstance(pos, (int, float)) else index), url
    return None, ""


def dry_run(client: Looot, domain: str, keywords: List[str]) -> List[str]:
    """Only free routes: the keyless job overview, plus balance and search when a token is set."""
    lines = ["Dry run. Nothing is spent."]
    job = next((j for j in client.jobs() if j.get("id") == JOB), None)
    price = (job or {}).get("cheapestPerCall")
    if price is None:
        lines.append(f"job:{JOB}: price not listed")
    else:
        lines.append(f"job:{JOB}: cheapest listed price ${price:.4f} per keyword ({(job or {}).get('providerCount', 0)} providers)")
        lines.append(f"{len(keywords)} keyword(s) for {domain}: about ${price * len(keywords):.4f} at the cheapest provider.")
    if client.has_token:
        b = client.balance()
        lines.append(f"Balance: ${b.get('available', 0):.2f} available, ${b.get('reserved', 0):.2f} reserved.")
        found = client.search("google search results for a keyword", 3)
        lines.append(f"Catalog search works ({len(found.get('endpoints', []))} rows returned).")
    else:
        lines.append("No LOOOT_TOKEN set, so balance and catalog search were skipped.")
    return lines


def check_rankings(
    client: Looot, domain: str, keywords: Iterable[str], country: Optional[str], max_cost: float, log=lambda m: None
) -> Dict[str, Any]:
    """Paid. One google.serp.organic run per keyword; stops starting new runs at the cost cap."""
    rows: List[Dict[str, Any]] = []
    spent = 0.0
    capped = False
    for kw in keywords:
        if spent >= max_cost:
            capped = True
            rows.append({"keyword": kw, "position": None, "url": "", "cost": 0.0, "note": "skipped, cost cap reached"})
            continue
        payload: Dict[str, Any] = {"query": kw}
        if country:
            payload["country"] = country
        run = client.run_job(JOB, payload)
        cost = run.get("actualCost") if isinstance(run.get("actualCost"), (int, float)) else 0.0
        spent += cost
        if run.get("status") != "completed":
            msg = (run.get("error") or {}).get("message", run.get("status"))
            log(f"  {kw}: {msg}")
            rows.append({"keyword": kw, "position": None, "url": "", "cost": cost, "note": f"run {run.get('status')}"})
            continue
        pos, url = find_rank(run.get("result"), domain)
        rows.append({"keyword": kw, "position": pos, "url": url, "cost": cost, "note": "" if pos else "not in the results"})
    return {"domain": domain, "date": dt.date.today().isoformat(), "rows": rows, "spent": spent, "capped": capped}


def load_history(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_history(path: str, snapshot: Dict[str, Any]) -> None:
    hist = load_history(path)
    hist[snapshot["date"]] = {r["keyword"]: r["position"] for r in snapshot["rows"]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hist, f, indent=2, sort_keys=True)


def _change(prev: Optional[int], now: Optional[int]) -> str:
    if prev is None and now is None:
        return ""
    if prev is None:
        return "new"
    if now is None:
        return "lost"
    if now == prev:
        return "="
    return f"{'+' if prev > now else '-'}{abs(prev - now)}"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_report(snapshot: Dict[str, Any], previous: Optional[Dict[str, Optional[int]]] = None) -> str:
    previous = previous or {}
    rows = snapshot["rows"]
    ranked = [r for r in rows if r["position"]]
    top10 = [r for r in ranked if r["position"] <= 10]
    out = [
        f"# Google rankings for {snapshot['domain']}",
        "",
        f"Checked {snapshot['date']} through looot (`job:{JOB}`).",
        "",
        f"- Keywords checked: {len(rows)}",
        f"- Ranking in the results: {len(ranked)}",
        f"- In the top 10: {len(top10)}",
        f"- Spent: ${snapshot['spent']:.4f}",
    ]
    if snapshot.get("capped"):
        out.append("- Stopped early at the cost cap. Some keywords were skipped.")
    out += ["", "| Keyword | Position | Change | URL | Note |", "| --- | --- | --- | --- | --- |"]
    for r in sorted(rows, key=lambda r: (r["position"] is None, r["position"] or 0)):
        change = _change(previous.get(r["keyword"]), r["position"]) if previous else ""
        out.append(
            f"| {_cell(r['keyword'])} | {r['position'] or '-'} | {change} | {_cell(r['url'])} | {_cell(r['note'])} |"
        )
    out.append("")
    return "\n".join(out)

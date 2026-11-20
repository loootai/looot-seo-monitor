"""Price the checks for free, then run them under a hard spending cap."""

from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Dict, List, Optional

from .client import Looot
from .extract import (
    CTR_BY_POSITION, ai_answer, ai_status, brand_terms, extract_volume, find_rank, ranked_domains,
)

# Surface -> looot job, and how one keyword becomes the job input.
SURFACES: Dict[str, Dict[str, Any]] = {
    "rank": {"job": "google.serp.organic", "label": "Google rank", "per": "keyword"},
    "ai_overview": {"job": "google.serp.ai-overview", "label": "Google AI Overview", "per": "keyword"},
    "chatgpt": {"job": "search.chatgpt", "label": "ChatGPT answer", "per": "keyword"},
    "volume": {"job": "google.keywords.volume", "label": "Search volume and CPC", "per": "run"},
}
# Used when the free catalog lists no price, or $0 (a free own-key endpoint can pull the minimum to 0),
# so the quote and the cap never assume a check is free. Rank: the paid providers list $0.0009 to $0.004.
FALLBACK_PRICE = {"rank": 0.004, "ai_overview": 0.0056, "chatgpt": 0.004, "volume": 0.09}

Log = Callable[[str], None]


def job_prices(client: Looot) -> Dict[str, Optional[float]]:
    """Cheapest listed price per call for each surface's job, from the free public catalog."""
    listed = {j.get("id"): j.get("cheapestPerCall") for j in client.jobs()}
    return {name: listed.get(s["job"]) for name, s in SURFACES.items()}


def quote(prices: Dict[str, Optional[float]], surfaces: List[str], n_keywords: int) -> Dict[str, Any]:
    """Calls and estimated dollars per surface, at the cheapest listed price."""
    lines = []
    total = 0.0
    for name in surfaces:
        price = prices.get(name)
        unit = price if isinstance(price, (int, float)) and price > 0 else FALLBACK_PRICE[name]
        calls = 1 if SURFACES[name]["per"] == "run" else n_keywords
        cost = unit * calls
        total += cost
        lines.append({"surface": name, "job": SURFACES[name]["job"], "calls": calls, "unit": unit,
                      "listed": isinstance(price, (int, float)) and price > 0, "cost": cost})
    return {"lines": lines, "total": total}


def format_quote(q: Dict[str, Any], max_cost: float) -> List[str]:
    out = ["| Check | looot job | Calls | Price each | Estimate |", "| --- | --- | --- | --- | --- |"]
    for line in q["lines"]:
        note = "" if line["listed"] else " (assumed upper price)"
        out.append(f"| {SURFACES[line['surface']]['label']} | job:{line['job']} | {line['calls']} | "
                   f"${line['unit']:.4f}{note} | ${line['cost']:.4f} |")
    out.append(f"| Total | | | | ${q['total']:.4f} |")
    if q["total"] > max_cost:
        out.append(f"The estimate is above the cap of ${max_cost:.2f}: checks past the cap are skipped, never charged.")
    else:
        out.append(f"Hard cap ${max_cost:.2f}. Each run is sent with fallback.maxCostUsd set to what is left.")
    return out


def _cost(run: Dict[str, Any]) -> float:
    c = run.get("actualCost")
    return float(c) if isinstance(c, (int, float)) and not isinstance(c, bool) else 0.0


def run_checks(
    client: Looot,
    domain: str,
    keywords: List[str],
    surfaces: List[str],
    max_cost: float,
    competitors: Optional[List[str]] = None,
    brands: Optional[List[str]] = None,
    country: Optional[str] = None,
    location: Optional[str] = None,
    prices: Optional[Dict[str, Optional[float]]] = None,
    log: Log = lambda m: None,
    today: Optional[str] = None,
) -> Dict[str, Any]:
    """Paid. Runs every selected surface for every keyword, keyword by keyword, and stops at the cap.

    Before each call the expected price is compared with what is left of the cap; the call is also sent
    with fallback.maxCostUsd equal to what is left, so looot itself refuses to overspend.
    """
    competitors = [c for c in (competitors or []) if c != domain]
    prices = prices if prices is not None else job_prices(client)
    day = today or dt.date.today().isoformat()
    tracked = [domain] + competitors
    terms = {d: brand_terms(d, brands if d == domain else None) for d in tracked}
    spent = 0.0
    capped = False
    costs = {s: 0.0 for s in surfaces}

    def expected(surface: str) -> float:
        p = prices.get(surface)
        return p if isinstance(p, (int, float)) and p > 0 else FALLBACK_PRICE[surface]

    def call(surface: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        nonlocal spent, capped
        left = max_cost - spent
        if left < expected(surface) or left <= 0:
            capped = True
            return None
        run = client.run_job(SURFACES[surface]["job"], payload, max_cost=left, day=day)
        c = _cost(run)
        spent += c
        costs[surface] += c
        if run.get("status") != "completed":
            msg = (run.get("error") or {}).get("message") or run.get("status")
            log(f"  {surface} {payload}: {msg}")
        return run

    rows: List[Dict[str, Any]] = []
    for kw in keywords:
        row: Dict[str, Any] = {"keyword": kw}
        if "rank" in surfaces:
            payload: Dict[str, Any] = {"query": kw}
            if country:
                payload["country"] = country
            if location:
                payload["location"] = location
            run = call("rank", payload)
            if run is None:
                row["rank"] = {"position": None, "url": "", "note": "skipped, cost cap reached", "top": [], "competitors": {}}
            elif run.get("status") != "completed":
                row["rank"] = {"position": None, "url": "", "note": f"run {run.get('status')}", "top": [], "competitors": {}}
            else:
                result = run.get("result")
                pos, url = find_rank(result, domain)
                row["rank"] = {
                    "position": pos, "url": url, "note": "" if pos else "not in the results",
                    "top": [h for _, h in ranked_domains(result)],
                    "competitors": {c: find_rank(result, c)[0] for c in competitors},
                }
        for surface, payload in (("ai_overview", {"prompt": kw}), ("chatgpt", {"q": kw})):
            if surface not in surfaces:
                continue
            run = call(surface, payload)
            if run is None:
                row[surface] = {"status": "skipped", "competitors": {}, "citations": []}
            elif run.get("status") != "completed":
                row[surface] = {"status": "failed", "competitors": {}, "citations": []}
            else:
                text, cites = ai_answer(run.get("result"))
                row[surface] = {
                    "status": ai_status(text, cites, domain, terms[domain]),
                    "competitors": {c: ai_status(text, cites, c, terms[c]) for c in competitors},
                    "citations": cites[:10],
                }
        rows.append(row)

    volume: Dict[str, Dict[str, Any]] = {}
    if "volume" in surfaces:
        payload = {"keywords": keywords, "location_name": location or "United States", "language_code": "en"}
        run = call("volume", payload)
        if run is not None and run.get("status") == "completed":
            volume = extract_volume(run.get("result"))
    for row in rows:
        v = volume.get(row["keyword"].lower())
        if v:
            row["volume"] = v

    snapshot = {
        "domain": domain, "date": day, "competitors": competitors, "surfaces": surfaces,
        "keywords": rows, "spent": spent, "costs": costs, "capped": capped, "max_cost": max_cost,
    }
    snapshot["sov"] = share_of_voice(snapshot)
    snapshot["outrankers"] = outrankers(snapshot)
    return snapshot


def share_of_voice(snapshot: Dict[str, Any]) -> Dict[str, float]:
    """Position-weighted visibility in percent for your domain and each competitor.

    100% means position 1 for every checked keyword. Weights follow CTR_BY_POSITION.
    """
    rows = [r for r in snapshot["keywords"] if "rank" in r and r["rank"].get("note") != "skipped, cost cap reached"]
    if not rows:
        return {}
    best = CTR_BY_POSITION[1] * len(rows)
    out = {}
    for d in [snapshot["domain"]] + snapshot.get("competitors", []):
        total = 0.0
        for r in rows:
            pos = r["rank"]["position"] if d == snapshot["domain"] else r["rank"].get("competitors", {}).get(d)
            total += CTR_BY_POSITION.get(pos or 0, 0.0)
        out[d] = round(100 * total / best, 1)
    return out


def outrankers(snapshot: Dict[str, Any], limit: int = 8) -> List[Dict[str, Any]]:
    """Domains that show up above you most often across the checked keywords."""
    counts: Dict[str, Dict[str, Any]] = {}
    for r in snapshot["keywords"]:
        rank = r.get("rank") or {}
        mine = rank.get("position") or 99
        for pos, host in enumerate(rank.get("top", []), start=1):
            if host == snapshot["domain"] or host.endswith("." + snapshot["domain"]) or pos >= mine:
                continue
            c = counts.setdefault(host, {"domain": host, "above_you": 0, "positions": []})
            c["above_you"] += 1
            c["positions"].append(pos)
    ranked = sorted(counts.values(), key=lambda c: (-c["above_you"], sum(c["positions"]) / len(c["positions"])))
    for c in ranked:
        c["avg_position"] = round(sum(c.pop("positions")) / c["above_you"], 1)
    return ranked[:limit]

"""Public entry points: parse inputs, the free dry run, and the paid check. Kept for v0.1 imports."""

from __future__ import annotations

from typing import Dict, List, Optional

from .checks import SURFACES, format_quote, job_prices, quote, run_checks
from .client import Looot
from .extract import clean_domain, extract_organic, find_rank
from .history import entry_from_snapshot, load_history, previous_entry, save_history
from .html_report import render_html
from .report import render_markdown

__all__ = [
    "SURFACES", "clean_domain", "dry_run", "extract_organic", "find_rank", "load_history", "parse_keywords",
    "render_markdown", "run_checks", "save_history",
]


def parse_keywords(text: str) -> List[str]:
    """One keyword per line, # comments and blank lines skipped, duplicates removed in order."""
    seen: List[str] = []
    for line in text.splitlines():
        k = line.strip()
        if k and not k.startswith("#") and k not in seen:
            seen.append(k)
    return seen


def dry_run(
    client: Looot, domain: str, keywords: List[str], surfaces: Optional[List[str]] = None, max_cost: float = 0.5,
    prices: Optional[Dict[str, Optional[float]]] = None,
) -> List[str]:
    """Only free routes: the keyless catalog overview, plus balance when a token is set. Never runs a job."""
    surfaces = surfaces or ["rank"]
    prices = prices if prices is not None else job_prices(client)
    q = quote(prices, surfaces, len(keywords))
    lines = ["Dry run. Nothing is spent.", f"{len(keywords)} keyword(s) for {domain}.", ""]
    lines += format_quote(q, max_cost)
    lines.append("")
    if client.has_token:
        b = client.balance()
        avail = b.get("available", 0)
        lines.append(f"Balance: ${avail:.2f} available, ${b.get('reserved', 0):.2f} reserved.")
        if avail < min(q["total"], max_cost):
            lines.append("The balance is below the estimate. Top up at https://looot.ai/usage before --live.")
    else:
        lines.append("No LOOOT_TOKEN set, so the balance was not read.")
    return lines


def check_and_write(
    client: Looot,
    domain: str,
    keywords: List[str],
    surfaces: List[str],
    max_cost: float,
    competitors: Optional[List[str]] = None,
    brands: Optional[List[str]] = None,
    country: Optional[str] = None,
    location: Optional[str] = None,
    md_path: Optional[str] = "report.md",
    html_path: Optional[str] = "report.html",
    history_path: Optional[str] = "rankings.json",
    log=lambda m: None,
    today: Optional[str] = None,
) -> Dict[str, object]:
    """Paid. Runs the checks, saves history, writes the markdown and HTML reports. Returns snapshot and markdown."""
    snapshot = run_checks(client, domain, keywords, surfaces, max_cost, competitors=competitors, brands=brands,
                          country=country, location=location, log=log, today=today)
    history = load_history(history_path) if history_path else {}
    previous = previous_entry(history, snapshot["date"])
    if history_path:
        history = save_history(history_path, snapshot)
    else:
        history[snapshot["date"]] = entry_from_snapshot(snapshot)
    markdown = render_markdown(snapshot, previous)
    if md_path:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown)
    if html_path:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(render_html(snapshot, history))
    return {"snapshot": snapshot, "markdown": markdown}

"""Markdown report."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .checks import SURFACES

AI_LABEL = {"cited": "cited", "mentioned": "mentioned", "absent": "-", "no_answer": "no answer",
            "skipped": "skipped (cap)", "failed": "failed"}


def change(prev: Optional[int], now: Optional[int]) -> str:
    """+n moved up n places, -n moved down, new, lost, = or empty."""
    if prev is None and now is None:
        return ""
    if prev is None:
        return "new"
    if now is None:
        return "lost"
    if now == prev:
        return "="
    return f"{'+' if prev > now else '-'}{abs(prev - now)}"


def cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def summary(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Headline numbers shared by the markdown and HTML reports."""
    rows = snapshot["keywords"]
    ranked = [r for r in rows if (r.get("rank") or {}).get("position")]
    out: Dict[str, Any] = {
        "keywords": len(rows),
        "ranked": len(ranked),
        "top3": len([r for r in ranked if r["rank"]["position"] <= 3]),
        "top10": len([r for r in ranked if r["rank"]["position"] <= 10]),
        "visibility": snapshot.get("sov", {}).get(snapshot["domain"]),
    }
    for surface in ("ai_overview", "chatgpt"):
        checked = [r for r in rows if r.get(surface, {}).get("status") in ("cited", "mentioned", "absent", "no_answer")]
        if checked:
            out[surface] = {
                "checked": len(checked),
                "cited": len([r for r in checked if r[surface]["status"] == "cited"]),
                "mentioned": len([r for r in checked if r[surface]["status"] in ("cited", "mentioned")]),
            }
    return out


def render_markdown(snapshot: Dict[str, Any], previous: Optional[Dict[str, Any]] = None) -> str:
    previous = previous or {}
    prev_rank = previous.get("rank", {})
    s = summary(snapshot)
    rows = snapshot["keywords"]
    surfaces = snapshot["surfaces"]
    jobs = ", ".join(f"`job:{SURFACES[x]['job']}`" for x in surfaces)
    out = [
        f"# SEO report for {snapshot['domain']}",
        "",
        f"Checked {snapshot['date']} through looot ({jobs}).",
        "",
        f"- Keywords checked: {s['keywords']}",
    ]
    if "rank" in surfaces:
        out += [f"- Ranking in the results: {s['ranked']}", f"- In the top 10: {s['top10']}"]
        if s["visibility"] is not None:
            out.append(f"- Visibility (position-weighted share of voice): {s['visibility']}%")
    for surface, label in (("ai_overview", "Google AI Overview"), ("chatgpt", "ChatGPT")):
        if surface in s:
            x = s[surface]
            out.append(f"- {label}: named in {x['mentioned']} of {x['checked']} answers, cited as a source in {x['cited']}")
    out.append(f"- Spent: ${snapshot['spent']:.4f} (cap ${snapshot.get('max_cost', 0):.2f})")
    if snapshot.get("capped"):
        out.append("- Stopped at the cost cap. Skipped checks were not charged.")

    if "rank" in surfaces:
        has_vol = any("volume" in r for r in rows)
        head = "| Keyword | Position | Change | URL |" + (" Volume | CPC |" if has_vol else "") + " Note |"
        out += ["", "## Google rankings", "", head, "| --- " * (head.count("|") - 1) + "|"]
        for r in sorted(rows, key=lambda r: (r["rank"]["position"] is None, r["rank"]["position"] or 0)):
            rk = r["rank"]
            ch = change(prev_rank.get(r["keyword"]), rk["position"]) if prev_rank else ""
            line = f"| {cell(r['keyword'])} | {rk['position'] or '-'} | {ch} | {cell(rk['url'])} |"
            if has_vol:
                v = r.get("volume") or {}
                cpc = v.get("cpc")
                line += f" {v.get('search_volume') if v.get('search_volume') is not None else '-'} | {f'${cpc:.2f}' if cpc is not None else '-'} |"
            out.append(line + f" {cell(rk['note'])} |")

    if snapshot.get("sov") and len(snapshot["sov"]) > 1:
        out += ["", "## Share of voice", "", "| Domain | Visibility |", "| --- | --- |"]
        for d, v in sorted(snapshot["sov"].items(), key=lambda kv: -kv[1]):
            out.append(f"| {cell(d)} | {v}% |")

    if snapshot.get("outrankers"):
        out += ["", "## Who ranks above you", "", "| Domain | Keywords above you | Average position |", "| --- | --- | --- |"]
        for o in snapshot["outrankers"]:
            out.append(f"| {cell(o['domain'])} | {o['above_you']} | {o['avg_position']} |")

    ai = [x for x in ("ai_overview", "chatgpt") if x in surfaces]
    if ai:
        comps = snapshot.get("competitors", [])
        out += ["", "## AI answers", "",
                "`cited` means a link to your domain is among the sources. `mentioned` means your name is in the answer text.", ""]
        head = "| Keyword | " + " | ".join(SURFACES[x]["label"] for x in ai)
        if comps:
            head += " | Competitors named"
        out += [head + " |", "| --- " * (head.count("|")) + "|"]
        for r in rows:
            line = f"| {cell(r['keyword'])} | " + " | ".join(AI_LABEL.get(r.get(x, {}).get("status"), "-") for x in ai)
            if comps:
                named = sorted({c for x in ai for c, st in r.get(x, {}).get("competitors", {}).items() if st in ("cited", "mentioned")})
                line += " | " + (", ".join(named) or "-")
            out.append(line + " |")
    out.append("")
    return "\n".join(out)

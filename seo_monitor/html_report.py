"""Single-file HTML report: no scripts, no external assets, light and dark themes, SVG charts."""

from __future__ import annotations

from html import escape
from typing import Any, Dict, List, Optional, Tuple

from .checks import SURFACES
from .extract import CTR_BY_POSITION
from .report import AI_LABEL, change, summary

PALETTE = ["#1f7a5a", "#c2410c", "#2563eb", "#9333ea", "#b45309", "#0f766e"]

CSS = """
:root{--bg:#f7f7f4;--card:#fff;--ink:#16181d;--muted:#5d6470;--line:#e3e3dd;--good:#1f7a5a;--bad:#b42318;
--chip:#eef2ef;--cite:#d9f0e5;--ment:#e8eefc;--grid:#ecece7;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#111317;--card:#1a1d23;--ink:#eceef2;
--muted:#9aa1ad;--line:#2b2f37;--good:#4cc59a;--bad:#f97066;--chip:#242832;--cite:#173b2e;--ment:#1d2a48;
--grid:#252931;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#111317;--card:#1a1d23;--ink:#eceef2;--muted:#9aa1ad;--line:#2b2f37;--good:#4cc59a;
--bad:#f97066;--chip:#242832;--cite:#173b2e;--ment:#1d2a48;--grid:#252931;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1080px;margin:0 auto;padding:32px 16px 48px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}h2{font-size:17px;margin:0 0 12px}
.sub{color:var(--muted);margin:0 0 24px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr));gap:12px;margin-bottom:20px}
.tile,.card{background:var(--card);border:1px solid var(--line);border-radius:12px}
.tile{padding:14px 16px}.tile b{display:block;font-size:24px;font-variant-numeric:tabular-nums}
.tile span{color:var(--muted);font-size:13px}
.card{padding:18px;margin-bottom:16px;overflow-x:auto}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media (max-width:760px){.grid2{grid-template-columns:1fr}}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:middle;white-space:nowrap}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600}
td.url{max-width:280px;overflow:hidden;text-overflow:ellipsis}td.url a{color:var(--muted)}
.up{color:var(--good);font-weight:600}.down{color:var(--bad);font-weight:600}.muted{color:var(--muted)}
.chip{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;background:var(--chip)}
.chip.cited{background:var(--cite)}.chip.mentioned{background:var(--ment)}
.bar{height:10px;border-radius:5px;background:var(--good)}.bartrack{background:var(--chip);border-radius:5px;width:100%}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:13px;color:var(--muted);margin-top:8px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
footer{color:var(--muted);font-size:13px;margin-top:24px}
svg text{fill:var(--muted);font-size:11px}
"""


def _visibility(entry: Dict[str, Any], domain: str, own: str) -> Optional[float]:
    if domain in entry.get("sov", {}):
        return entry["sov"][domain]
    ranks = entry.get("rank", {}) if domain == own else entry.get("competitor_rank", {}).get(domain)
    if not ranks:
        return None
    return round(100 * sum(CTR_BY_POSITION.get(p or 0, 0) for p in ranks.values()) / (CTR_BY_POSITION[1] * len(ranks)), 1)


def _line_chart(dates: List[str], series: List[Tuple[str, List[Optional[float]]]], w: int = 640, h: int = 220) -> str:
    """Multi-series line chart, y from 0 to the max value. Gaps where a value is missing."""
    values = [v for _, vs in series for v in vs if v is not None]
    if len(dates) < 2 or not values:
        return '<p class="muted">The chart appears after the second run. Each run adds one point.</p>'
    top = max(10.0, max(values) * 1.15)
    left, right, pad_t, pad_b = 36, 12, 10, 26
    iw, ih = w - left - right, h - pad_t - pad_b
    x = lambda i: left + iw * i / (len(dates) - 1)  # noqa: E731
    y = lambda v: pad_t + ih * (1 - v / top)  # noqa: E731
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Visibility over time">']
    for k in range(5):
        v = top * k / 4
        parts.append(f'<line x1="{left}" x2="{w - right}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="var(--grid)"/>')
        parts.append(f'<text x="{left - 6}" y="{y(v) + 4:.1f}" text-anchor="end">{v:.0f}%</text>')
    step = max(1, len(dates) // 6)
    for i, d in enumerate(dates):
        if i % step == 0 or i == len(dates) - 1:
            parts.append(f'<text x="{x(i):.1f}" y="{h - 8}" text-anchor="middle">{escape(d[5:])}</text>')
    for n, (name, vs) in enumerate(series):
        color = PALETTE[n % len(PALETTE)]
        seg: List[str] = []
        for i, v in enumerate(vs):
            if v is None:
                if len(seg) > 1:
                    parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.2" points="{" ".join(seg)}"/>')
                seg = []
                continue
            seg.append(f"{x(i):.1f},{y(v):.1f}")
            parts.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="3" fill="{color}"><title>{escape(name)} {escape(dates[i])}: {v}%</title></circle>')
        if len(seg) > 1:
            parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.2" points="{" ".join(seg)}"/>')
    parts.append("</svg>")
    legend = "".join(f'<span><i style="background:{PALETTE[n % len(PALETTE)]}"></i>{escape(name)}</span>'
                     for n, (name, _) in enumerate(series))
    return "".join(parts) + f'<div class="legend">{legend}</div>'


def _sparkline(points: List[Optional[int]], w: int = 96, h: int = 24) -> str:
    """Position history for one keyword. Higher on the chart is a better position. Missing = off page."""
    known = [p for p in points if p]
    if len(points) < 2 or not known:
        return ""
    worst = max(max(known), 10)
    xs = lambda i: 2 + (w - 4) * i / (len(points) - 1)  # noqa: E731
    ys = lambda p: 2 + (h - 4) * ((p - 1) / max(worst - 1, 1))  # noqa: E731
    pts = [f"{xs(i):.1f},{ys(p):.1f}" for i, p in enumerate(points) if p]
    last = points[-1]
    dot = f'<circle cx="{xs(len(points) - 1):.1f}" cy="{ys(last):.1f}" r="2.4" fill="var(--good)"/>' if last else ""
    return (f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true">'
            f'<polyline fill="none" stroke="var(--muted)" stroke-width="1.5" points="{" ".join(pts)}"/>{dot}</svg>')


def _change_html(text: str) -> str:
    if text.startswith("+") or text == "new":
        return f'<span class="up">{escape(text)}</span>'
    if text.startswith("-") or text == "lost":
        return f'<span class="down">{escape(text)}</span>'
    return f'<span class="muted">{escape(text)}</span>'


def _chip(status: Optional[str]) -> str:
    if not status:
        return '<span class="muted">-</span>'
    return f'<span class="chip {escape(status)}">{escape(AI_LABEL.get(status, status))}</span>'


def render_html(snapshot: Dict[str, Any], history: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
    """The full report page. `history` should already include today's entry."""
    history = history or {}
    dom = snapshot["domain"]
    s = summary(snapshot)
    dates = sorted(history)
    prev = history[max(d for d in dates if d < snapshot["date"])] if any(d < snapshot["date"] for d in dates) else {}
    rows = snapshot["keywords"]
    surfaces = snapshot["surfaces"]

    tiles = [(s["keywords"], "keywords checked")]
    if "rank" in surfaces:
        tiles += [(f"{s['top10']}", "in the Google top 10"), (f"{s['top3']}", "in the top 3")]
        if s["visibility"] is not None:
            tiles.append((f"{s['visibility']}%", "visibility (share of voice)"))
    for surface, label in (("ai_overview", "AI Overview"), ("chatgpt", "ChatGPT")):
        if surface in s:
            tiles.append((f"{s[surface]['mentioned']}/{s[surface]['checked']}", f"named in {label}"))
    tiles.append((f"${snapshot['spent']:.4f}", f"spent of ${snapshot.get('max_cost', 0):.2f} cap"))
    tiles_html = "".join(f'<div class="tile"><b>{escape(str(v))}</b><span>{escape(t)}</span></div>' for v, t in tiles)

    body = [f'<div class="tiles">{tiles_html}</div>']

    if "rank" in surfaces:
        tracked = [dom] + snapshot.get("competitors", [])
        series = [(d, [_visibility(history.get(day, {}), d, dom) for day in dates]) for d in tracked]
        chart = _line_chart(dates, series)
        sov = snapshot.get("sov", {})
        color = {d: PALETTE[i % len(PALETTE)] for i, d in enumerate(tracked)}
        top = max(sov.values()) if sov else 0
        bars = "".join(
            f'<tr><td>{escape(d)}</td><td style="width:60%"><div class="bartrack"><div class="bar" '
            f'style="width:{(v / top * 100) if top else 0:.0f}%;background:{color[d]}"></div></div></td>'
            f"<td>{v}%</td></tr>"
            for d, v in sorted(sov.items(), key=lambda kv: -kv[1]))
        body.append(f'<div class="grid2"><section class="card"><h2>Visibility over time</h2>{chart}</section>'
                    f'<section class="card"><h2>Share of voice</h2><table>{bars}</table>'
                    f'<p class="muted" style="font-size:13px">Position-weighted: 100% is position 1 for every keyword.</p></section></div>')

        has_vol = any("volume" in r for r in rows)
        comps = snapshot.get("competitors", [])
        head = "<th>Keyword</th><th>Position</th><th>Change</th><th>Trend</th>"
        head += "".join(f"<th>{escape(c)}</th>" for c in comps)
        head += ("<th>Volume</th><th>CPC</th>" if has_vol else "") + "<th>URL</th>"
        trs = []
        for r in sorted(rows, key=lambda r: (r["rank"]["position"] is None, r["rank"]["position"] or 0)):
            rk = r["rank"]
            ch = change(prev.get("rank", {}).get(r["keyword"]), rk["position"]) if prev.get("rank") else ""
            spark = _sparkline([history.get(d, {}).get("rank", {}).get(r["keyword"]) for d in dates])
            tds = (f"<td>{escape(r['keyword'])}</td><td><b>{rk['position'] or '-'}</b></td>"
                   f"<td>{_change_html(ch)}</td><td>{spark}</td>")
            tds += "".join(f"<td>{rk.get('competitors', {}).get(c) or '-'}</td>" for c in comps)
            if has_vol:
                v = r.get("volume") or {}
                vol = v.get("search_volume")
                cpc = v.get("cpc")
                tds += f"<td>{vol if vol is not None else '-'}</td><td>{f'${cpc:.2f}' if cpc is not None else '-'}</td>"
            url = rk["url"]
            tds += (f'<td class="url"><a href="{escape(url)}">{escape(url)}</a></td>' if url
                    else f'<td class="muted">{escape(rk["note"])}</td>')
            trs.append(f"<tr>{tds}</tr>")
        body.append(f'<section class="card"><h2>Google rankings</h2><table><thead><tr>{head}</tr></thead>'
                    f'<tbody>{"".join(trs)}</tbody></table></section>')

        if snapshot.get("outrankers"):
            o_rows = "".join(f"<tr><td>{escape(o['domain'])}</td><td>{o['above_you']}</td><td>{o['avg_position']}</td></tr>"
                             for o in snapshot["outrankers"])
            body.append('<section class="card"><h2>Who ranks above you</h2><table><thead><tr><th>Domain</th>'
                        f'<th>Keywords above you</th><th>Average position</th></tr></thead><tbody>{o_rows}</tbody></table>'
                        '<p class="muted" style="font-size:13px">From the same Google results you already paid for.</p></section>')

    ai = [x for x in ("ai_overview", "chatgpt") if x in surfaces]
    if ai:
        comps = snapshot.get("competitors", [])
        head = "<th>Keyword</th>" + "".join(f"<th>{escape(SURFACES[x]['label'])}</th>" for x in ai)
        if comps:
            head += "<th>Competitors named</th>"
        trs = []
        for r in rows:
            tds = f"<td>{escape(r['keyword'])}</td>" + "".join(f"<td>{_chip(r.get(x, {}).get('status'))}</td>" for x in ai)
            if comps:
                named = sorted({c for x in ai for c, st in r.get(x, {}).get("competitors", {}).items() if st in ("cited", "mentioned")})
                tds += f"<td>{escape(', '.join(named)) or '-'}</td>"
            trs.append(f"<tr>{tds}</tr>")
        body.append(f'<section class="card"><h2>AI answers</h2><table><thead><tr>{head}</tr></thead>'
                    f'<tbody>{"".join(trs)}</tbody></table><p class="muted" style="font-size:13px">'
                    "cited: a link to your domain is among the sources. mentioned: your name is in the answer text.</p></section>")

    jobs = ", ".join(f"job:{SURFACES[x]['job']}" for x in surfaces)
    capped = " Stopped at the cost cap; skipped checks were not charged." if snapshot.get("capped") else ""
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>SEO report {escape(dom)}</title><style>{CSS}</style></head><body><main>"
        f"<h1>SEO report for {escape(dom)}</h1>"
        f'<p class="sub">Checked {escape(snapshot["date"])} through looot. {len(dates)} run(s) in history.{capped}</p>'
        + "".join(body)
        + f"<footer>Data: {escape(jobs)}. Generated by looot-seo-monitor.</footer></main></body></html>\n"
    )

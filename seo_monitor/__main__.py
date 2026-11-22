from __future__ import annotations

import argparse
import sys
from typing import List

from .client import Looot, LoootError
from .monitor import SURFACES, check_and_write, clean_domain, dry_run, parse_keywords


def _split(values: List[str]) -> List[str]:
    out: List[str] = []
    for v in values or []:
        out += [x.strip() for x in v.split(",") if x.strip()]
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="seo_monitor",
        description="Google rank, AI Overview and ChatGPT visibility for a domain through looot. "
                    "Dry run (free price quote) unless --live is given.",
    )
    p.add_argument("--domain", required=True, help="Domain to look for, e.g. example.com")
    p.add_argument("--keywords", required=True, help="Text file, one keyword per line")
    p.add_argument("--competitor", action="append", default=[], help="Competitor domain; repeat or comma-separate")
    p.add_argument("--brand", action="append", default=[], help="Extra name that counts as a mention of you in AI answers")
    p.add_argument("--ai-overview", action="store_true", help="Also check Google AI Overview per keyword")
    p.add_argument("--chatgpt", action="store_true", help="Also check ChatGPT's answer per keyword")
    p.add_argument("--volume", action="store_true", help="Also fetch search volume and CPC (one call for all keywords)")
    p.add_argument("--all", action="store_true", help="Every check above")
    p.add_argument("--no-rank", action="store_true", help="Skip the Google rank check")
    p.add_argument("--country", help="Country code passed to the SERP job, e.g. us")
    p.add_argument("--location", help='Location name, e.g. "United States" (SERP and volume)')
    p.add_argument("--out", default="report.md", help="Markdown report path")
    p.add_argument("--html", default="report.html", help="HTML report path ('' to skip)")
    p.add_argument("--history", default="rankings.json", help="JSON file that remembers past results")
    p.add_argument("--max-cost", type=float, default=0.50, help="Hard cap in USD for this run")
    p.add_argument("--live", action="store_true", help="Spend money. Without it, a free dry run")
    args = p.parse_args(argv)

    domain = clean_domain(args.domain)
    with open(args.keywords, encoding="utf-8") as f:
        keywords = parse_keywords(f.read())
    if not keywords or "." not in domain:
        print("Need a domain like example.com and at least one keyword.", file=sys.stderr)
        return 1
    if args.max_cost <= 0:
        print("--max-cost must be above 0", file=sys.stderr)
        return 1
    surfaces = [] if args.no_rank else ["rank"]
    for name, on in (("ai_overview", args.ai_overview), ("chatgpt", args.chatgpt), ("volume", args.volume)):
        if on or args.all:
            surfaces.append(name)
    if not surfaces:
        print("Nothing to check: --no-rank needs --ai-overview, --chatgpt or --volume.", file=sys.stderr)
        return 1
    competitors = [clean_domain(c) for c in _split(args.competitor)]

    client = Looot()
    try:
        if not args.live:
            print("\n".join(dry_run(client, domain, keywords, surfaces, args.max_cost)))
            print("Add --live to run the checks and write the reports.")
            return 0
        if not client.has_token:
            print("--live needs LOOOT_TOKEN. Create an agent token at https://looot.ai.", file=sys.stderr)
            return 1
        print(f"Balance ${client.balance().get('available', 0):.2f}. Hard cap ${args.max_cost:.2f}. "
              f"Checks: {', '.join(SURFACES[s]['label'] for s in surfaces)}.")
        res = check_and_write(
            client, domain, keywords, surfaces, args.max_cost, competitors=competitors, brands=_split(args.brand),
            country=args.country, location=args.location, md_path=args.out, html_path=args.html or None,
            history_path=args.history, log=print,
        )
    except LoootError as e:
        print(f"looot error {e.code}: {e}", file=sys.stderr)
        return 2
    snap = res["snapshot"]
    written = " and ".join(x for x in (args.out, args.html) if x)
    print(f"Wrote {written}. Spent ${snap['spent']:.4f}{' (stopped at the cap)' if snap['capped'] else ''}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

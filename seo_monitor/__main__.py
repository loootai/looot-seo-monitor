from __future__ import annotations

import argparse
import sys

from .client import Looot, LoootError
from .monitor import (
    check_rankings,
    clean_domain,
    dry_run,
    load_history,
    parse_keywords,
    render_report,
    save_history,
)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="seo_monitor",
        description="Check Google rankings for a domain through looot. Dry run unless --live is given.",
    )
    p.add_argument("--domain", required=True, help="Domain to look for, e.g. example.com")
    p.add_argument("--keywords", required=True, help="Text file, one keyword per line")
    p.add_argument("--out", default="report.md", help="Markdown report path")
    p.add_argument("--history", default="rankings.json", help="JSON file that remembers past positions")
    p.add_argument("--country", help="Country code passed to the SERP job, e.g. us")
    p.add_argument("--max-cost", type=float, default=0.50, help="Stop starting paid runs at this many USD")
    p.add_argument("--live", action="store_true", help="Spend money. Without it, a dry run")
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

    client = Looot()
    try:
        if not args.live:
            print("\n".join(dry_run(client, domain, keywords)))
            print("Add --live to run the checks and write the report.")
            return 0
        if not client.has_token:
            print("--live needs LOOOT_TOKEN. Create an agent token at https://looot.ai.", file=sys.stderr)
            return 1
        print(f"Balance ${client.balance().get('available', 0):.2f}. Cost cap ${args.max_cost:.2f}.")
        snapshot = check_rankings(client, domain, keywords, args.country, args.max_cost, log=print)
    except LoootError as e:
        print(f"looot error {e.code}: {e}", file=sys.stderr)
        return 2

    history = load_history(args.history)
    earlier = [d for d in history if d < snapshot["date"]]
    previous = history[max(earlier)] if earlier else None
    report = render_report(snapshot, previous)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(report)
    save_history(args.history, snapshot)
    print(f"Wrote {args.out}. Spent ${snapshot['spent']:.4f}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

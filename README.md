# looot-seo-monitor

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/loootai/looot-seo-monitor)

Checks where your domain ranks on Google for a list of keywords and writes a markdown report. It remembers past positions in a JSON file, so the next report shows what moved.

## Install for agents

```bash
git clone https://github.com/loootai/looot-seo-monitor
claude mcp add --transport http looot https://api.looot.ai/mcp
```

See also: [awesome-looot-use-cases](https://github.com/loootai/awesome-looot-use-cases) (copy-paste recipes) and [awesome-gtm](https://github.com/loootai/awesome-gtm) (open-source GTM tools).

It uses [looot](https://looot.ai): one token and one prepaid balance for 2,500+ data API endpoints. Each keyword is one `job:google.serp.organic` run. looot picks the SERP provider, shows the price first, and charges $0 for a failed call. This repo is a template. Click "Use this template" on GitHub and change what you need.

No dependencies. Standard library only, Python 3.9 or newer.

## Try it without spending anything

```bash
git clone https://github.com/loootai/looot-seo-monitor
cd looot-seo-monitor
python3 -m seo_monitor --domain example.com --keywords examples/keywords.txt
```

That is a dry run, and it is the default. It needs no token and calls only a free, public route:

```
Dry run. Nothing is spent.
job:google.serp.organic: cheapest listed price $0.0009 per keyword (7 providers)
2 keyword(s) for example.com: about $0.0018 at the cheapest provider.
```

With `LOOOT_TOKEN` set, the dry run also reads your balance and runs one catalog search, both free.

## Run it for real

1. Sign up at https://looot.ai, top up (from $5), and create an agent token with the scopes `catalog.read`, `runs.read`, `runs.execute` and `usage.read`.
2. Run:

```bash
export LOOOT_TOKEN=...      # never commit this
python3 -m seo_monitor --domain example.com --keywords my-keywords.txt --country us --max-cost 0.50 --live
```

| Flag | Meaning | Default |
| --- | --- | --- |
| `--domain` | Domain to find. Subdomains count (`blog.example.com` matches `example.com`) | required |
| `--keywords` | Text file, one keyword per line, `#` for comments | required |
| `--country` | Country code sent as `country` to the SERP job | none |
| `--max-cost` | Stop starting paid runs once this many USD are spent | 0.50 |
| `--out` | Report path | `report.md` |
| `--history` | JSON file of past positions | `rankings.json` |
| `--live` | Spend money. Without it, dry run | off |

## What the report looks like

```
# Google rankings for example.com

Checked 2026-10-08 through looot (`job:google.serp.organic`).

- Keywords checked: 2
- Ranking in the results: 1
- In the top 10: 1
- Spent: $0.0038

| Keyword | Position | Change | URL | Note |
| --- | --- | --- | --- | --- |
| best crm for startups | 4 | +2 | https://example.com/crm | |
| email verification api | - | lost | | not in the results |
```

`Change` compares with the most recent earlier run in the history file: `+2` moved up two places, `-1` moved down one, `new`, `lost` or `=`.

## How it calls looot

`POST https://api.looot.ai/v1/runs?wait=30` with `endpointId: "job:google.serp.organic"`, `input: {"query": ..., "country": ...}` and `fallback: true`. The idempotency key is a hash of the job and input, so rerunning the same keyword set on the same day does not pay twice. Job inputs are mapped to each provider's fields by looot, see https://docs.looot.ai/concepts/job-inputs.

Providers answer in different shapes. `extract_organic` in `seo_monitor/monitor.py` finds the first list of results with a `link` or `url`. If a live run reports "not in the results" for a keyword where you do rank, print `run["result"]` once and adjust that function. The cost cap is checked before each paid call, so a run can overshoot it by the price of one call.

## Run it every week

```yaml
# .github/workflows/seo.yml in your own copy
on:
  schedule: [{ cron: "0 6 * * 1" }]
jobs:
  rank:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python3 -m seo_monitor --domain example.com --keywords keywords.txt --live
        env:
          LOOOT_TOKEN: ${{ secrets.LOOOT_TOKEN }}
      - uses: actions/upload-artifact@v4
        with: { name: report, path: report.md }
```

Pin the action versions to commit SHAs in your own repo.

## Tests

```bash
python3 -m unittest discover -s tests -t .
bash scripts/leak-scan.sh .   # run before you push
```

The tests start a local mock server. They check that the dry run never POSTs a run, the live path, the cost cap and the report.

## License

MIT. Docs: https://docs.looot.ai. Support: https://looot.ai/contact.

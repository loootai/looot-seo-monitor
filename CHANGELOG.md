# Changelog

## 0.2.0

- Google AI Overview check (`--ai-overview`, `job:google.serp.ai-overview`): is your domain cited or named, and which competitors are.
- ChatGPT check (`--chatgpt`, `job:search.chatgpt`): the same for ChatGPT's live answer.
- Search volume and CPC (`--volume`, `job:google.keywords.volume`): one call for every keyword.
- Competitors (`--competitor`), position-weighted share of voice, and "who ranks above you" from the SERP call you already pay for.
- Single-file HTML report with KPI tiles, visibility over time, per-keyword trend lines and AI answer table. No scripts, light and dark.
- The dry run prices every check from the free catalog. Each paid run carries `fallback.maxCostUsd` set to what is left of `--max-cost`, so the cap is enforced by looot and no longer overshoots by one call.
- Fix: the idempotency key now includes the day. Before, a weekly run replayed the first week's answer.
- MCP server on stdio (`python3 -m seo_monitor.mcp_server`) with `seo_quote`, `seo_check` and `seo_history`.
- History file v2 (rank, competitor rank, AI status, share of voice, spend). v0.1 files are read as before.
- GitHub Actions template in `examples/github-workflow.yml`.

## 0.1.0

First release. Dry run by default, live run behind `--live`, markdown report with position changes, cost cap, idempotent reruns.

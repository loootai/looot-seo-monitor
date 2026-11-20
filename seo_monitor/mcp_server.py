"""MCP server over stdio, standard library only.

    claude mcp add seo-monitor -e LOOOT_TOKEN=... -- python3 -m seo_monitor.mcp_server

Tools:
  seo_quote    free: what a check would cost, per surface, from the public catalog
  seo_check    paid: runs the checks under max_cost_usd (required), saves history, writes reports
  seo_history  free: the saved history file as JSON
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

from . import __version__
from .checks import SURFACES, format_quote, job_prices, quote
from .client import Looot, LoootError
from .extract import clean_domain
from .history import load_history
from .monitor import check_and_write

PROTOCOL_VERSION = "2025-06-18"
SURFACE_ENUM = list(SURFACES)

_COMMON = {
    "domain": {"type": "string", "description": "Your domain, e.g. example.com"},
    "keywords": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 200},
    "surfaces": {
        "type": "array", "items": {"type": "string", "enum": SURFACE_ENUM},
        "description": "rank (Google position), ai_overview, chatgpt, volume. Default: rank",
    },
}

TOOLS = [
    {
        "name": "seo_quote",
        "description": "Free. Price a check before running it: calls and estimated USD per surface (Google rank, "
                       "Google AI Overview, ChatGPT, search volume) from the public looot catalog. Spends nothing.",
        "inputSchema": {"type": "object", "required": ["domain", "keywords"],
                        "properties": {**_COMMON, "max_cost_usd": {"type": "number", "exclusiveMinimum": 0}}},
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "seo_check",
        "description": "Paid. Check where a domain ranks on Google and whether Google AI Overview and ChatGPT name or "
                       "cite it, for each keyword, with competitors and share of voice. Never spends more than "
                       "max_cost_usd. Call seo_quote first and confirm the price with the user. Needs LOOOT_TOKEN.",
        "inputSchema": {
            "type": "object", "required": ["domain", "keywords", "max_cost_usd"],
            "properties": {
                **_COMMON,
                "max_cost_usd": {"type": "number", "exclusiveMinimum": 0, "maximum": 20},
                "competitors": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                "brands": {"type": "array", "items": {"type": "string"}, "description": "Extra names that count as a mention"},
                "country": {"type": "string"},
                "location": {"type": "string"},
                "history_path": {"type": "string", "description": "Default rankings.json in the working directory"},
                "html_path": {"type": "string", "description": "Default report.html"},
            },
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    },
    {
        "name": "seo_history",
        "description": "Free. Read the saved history file (positions, AI answer status and share of voice by date).",
        "inputSchema": {"type": "object", "properties": {"history_path": {"type": "string"}}},
        "annotations": {"readOnlyHint": True},
    },
]


def _text(text: str, is_error: bool = False) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _surfaces(args: Dict[str, Any]) -> List[str]:
    chosen = [s for s in (args.get("surfaces") or ["rank"]) if s in SURFACES]
    return chosen or ["rank"]


def call_tool(name: str, args: Dict[str, Any], client: Optional[Looot] = None) -> Dict[str, Any]:
    """Run one tool and return an MCP CallToolResult."""
    client = client or Looot()
    try:
        if name == "seo_history":
            return _text(json.dumps(load_history(args.get("history_path") or "rankings.json"), indent=2))
        domain = clean_domain(str(args.get("domain", "")))
        keywords = [str(k).strip() for k in args.get("keywords") or [] if str(k).strip()]
        if "." not in domain or not keywords:
            return _text("Need a domain like example.com and at least one keyword.", True)
        surfaces = _surfaces(args)
        if name == "seo_quote":
            cap = float(args.get("max_cost_usd") or 0.5)
            q = quote(job_prices(client), surfaces, len(keywords))
            return _text("\n".join(format_quote(q, cap)))
        if name == "seo_check":
            cap = args.get("max_cost_usd")
            if not isinstance(cap, (int, float)) or cap <= 0:
                return _text("max_cost_usd is required and must be above 0.", True)
            if not client.has_token:
                return _text("seo_check needs LOOOT_TOKEN in the server environment. Create one at https://looot.ai.", True)
            res = check_and_write(
                client, domain, keywords, surfaces, float(cap),
                competitors=[clean_domain(c) for c in args.get("competitors") or []],
                brands=args.get("brands") or [], country=args.get("country"), location=args.get("location"),
                md_path=None, html_path=args.get("html_path") or "report.html",
                history_path=args.get("history_path") or "rankings.json",
            )
            return _text(str(res["markdown"]))
        return _text(f"Unknown tool {name}", True)
    except LoootError as e:
        return _text(f"looot error {e.code}: {e}", True)


def handle(msg: Dict[str, Any], client: Optional[Looot] = None) -> Optional[Dict[str, Any]]:
    """One JSON-RPC message in, one response out (None for notifications)."""
    method = msg.get("method")
    mid = msg.get("id")
    if mid is None:
        return None
    if method == "initialize":
        version = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION
        result: Dict[str, Any] = {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "looot-seo-monitor", "version": __version__},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = msg.get("params") or {}
        result = call_tool(str(params.get("name")), params.get("arguments") or {}, client)
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(stdin=sys.stdin, stdout=sys.stdout) -> None:
    """Newline-delimited JSON-RPC over stdio, as the MCP stdio transport specifies."""
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply: Optional[Dict[str, Any]] = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = handle(msg)
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve()

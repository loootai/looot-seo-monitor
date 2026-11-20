"""Local stand-in for the looot API. Answer shapes copy real provider answers seen on 2026-11-20."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

OVERVIEW = {"categories": [{"platforms": [{"jobs": [
    {"id": "google.serp.organic", "title": "Google results", "providerCount": 9, "cheapestPerCall": 0.0009},
    {"id": "google.serp.ai-overview", "title": "AI Overview", "providerCount": 2, "cheapestPerCall": 0.0018},
    {"id": "search.chatgpt", "title": "ChatGPT", "providerCount": 1, "cheapestPerCall": 0.004},
    {"id": "google.keywords.volume", "title": "Volume", "providerCount": 1, "cheapestPerCall": 0.09},
]}]}]}

COST = {"google.serp.organic": 0.002, "google.serp.ai-overview": 0.0018, "search.chatgpt": 0.004,
        "google.keywords.volume": 0.09}


def serp_for(query):
    if query == "ranked":
        return {"data": {"organic": [
            {"position": 1, "title": "A", "link": "https://other.com/a"},
            {"position": 2, "title": "B", "link": "https://www.blog.example.com/post"},
            {"position": 3, "title": "C", "link": "https://rival.com/c"},
        ]}}
    if query == "hidden":
        return {"organic": [{"position": 1, "title": "A", "link": "https://other.com/a"},
                            {"position": 4, "title": "R", "link": "https://rival.com/r"}]}
    if query == "anyapi":
        # The shape AnyAPI returned through job:google.serp.organic.
        return {"items": 2, "output": {"data": {"query": "anyapi", "results": [
            {"link": "https://rival.com/x", "title": "X", "snippet": "s", "position": 1},
            {"link": "https://example.com/y", "title": "Y", "snippet": "s", "position": 2},
        ]}, "found": True}}
    return {"organic": []}


def ai_overview_for(prompt):
    # The shape AnyAPI returned through job:google.serp.ai-overview.
    if prompt == "ranked":
        return {"items": 1, "output": {"data": {
            "answer": "Example is a good pick. Rival also works.",
            "answerMarkdown": "Example is a good pick. Rival also works.",
            "citations": [{"url": "https://docs.example.com/guide", "index": 1, "title": "Guide"},
                          {"url": "https://other.com/z", "index": 2, "title": "Z"}],
        }, "found": True}}
    if prompt == "hidden":
        return {"items": 1, "output": {"data": {"answer": "Rival.com leads here.",
                                                 "citations": [{"url": "https://rival.com/a", "index": 1}]}, "found": True}}
    return {"items": 0, "output": {"data": {}, "found": False}}


def chatgpt_for(q):
    # The shape SearchAPI.io returned through job:search.chatgpt.
    if q == "ranked":
        return {"markdown": "Try **Example** for this.", "citations": [{"index": 9, "source_indexes": [0]}],
                "reference_links": [{"link": "https://other.com/ref", "index": 0, "title": "Ref", "source": "Other"}],
                "web_results": [{"link": "https://example.com/w", "position": 1, "title": "W", "source": "example.com"}]}
    return {"markdown": "Nothing relevant here.", "reference_links": [], "web_results": []}


def volume_for(keywords):
    return {"tasks": [{"result": [{"keyword": k, "search_volume": 1000 * (i + 1), "cpc": 1.5 + i, "competition": "LOW"}
                                  for i, k in enumerate(keywords)]}]}


class Mock:
    def __init__(self, fail_jobs=()):
        self.calls = []
        mock = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, data):
                raw = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _handle(self):
                n = int(self.headers.get("content-length") or 0)
                body = json.loads(self.rfile.read(n)) if n else None
                path = self.path.split("?")[0]
                mock.calls.append((self.command, path, self.headers.get("authorization"), body))
                if path == "/v1/catalog/overview":
                    return self._send(200, OVERVIEW)
                if not self.headers.get("authorization"):
                    return self._send(401, {"error": {"code": "unauthorized", "message": "Valid bearer token required"}})
                if path == "/v1/balance":
                    return self._send(200, {"available": 5.0, "reserved": 0})
                if path == "/v1/catalog/search":
                    return self._send(200, {"endpoints": [{"id": "serper-search"}]})
                if path == "/v1/runs":
                    job = body["endpointId"].split(":", 1)[1]
                    inp = body["input"]
                    if job in fail_jobs:
                        return self._send(200, {"runId": "r", "status": "failed", "actualCost": 0,
                                                "error": {"code": "provider_error", "message": "upstream down"}})
                    if job == "google.serp.organic":
                        result = serp_for(inp["query"])
                    elif job == "google.serp.ai-overview":
                        result = ai_overview_for(inp["prompt"])
                    elif job == "search.chatgpt":
                        result = chatgpt_for(inp["q"])
                    elif job == "google.keywords.volume":
                        result = volume_for(inp["keywords"])
                    else:
                        return self._send(200, {"status": "failed", "error": {"code": "unknown_job", "message": job}})
                    cap = (body.get("fallback") or {}).get("maxCostUsd")
                    if isinstance(cap, (int, float)) and COST[job] > cap:
                        # looot refuses a run that would cost more than fallback.maxCostUsd and charges nothing.
                        return self._send(200, {"runId": "r", "status": "failed", "actualCost": 0, "outcome": "skipped",
                                                "error": {"code": "max_cost_exceeded", "message": "over maxCostUsd"}})
                    return self._send(200, {"runId": "r", "status": "completed", "actualCost": COST[job], "result": result})
                self._send(404, {"error": {"code": "not_found", "message": "no route"}})

            do_GET = _handle
            do_POST = _handle

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def runs(self):
        return [c[3] for c in self.calls if c[1] == "/v1/runs"]

    def close(self):
        self.server.shutdown()
        self.server.server_close()

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

OVERVIEW = {"categories": [{"platforms": [{"jobs": [
    {"id": "google.serp.organic", "title": "Google results", "providerCount": 7, "cheapestPerCall": 0.0009}
]}]}]}


def serp_for(query):
    if query == "ranked":
        return {"data": {"organic": [
            {"position": 1, "title": "A", "link": "https://other.com/a"},
            {"position": 2, "title": "B", "link": "https://www.blog.example.com/post"},
        ]}}
    if query == "hidden":
        return {"organic": [{"position": 1, "title": "A", "link": "https://other.com/a"}]}
    return {"organic": []}


class Mock:
    def __init__(self):
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
                    q = body["input"]["query"]
                    return self._send(200, {"runId": "r", "status": "completed", "actualCost": 0.002, "result": serp_for(q)})
                self._send(404, {"error": {"code": "not_found", "message": "no route"}})

            do_GET = _handle
            do_POST = _handle

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

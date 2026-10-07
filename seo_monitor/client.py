"""Minimal looot REST client on the standard library. No dependencies.

Endpoints and fields come from https://api.looot.ai/openapi.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_BASE_URL = "https://api.looot.ai"


class LoootError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.status = status
        self.code = code


class Looot:
    def __init__(self, token: Optional[str] = None, base_url: Optional[str] = None, timeout: float = 75.0) -> None:
        self.base_url = (base_url or os.environ.get("LOOOT_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.token = (token if token is not None else os.environ.get("LOOOT_TOKEN", "")).strip() or None
        self.timeout = timeout

    @property
    def has_token(self) -> bool:
        return self.token is not None

    def jobs(self) -> List[Dict[str, Any]]:
        """Free, no token. Every job with its cheapest price per call."""
        data = self._request("GET", "/v1/catalog/overview", params={"depth": "jobs"}, auth=False)
        out: List[Dict[str, Any]] = []
        for cat in data.get("categories", []):
            for platform in cat.get("platforms", []):
                out.extend(platform.get("jobs", []))
        return out

    def search(self, q: str, limit: int = 3) -> Dict[str, Any]:
        """Free, needs a token with catalog.read."""
        return self._request("GET", "/v1/catalog/search", params={"q": q, "limit": limit})

    def balance(self) -> Dict[str, Any]:
        """Free, needs a token with usage.read."""
        return self._request("GET", "/v1/balance")

    def run_job(self, job: str, payload: Dict[str, Any], wait: int = 30) -> Dict[str, Any]:
        """Paid. Runs job:<job>. The idempotency key is a hash of job and input, so a rerun never pays twice."""
        digest = hashlib.sha256((job + json.dumps(payload, sort_keys=True)).encode()).hexdigest()[:32]
        body = {
            "endpointId": f"job:{job}",
            "input": payload,
            "idempotencyKey": f"seomon-{digest}",
            "fallback": True,
        }
        return self._request("POST", "/v1/runs", params={"wait": wait}, body=body)

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        auth: bool = True,
    ) -> Dict[str, Any]:
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        headers = {"accept": "application/json"}
        if auth:
            if not self.token:
                raise LoootError(401, "missing_token", f"{method} {path} needs LOOOT_TOKEN")
            headers["authorization"] = f"Bearer {self.token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["content-type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:  # noqa: S310 (https base url)
                text = res.read().decode()
        except urllib.error.HTTPError as e:
            text = e.read().decode()
            try:
                err = (json.loads(text) or {}).get("error") or {}
            except ValueError:
                err = {}
            raise LoootError(e.code, err.get("code") or f"http_{e.code}", err.get("message") or f"HTTP {e.code}") from None
        return json.loads(text) if text else {}

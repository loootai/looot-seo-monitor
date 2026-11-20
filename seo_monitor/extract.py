"""Read provider answers: organic results, AI answers with citations, and keyword volume.

Providers behind one looot job answer in different shapes, so every reader here walks the JSON and
looks for the first structure that fits instead of one fixed path.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

# Rough share of clicks by Google position, used to weight share of voice. Position 11+ counts as 0.
CTR_BY_POSITION = {1: 0.28, 2: 0.15, 3: 0.10, 4: 0.07, 5: 0.05, 6: 0.04, 7: 0.03, 8: 0.025, 9: 0.02, 10: 0.02}

TEXT_KEYS = ("answerMarkdown", "answer_markdown", "markdown", "answer_text", "answer", "text", "content")
CITATION_KEYS = ("citations", "reference_links", "references", "sources", "source_links")


def clean_domain(raw: str) -> str:
    """Lower-case host of a URL or domain, without scheme, www, path or query."""
    d = raw.strip().lower()
    for prefix in ("https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    if d.startswith("www."):
        d = d[4:]
    return d.split("/")[0].split("?")[0].split("#")[0]


def host_of(url: str) -> str:
    """Host of a URL without www, lower case."""
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def on_domain(url: str, domain: str) -> bool:
    """True when the URL is on the domain or one of its subdomains."""
    host = host_of(url)
    return host == domain or host.endswith("." + domain)


def _link(row: Dict[str, Any]) -> str:
    return str(row.get("link") or row.get("url") or "")


def extract_organic(result: Any, depth: int = 0) -> List[Dict[str, Any]]:
    """First list of result-like dicts (each with a link or url) anywhere in a SERP answer."""
    if depth > 6 or not isinstance(result, (dict, list)):
        return []
    if isinstance(result, list):
        rows = [r for r in result if isinstance(r, dict) and _link(r)]
        if rows:
            return rows
        for item in result:
            nested = extract_organic(item, depth + 1)
            if nested:
                return nested
        return []
    for key in ("organic", "organic_results", "organicResults", "results", "items"):
        if key in result:
            nested = extract_organic(result[key], depth + 1)
            if nested:
                return nested
    for value in result.values():
        nested = extract_organic(value, depth + 1)
        if nested:
            return nested
    return []


def _position(row: Dict[str, Any], index: int) -> int:
    pos = row.get("position") or row.get("rank") or row.get("rank_absolute")
    return int(pos) if isinstance(pos, (int, float)) and not isinstance(pos, bool) else index


def find_rank(result: Any, domain: str) -> Tuple[Optional[int], str]:
    """Position (1-based) and URL of the first result on `domain` or a subdomain, else (None, '')."""
    for index, row in enumerate(extract_organic(result), start=1):
        url = _link(row)
        if on_domain(url, domain):
            return _position(row, index), url
    return None, ""


def ranked_domains(result: Any, limit: int = 10) -> List[Tuple[int, str]]:
    """(position, host) for the top `limit` organic results, best first, one entry per host."""
    seen: Dict[str, int] = {}
    for index, row in enumerate(extract_organic(result), start=1):
        pos = _position(row, index)
        host = host_of(_link(row))
        if host and pos <= limit and host not in seen:
            seen[host] = pos
    return sorted(((p, h) for h, p in seen.items()))


def _first_text(node: Any, depth: int = 0) -> str:
    if depth > 6:
        return ""
    if isinstance(node, dict):
        for key in TEXT_KEYS:
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return value
        for value in node.values():
            found = _first_text(value, depth + 1)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _first_text(item, depth + 1)
            if found:
                return found
    return ""


def _citation_list(node: Any, depth: int = 0) -> List[str]:
    if depth > 6:
        return []
    if isinstance(node, dict):
        for key in CITATION_KEYS:
            value = node.get(key)
            if isinstance(value, list):
                urls = [_link(v) for v in value if isinstance(v, dict) and _link(v)]
                if urls:
                    return urls
        for value in node.values():
            found = _citation_list(value, depth + 1)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _citation_list(item, depth + 1)
            if found:
                return found
    return []


def ai_answer(result: Any) -> Tuple[str, List[str]]:
    """Answer text and cited URLs from an AI Overview or ChatGPT answer, in any provider shape."""
    return _first_text(result), _citation_list(result)


def brand_terms(domain: str, extra: Optional[List[str]] = None) -> List[str]:
    """Words that count as a mention: the domain, its first label when 3+ letters, and any given names."""
    terms = [domain]
    label = domain.split(".")[0]
    if len(label) >= 3:
        terms.append(label)
    for name in extra or []:
        if name.strip():
            terms.append(name.strip())
    return list(dict.fromkeys(t.lower() for t in terms))


def mentions(text: str, terms: List[str]) -> bool:
    """True when any term appears in the text as a whole word, case-insensitive."""
    low = text.lower()
    return any(re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", low) for t in terms)


def ai_status(text: str, citations: List[str], domain: str, terms: List[str]) -> str:
    """cited, mentioned, absent, or no_answer when the engine gave no answer."""
    if not text.strip() and not citations:
        return "no_answer"
    if any(on_domain(u, domain) for u in citations):
        return "cited"
    if mentions(text, terms):
        return "mentioned"
    return "absent"


def extract_volume(result: Any, depth: int = 0) -> Dict[str, Dict[str, Any]]:
    """keyword -> {search_volume, cpc, competition} from a keyword volume answer."""
    out: Dict[str, Dict[str, Any]] = {}
    if depth > 7:
        return out
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict) and isinstance(item.get("keyword"), str) and (
                "search_volume" in item or "searchVolume" in item or "volume" in item
            ):
                vol = item.get("search_volume", item.get("searchVolume", item.get("volume")))
                out[item["keyword"].lower()] = {
                    "search_volume": vol if isinstance(vol, (int, float)) else None,
                    "cpc": item.get("cpc") if isinstance(item.get("cpc"), (int, float)) else None,
                    "competition": item.get("competition"),
                }
            else:
                out.update(extract_volume(item, depth + 1))
    elif isinstance(result, dict):
        for value in result.values():
            out.update(extract_volume(value, depth + 1))
    return out

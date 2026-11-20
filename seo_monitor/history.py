"""History file: one entry per check date, so reports can show what moved and draw charts."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional


def _upgrade(entry: Any) -> Dict[str, Any]:
    """v0.1 files stored {keyword: position}; v2 stores {"rank": {...}, "ai_overview": {...}, ...}."""
    if isinstance(entry, dict) and ("rank" in entry and isinstance(entry.get("rank"), dict)):
        return entry
    if isinstance(entry, dict):
        return {"rank": entry}
    return {}


def load_history(path: str) -> Dict[str, Dict[str, Any]]:
    """Every saved entry by date, upgraded to the v2 shape. Missing file is an empty history."""
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {d: _upgrade(e) for d, e in raw.items()}


def entry_from_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """The compact part of a snapshot that is worth keeping over time."""
    rows = snapshot["keywords"]
    entry: Dict[str, Any] = {"spent": round(snapshot["spent"], 6)}
    if any("rank" in r for r in rows):
        entry["rank"] = {r["keyword"]: r["rank"]["position"] for r in rows if "rank" in r}
        comp: Dict[str, Dict[str, Optional[int]]] = {}
        for r in rows:
            for d, p in (r.get("rank") or {}).get("competitors", {}).items():
                comp.setdefault(d, {})[r["keyword"]] = p
        if comp:
            entry["competitor_rank"] = comp
    for surface in ("ai_overview", "chatgpt"):
        if any(surface in r for r in rows):
            entry[surface] = {r["keyword"]: r[surface]["status"] for r in rows if surface in r}
    if snapshot.get("sov"):
        entry["sov"] = snapshot["sov"]
    return entry


def save_history(path: str, snapshot: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Add or replace today's entry and write the file. Returns the full history."""
    hist = load_history(path)
    hist[snapshot["date"]] = entry_from_snapshot(snapshot)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hist, f, indent=2, sort_keys=True)
    return hist


def previous_entry(history: Dict[str, Dict[str, Any]], date: str) -> Optional[Dict[str, Any]]:
    """The most recent entry strictly before `date`, or None."""
    earlier = [d for d in history if d < date]
    return history[max(earlier)] if earlier else None

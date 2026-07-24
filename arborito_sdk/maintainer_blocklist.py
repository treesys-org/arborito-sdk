"""Maintainer Nostr-tree blocklist (same list Arborito refreshes from GitHub).

Embedded copy ships with the package; when online we fetch the live file from
``treesys-org/arborito`` on ``main`` and merge (union).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from importlib import resources
from pathlib import Path
from typing import Any

REMOTE_URL = (
    "https://raw.githubusercontent.com/treesys-org/arborito/main/"
    "src/features/nostr/api/maintainer-nostr-tree-blocklist.json"
)
FETCH_TIMEOUT_SEC = 8.0
FETCH_MIN_INTERVAL_SEC = 6 * 60 * 60
MAX_REMOTE_ENTRIES = 5000
_CACHE_NAME = "maintainer-nostr-tree-blocklist.cache.json"

_blocked: set[str] = set()
_last_fetch_at = 0.0
_loaded_embedded = False


def _key(owner_pub: str, universe_id: str) -> str:
    return f"{str(owner_pub or '').strip().lower()}/{str(universe_id or '').strip()}"


def _cache_path() -> Path:
    return Path.home() / ".arborito-sdk" / _CACHE_NAME


def _add_pairs(rows: Any) -> None:
    if not isinstance(rows, list):
        return
    n = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        k = _key(str(row.get("ownerPub") or ""), str(row.get("universeId") or ""))
        if k == "/":
            continue
        _blocked.add(k)
        n += 1
        if n >= MAX_REMOTE_ENTRIES:
            break


def _load_embedded() -> None:
    global _loaded_embedded
    if _loaded_embedded:
        return
    try:
        raw = resources.files("arborito_sdk").joinpath("data/maintainer-nostr-tree-blocklist.json").read_text(
            encoding="utf-8"
        )
        _add_pairs(json.loads(raw))
    except (OSError, json.JSONDecodeError, TypeError, AttributeError):
        pass
    _loaded_embedded = True


def _load_disk_cache() -> None:
    path = _cache_path()
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("pairs"), list):
            _add_pairs(data["pairs"])
        elif isinstance(data, list):
            _add_pairs(data)
    except (OSError, json.JSONDecodeError, TypeError):
        pass


def _write_disk_cache(pairs: list[dict[str, str]]) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "pairs": pairs}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def rebuild() -> None:
    """Rebuild in-memory set from embedded JSON + disk cache."""
    _blocked.clear()
    global _loaded_embedded
    _loaded_embedded = False
    _load_embedded()
    _load_disk_cache()


def is_nostr_tree_maintainer_blocked(owner_pub: str, universe_id: str) -> bool:
    if not _blocked:
        rebuild()
    return _key(owner_pub, universe_id) in _blocked


def refresh_maintainer_blocklist(*, force: bool = False) -> bool:
    """Fetch GitHub copy and merge. Returns True when remote was applied."""
    global _last_fetch_at
    if not _blocked:
        rebuild()
    now = time.time()
    if not force and now - _last_fetch_at < FETCH_MIN_INTERVAL_SEC:
        return False
    try:
        req = urllib.request.Request(
            REMOTE_URL,
            headers={"User-Agent": "arborito-sdk-blocklist/1.0", "Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        return False
    if not isinstance(data, list):
        return False
    pairs: list[dict[str, str]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        owner = str(row.get("ownerPub") or "").strip().lower()
        uid = str(row.get("universeId") or "").strip()
        if owner and uid:
            pairs.append({"ownerPub": owner, "universeId": uid})
        if len(pairs) >= MAX_REMOTE_ENTRIES:
            break
    _write_disk_cache(pairs)
    rebuild()
    _last_fetch_at = time.time()
    return True


def maintainer_blocklist_remote_url() -> str:
    return REMOTE_URL

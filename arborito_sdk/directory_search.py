"""Public course directory search (Nostr kind 30100) for the CLI/SDK."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from .app_pow import verify_app_pow
from .maintainer_blocklist import (
    is_nostr_tree_maintainer_blocked,
    refresh_maintainer_blocklist,
)
from .nostr_protocol import KIND_TREE_DIRECTORY, TAG_APP, TAG_APP_VALUE

_COMMON_TRIGRAMS = frozenset(
    {
        "the",
        "and",
        "ing",
        "ion",
        "ent",
        "ati",
        "for",
        "tio",
        "her",
        "ter",
        "hat",
        "tha",
        "ere",
        "ate",
        "ver",
        "con",
        "com",
        "pro",
        "que",
        "del",
        "los",
        "las",
        "una",
        "por",
        "con",
    }
)


def catalog_row_search_text(text: str) -> str:
    s = unicodedata.normalize("NFKD", str(text or "").lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def trigrams_from_token(token: str) -> list[str]:
    t = catalog_row_search_text(token).replace(" ", "")
    if len(t) < 3:
        return [t] if t else []
    return [t[i : i + 3] for i in range(0, len(t) - 2)]


def trigrams_from_query(q: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for tok in catalog_row_search_text(q).split():
        for tri in trigrams_from_token(tok):
            if tri not in seen:
                seen.add(tri)
                out.append(tri)
    norm = catalog_row_search_text(q).replace(" ", "")
    for tri in trigrams_from_token(norm):
        if tri not in seen:
            seen.add(tri)
            out.append(tri)
    return out


def rank_trigrams_for_search(tris: list[str]) -> list[str]:
    ranked = sorted(
        (t for t in tris if len(t) >= 3),
        key=lambda t: (t in _COMMON_TRIGRAMS, t),
    )
    return ranked[:8]


def catalog_row_matches_query(q_raw: str, row: dict[str, Any]) -> bool:
    q = catalog_row_search_text(q_raw)
    if not q:
        return True
    titles = row.get("titles")
    titles_blob = ""
    if isinstance(titles, dict):
        titles_blob = " ".join(str(v or "") for v in titles.values())
    hay = catalog_row_search_text(
        f"{row.get('title') or ''} {titles_blob} {row.get('description') or ''} {row.get('authorName') or ''}"
    )
    return q in hay


def _event_has_arborito_app_tag(ev: dict[str, Any]) -> bool:
    for row in ev.get("tags") or []:
        if (
            isinstance(row, list)
            and len(row) >= 2
            and str(row[0]) == TAG_APP
            and str(row[1]) == TAG_APP_VALUE
        ):
            return True
    return False


def _row_from_directory_event(ev: dict[str, Any]) -> dict[str, Any] | None:
    if not _event_has_arborito_app_tag(ev):
        return None
    try:
        body = json.loads(ev.get("content") or "null")
    except json.JSONDecodeError:
        return None
    if not isinstance(body, dict):
        return None
    if body.get("delisted") is True:
        return None
    owner = str(body.get("ownerPub") or "").strip()
    uid = str(body.get("universeId") or "").strip()
    if not owner or not uid:
        return None
    if str(ev.get("pubkey") or "").lower() != owner.lower():
        return None
    nonce = str(body.get("powNonce") or "").strip()
    if not verify_app_pow("tree_directory_v2", owner, uid, "directory", owner, nonce):
        return None
    if is_nostr_tree_maintainer_blocked(owner, uid):
        return None
    titles = body.get("titles") if isinstance(body.get("titles"), dict) else None
    langs = body.get("languages") if isinstance(body.get("languages"), list) else None
    out: dict[str, Any] = {
        "ownerPub": owner,
        "universeId": uid,
        "title": str(body.get("title") or "").strip() or "Arborito",
        "shareCode": str(body.get("shareCode") or "").strip(),
        "updatedAt": str(body.get("updatedAt") or "").strip(),
        "description": str(body.get("description") or "").strip(),
        "authorName": str(body.get("authorName") or "").strip(),
    }
    if titles:
        out["titles"] = {str(k).upper(): str(v) for k, v in titles.items() if k and v}
    if langs:
        out["languages"] = [str(c).strip().upper() for c in langs if str(c or "").strip()][:16]
    icon = str(body.get("icon") or "").strip()[:32]
    if icon:
        out["icon"] = icon
    return out


def search_public_courses(
    client: Any,
    query: str,
    *,
    limit: int = 30,
    refresh_blocklist: bool = True,
) -> list[dict[str, Any]]:
    """Search the global Arborito course directory on configured relays.

    Filters the maintainer blocklist (embedded + GitHub refresh) so blocked
    junk never appears in CLI results.
    """
    q = str(query or "").strip()
    if not q:
        return []
    if refresh_blocklist:
        refresh_maintainer_blocklist(force=False)

    limit = max(1, min(120, int(limit or 30)))
    since = int(__import__("time").time()) - 180 * 86400
    tris = rank_trigrams_for_search(trigrams_from_query(q))
    best: dict[str, dict[str, Any]] = {}

    def ingest(evs: list[dict[str, Any]] | None) -> None:
        for ev in evs or []:
            row = _row_from_directory_event(ev)
            if not row:
                continue
            if not catalog_row_matches_query(q, row):
                continue
            key = f"{row['ownerPub'].lower()}/{row['universeId']}"
            ca = int(ev.get("created_at") or 0)
            prev = best.get(key)
            if not prev or ca > int(prev.get("_ca") or 0):
                row["_ca"] = ca
                best[key] = row

    if len(q) >= 3 and tris:
        relay_limit = min(200, max(limit * 2, 80))
        for tri in tris[:2]:
            evs = client.query(
                [{"kinds": [KIND_TREE_DIRECTORY], "#t": [tri], "since": since, "limit": relay_limit}],
                timeout=8.0,
            )
            ingest(evs)
            if len(best) >= limit:
                break

    if len(best) < limit:
        need = max(limit * 2, 40)
        evs = client.query(
            [{"kinds": [KIND_TREE_DIRECTORY], "since": since, "limit": min(200, need)}],
            timeout=8.0,
        )
        ingest(evs)

    rows = sorted(best.values(), key=lambda r: int(r.get("_ca") or 0), reverse=True)
    for r in rows:
        r.pop("_ca", None)
    return rows[:limit]

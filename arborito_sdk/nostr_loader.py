"""Turn a Nostr universe bundle into SDK lesson rows (bundle format v2)."""

from __future__ import annotations

from typing import Any, Callable

from .nostr_client import NostrClient
from .quiz_v2 import _parse_leaf_header, clean_lesson_text, parse_all_challenges_from_content


def _collect_lazy_keys(node: dict[str, Any], out: list[str]) -> None:
    ntype = node.get("type")
    if ntype in ("leaf", "exam"):
        if node.get("treeLazyContent") and node.get("treeContentKey"):
            key = str(node["treeContentKey"]).strip()
            if key:
                out.append(key)
    for child in node.get("children") or []:
        if isinstance(child, dict):
            _collect_lazy_keys(child, out)


def _pick_language_root(bundle: dict[str, Any], lang: str) -> dict[str, Any] | None:
    tree = bundle.get("tree") or {}
    langs = tree.get("languages") or {}
    if not isinstance(langs, dict) or not langs:
        return None
    key = lang.upper()
    root = langs.get(key) or langs.get("ES") or langs.get("EN")
    if root is None:
        root = next(iter(langs.values()), None)
    return root if isinstance(root, dict) else None


def lessons_from_nostr_bundle(
    bundle: dict[str, Any],
    lang: str,
    *,
    fetch_lesson_chunk: Callable[[str], dict[str, Any] | None],
) -> list[dict[str, Any]]:
    root = _pick_language_root(bundle, lang)
    if not root:
        raise ValueError(f"No language tree for {lang!r} in Nostr bundle")

    lessons: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        ntype = node.get("type")
        if ntype in ("leaf", "exam"):
            raw = str(node.get("content") or "")
            if node.get("treeLazyContent") and node.get("treeContentKey"):
                chunk = fetch_lesson_chunk(str(node["treeContentKey"]))
                raw = str((chunk or {}).get("content") or "")
            challenges = parse_all_challenges_from_content(raw)
            info = _parse_leaf_header(raw)
            tags = info.get("tags") or []
            lesson: dict[str, Any] = {
                "id": node.get("id") or f"lesson-{len(lessons)}",
                "title": node.get("name") or node.get("title") or node.get("id") or "?",
                "text": clean_lesson_text(raw),
                "raw": raw,
                "meta": {"tags": list(tags) if isinstance(tags, list) else []},
            }
            if challenges:
                lesson["challenge"] = challenges[0]
                lesson["challenges"] = challenges
            lessons.append(lesson)
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    walk(root)
    return lessons


def load_nostr_course(
    client: NostrClient,
    pub: str,
    universe_id: str,
    lang: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bundle = client.load_universe_bundle(pub, universe_id)
    if not bundle:
        raise ValueError("Failed to load public tree from Nostr relays.")
    fmt_ok = (
        str(bundle.get("format") or "") == "arborito-tree"
        or int((bundle.get("meta") or {}).get("nostrBundleFormat") or 0) == 2
    )
    if not fmt_ok:
        raise ValueError(
            "Unsupported Nostr bundle format. The publisher must republish with current Arborito."
        )

    def fetch_chunk(content_key: str) -> dict[str, Any] | None:
        return chunk_cache.get(content_key)

    root = _pick_language_root(bundle, lang)
    chunk_cache: dict[str, dict[str, Any]] = {}
    if root:
        lazy_keys: list[str] = []
        _collect_lazy_keys(root, lazy_keys)
        if lazy_keys:
            chunk_cache = client.load_lesson_chunks(pub, universe_id, lazy_keys)
            missing = [k for k in lazy_keys if k not in chunk_cache]
            if missing:
                raise ValueError(
                    f"Incomplete Nostr load: missing {len(missing)} lesson chunk(s) "
                    f"(e.g. {missing[0]!r})."
                )

    lessons = lessons_from_nostr_bundle(bundle, lang, fetch_lesson_chunk=fetch_chunk)
    meta = {
        "pub": pub,
        "universe_id": universe_id,
        "title": str((bundle.get("meta") or {}).get("title") or "Arborito"),
        "share_code": str((bundle.get("meta") or {}).get("shareCode") or "").strip(),
        "updated_at": str((bundle.get("_nostr_header") or {}).get("updatedAt") or ""),
        "bundle": bundle,
    }
    return lessons, meta

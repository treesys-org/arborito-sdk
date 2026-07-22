"""Nostr bundle v2 split — port of nostr-bundle-chunks.js."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from .nostr_protocol import NOSTR_CHUNK_CONTENT_MAX


def split_utf8_chunks(text: str, max_bytes: int = NOSTR_CHUNK_CONTENT_MAX) -> list[str]:
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return [text]
    parts: list[str] = []
    start = 0
    while start < len(data):
        end = min(start + max_bytes, len(data))
        while end > start:
            try:
                parts.append(data[start:end].decode("utf-8"))
                start = end
                break
            except UnicodeDecodeError:
                end -= 1
        else:
            raise ValueError("Could not split UTF-8 text at byte boundary")
    return parts


def _safe_key_part(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9:_-]", "_", str(value if value is not None else ""))


def _main_lesson_key(node_id: str) -> str:
    return f"m__{_safe_key_part(node_id)}"


def _snap_lesson_key(snap_id: str, node_id: str) -> str:
    return f"s__{_safe_key_part(snap_id)}__{_safe_key_part(node_id)}"


def _snap_graph_key(snap_id: str) -> str:
    return f"snap__{_safe_key_part(snap_id)}"


def _walk_tree_node(
    node: dict[str, Any],
    lesson_chunks: dict[str, dict[str, str]],
    make_key,
    seen: set[int],
) -> None:
    if not isinstance(node, dict):
        return
    oid = id(node)
    if oid in seen:
        return
    seen.add(oid)
    ntype = node.get("type")
    content = node.get("content")
    if ntype in ("leaf", "exam") and isinstance(content, str) and content:
        key = make_key(str(node.get("id") or ""))
        lesson_chunks[key] = {"content": content}
        node["content"] = ""
        node["treeLazyContent"] = True
        node["treeContentKey"] = key
    else:
        node.pop("treeLazyContent", None)
        node.pop("treeContentKey", None)
    for child in node.get("children") or []:
        if isinstance(child, dict):
            _walk_tree_node(child, lesson_chunks, make_key, seen)


def _strip_languages_and_snapshots(tree: dict[str, Any], lesson_chunks: dict[str, dict[str, str]]) -> None:
    seen: set[int] = set()
    langs = tree.get("languages")
    if isinstance(langs, dict):
        for root in langs.values():
            if isinstance(root, dict):
                _walk_tree_node(root, lesson_chunks, _main_lesson_key, seen)
    snaps = tree.get("releaseSnapshots")
    if isinstance(snaps, dict):
        for snap_id, snap in snaps.items():
            if not isinstance(snap, dict):
                continue
            sl = snap.get("languages")
            if isinstance(sl, dict):
                for root in sl.values():
                    if isinstance(root, dict):
                        _walk_tree_node(
                            root,
                            lesson_chunks,
                            lambda nid, sid=str(snap_id): _snap_lesson_key(sid, nid),
                            seen,
                        )


def _offload_release_snapshots(tree: dict[str, Any], snapshot_chunks: dict[str, Any]) -> None:
    rs = tree.get("releaseSnapshots")
    if not isinstance(rs, dict):
        return
    placeholder: dict[str, Any] = {}
    for snap_id, snap in rs.items():
        if not isinstance(snap, dict):
            continue
        key = _snap_graph_key(str(snap_id))
        snapshot_chunks[key] = snap
        placeholder[str(snap_id)] = {"treeSnapshotRef": key}
    tree["releaseSnapshots"] = placeholder


def _lesson_plain_snippet(raw: str, max_len: int = 12000) -> str:
    s = str(raw or "")
    s = re.sub(r"^---[\s\S]*?---\s*", "", s, count=1, flags=re.M)
    s = re.sub(r"```[\s\S]*?```", " ", s)
    s = re.sub(r"`[^`]+`", " ", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"[#>*_|[\]()]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len] if len(s) > max_len else s


def _collect_search_entries(tree: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    def walk(node: dict[str, Any], lang: str, path: str) -> None:
        if not isinstance(node, dict) or node.get("id") is None:
            return
        ntype = node.get("type")
        name = str(node.get("name") or "")
        crumb = f"{path}/{name}" if path else name
        if ntype in ("leaf", "exam", "branch", "root"):
            entry: dict[str, Any] = {
                "id": str(node["id"]),
                "n": name,
                "t": str(ntype),
                "i": str(node.get("icon") or ""),
                "d": str(node.get("description") or ""),
                "p": crumb,
                "l": lang.upper()[:8],
                "c": bool(node.get("isCertifiable")),
            }
            if ntype in ("leaf", "exam") and isinstance(node.get("content"), str) and node["content"]:
                entry["sb"] = _lesson_plain_snippet(node["content"])
            entries.append(entry)
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child, lang, crumb)

    langs = tree.get("languages")
    if isinstance(langs, dict):
        for lang, root in langs.items():
            if isinstance(root, dict):
                walk(root, str(lang), "")
    return entries


def prepare_nostr_split_bundle_v2(
    bundle: dict[str, Any],
    *,
    include_forum: bool = True,
) -> dict[str, Any]:
    slim = copy.deepcopy(bundle)
    lesson_chunks: dict[str, dict[str, str]] = {}
    snapshot_chunks: dict[str, Any] = {}

    tree = slim.get("tree")
    if isinstance(tree, dict):
        tree.pop("searchIndex", None)
        tree.pop("forum", None)
    slim.pop("forum", None)

    search_entries = _collect_search_entries(tree) if isinstance(tree, dict) else []

    if isinstance(tree, dict):
        _strip_languages_and_snapshots(tree, lesson_chunks)
        _offload_release_snapshots(tree, snapshot_chunks)

    slim["progress"] = {
        "completedNodes": [],
        "memory": {},
        "bookmarks": {},
        "gamification": {},
        "gameData": {},
    }

    meta = slim.get("meta") if isinstance(slim.get("meta"), dict) else {}
    slim["meta"] = dict(meta)
    slim["meta"]["nostrBundleFormat"] = 2
    slim["meta"]["nostrLessonChunksCount"] = len(lesson_chunks)
    slim["meta"]["nostrSnapshotChunksCount"] = len(snapshot_chunks)
    slim["meta"]["nostrSearchEntryCount"] = len(search_entries)
    slim["meta"]["nostrForumMessageParts"] = 0

    forum_split = {
        "meta": {"messageParts": 0},
        "threads": [],
        "messageParts": [],
        "moderationLog": [],
    }
    if include_forum and isinstance(bundle.get("forum"), dict):
        fo = bundle["forum"]
        messages = fo.get("messages") if isinstance(fo.get("messages"), list) else []
        forum_split = {
            "meta": {"messageParts": 1, "messageCount": len(messages)},
            "threads": fo.get("threads") if isinstance(fo.get("threads"), list) else [],
            "messageParts": [messages],
            "moderationLog": fo.get("moderationLog") if isinstance(fo.get("moderationLog"), list) else [],
        }
        slim["meta"]["nostrForumMessageParts"] = 1

    return {
        "slimBundle": slim,
        "lessonChunks": lesson_chunks,
        "snapshotChunks": snapshot_chunks,
        "searchPack": {"version": 1, "entries": search_entries},
        "forumSplit": forum_split,
    }


def build_bundle_from_archive(
    path: str,
    *,
    title: str = "",
    author_name: str = "CLI",
    description: str = "",
) -> dict[str, Any]:
    from pathlib import Path

    from .quiz_v2 import load_arborito_archive

    data = load_arborito_archive(path)
    meta_in = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    tree = data.get("tree") if isinstance(data.get("tree"), dict) else {}
    name = title or str(meta_in.get("name") or Path(path).stem)
    desc = description or str(meta_in.get("description") or "Published from arborito-cli.")
    if len(desc.strip()) < 5:
        desc = "Published from arborito-cli."
    author = author_name or str(meta_in.get("authorName") or "CLI")
    if len(author.strip()) < 2:
        author = "CLI"
    return {
        "format": "arborito-bundle",
        "version": 1,
        "meta": {
            "title": name,
            "description": desc,
            "authorName": author,
            "forumEnabled": False,
            "listInDiscover": True,
        },
        "tree": tree,
        "progress": {
            "completedNodes": [],
            "memory": {},
            "bookmarks": {},
            "gamification": {},
            "gameData": {},
        },
        "forum": {"version": 1, "threads": [], "messages": [], "moderationLog": []},
    }


def reassemble_main_json(parts: list[str]) -> dict[str, Any]:
    return json.loads("".join(parts))

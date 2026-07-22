"""Load lessons from exported .arborito archives."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .quiz_v2 import (
    clean_lesson_text,
    load_arborito_archive as _load_archive,
    parse_all_challenges_from_content,
    _parse_leaf_header,
)


def _lesson_from_node(node: dict[str, Any]) -> dict[str, Any]:
    raw = node.get("content") or ""
    challenges = parse_all_challenges_from_content(raw)
    info = _parse_leaf_header(raw)
    tags = info.get("tags") or []
    lesson: dict[str, Any] = {
        "id": node["id"],
        "title": node.get("name") or node["id"],
        "text": clean_lesson_text(raw),
        "raw": raw,
        "node_type": node.get("type"),
        "path": node.get("path"),
        "icon": node.get("icon"),
        "meta": {"tags": list(tags) if isinstance(tags, list) else []},
    }
    if challenges:
        lesson["challenge"] = challenges[0]
        lesson["challenges"] = challenges
    return lesson


def load_arborito_course(path: str | Path, lang: str = "ES") -> dict[str, Any]:
    """Full course: tree root, flat lessons, id index, meta."""
    data = _load_archive(path)
    languages = (data.get("tree") or {}).get("languages") or {}
    lang_key = lang.upper()
    root = languages.get(lang_key) or languages.get("ES") or next(iter(languages.values()), None)
    if not root:
        raise ValueError(f"No language tree in {path}")

    lessons: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}

    def walk(node: dict[str, Any]) -> None:
        ntype = node.get("type")
        if ntype in ("leaf", "exam"):
            lesson = _lesson_from_node(node)
            lessons.append(lesson)
            by_id[lesson["id"]] = lesson
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    walk(root)
    meta = data.get("meta") or {}
    return {
        "lessons": lessons,
        "tree_root": root,
        "lesson_by_id": by_id,
        "meta": meta,
        "files": data.get("files") or {},
        "source_label": str(Path(path).name),
        "source_path": str(Path(path).resolve()),
    }


def load_arborito_archive(path: str | Path, lang: str = "ES") -> list[dict[str, Any]]:
    """Walk an `.arborito` ZIP and return its leaf/exam lessons in order."""
    return load_arborito_course(path, lang=lang)["lessons"]

"""Write lesson markdown back into local ``.arborito`` archives (construction parity)."""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Optional

from .client import Arborito
from .quiz_v2 import parse_all_challenges_from_content
from .tree_nav import find_node, walk_tree

_UNSAFE_TITLE_CHARS = set('<>:"/\\|?*')


def reconstruct_arborito_file(meta: dict[str, Any], body_md: str) -> str:
    """Rebuild leaf file: optional ``@info`` + body (matches Arborito editor)."""
    fields: list[str] = []
    title = str(meta.get("title") or "").strip()
    if title and any(c in title for c in _UNSAFE_TITLE_CHARS):
        fields.append(f"title: {title}")
    icon = str(meta.get("icon") or "").strip()
    if icon and icon != "📄":
        fields.append(f"icon: {icon}")
    desc = str(meta.get("description") or "").strip()
    if desc:
        fields.append(f"description: {desc}")
    if meta.get("exam"):
        fields.append("exam: yes")
    if meta.get("certifiable"):
        fields.append("certifiable: yes")
    discussion = str(meta.get("discussion") or "").strip()
    if discussion:
        fields.append(f"discussion: {discussion}")
    tags = meta.get("tags") or []
    if isinstance(tags, list) and tags:
        fields.append(f"tags: {', '.join(str(t) for t in tags if str(t).strip())}")

    out = ""
    if fields:
        out = "@info\n" + "\n".join(fields) + "\n@/info"
    body = str(body_md or "").strip()
    if body:
        if out:
            out += "\n\n"
        out += body + "\n"
    elif out:
        out += "\n"
    return out


def find_tree_node(api: Arborito, lesson_id: str) -> Optional[dict[str, Any]]:
    root = api.tree.root()
    if not root:
        return None
    for node in walk_tree(root):
        if str(node.get("id") or "") == lesson_id:
            return node
    hits = api.tree.find(lesson_id)
    return hits[0] if hits else None


def lesson_archive_entry(api: Arborito, lesson: dict[str, Any]) -> Optional[str]:
    node = find_tree_node(api, str(lesson.get("id") or ""))
    if node and node.get("archive_entry"):
        return str(node["archive_entry"])
    return None


def validate_lesson_markdown(text: str) -> list[str]:
    """Light validation before save (quiz blocks must parse)."""
    warnings: list[str] = []
    try:
        parse_all_challenges_from_content(text)
    except Exception as e:
        warnings.append(f"@quiz parse: {e}")
    if "@info" in text and "@/info" not in text:
        warnings.append("@info block not closed")
    return warnings


def update_archive_entry(archive_path: Path, entry_name: str, content: str) -> None:
    """Replace one ZIP member atomically."""
    archive_path = archive_path.resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(f"Archive not found: {archive_path}")
    fd, tmp_name = tempfile.mkstemp(suffix=".arborito", dir=archive_path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with zipfile.ZipFile(archive_path, "r") as zin, zipfile.ZipFile(tmp, "w") as zout:
            seen = False
            for item in zin.infolist():
                if item.filename == entry_name:
                    zout.writestr(item, content.encode("utf-8"))
                    seen = True
                else:
                    zout.writestr(item, zin.read(item.filename))
            if not seen:
                zout.writestr(entry_name, content.encode("utf-8"))
        shutil.move(str(tmp), str(archive_path))
    finally:
        if tmp.is_file():
            tmp.unlink(missing_ok=True)


def _apply_lesson_content(api: Arborito, lesson_id: str, raw_markdown: str) -> None:
    """Update the canonical playlist / by-id row (not a shallow by_id copy)."""
    from .quiz_v2 import _parse_leaf_header, clean_lesson_text, parse_all_challenges_from_content

    challenges = parse_all_challenges_from_content(raw_markdown)
    text = clean_lesson_text(raw_markdown)
    info = _parse_leaf_header(raw_markdown)
    tags = info.get("tags") or []
    meta = {"tags": list(tags) if isinstance(tags, list) else []}

    def patch(row: dict[str, Any]) -> None:
        row["raw"] = raw_markdown
        row["text"] = text
        row["meta"] = meta
        if challenges:
            row["challenge"] = challenges[0]
            row["challenges"] = challenges
        else:
            row.pop("challenge", None)
            row.pop("challenges", None)

    hit = getattr(api, "_lesson_by_id", {}).get(lesson_id)
    if isinstance(hit, dict):
        patch(hit)
    catalog = getattr(api, "_lesson_catalog", None)
    if isinstance(catalog, dict):
        cat = catalog.get(lesson_id)
        if isinstance(cat, dict) and cat is not hit:
            patch(cat)
    for row in getattr(api, "_playlist", []) or []:
        if isinstance(row, dict) and str(row.get("id") or "") == lesson_id and row is not hit:
            patch(row)
    for row in getattr(api, "_all_lessons", []) or []:
        if isinstance(row, dict) and str(row.get("id") or "") == lesson_id and row is not hit:
            patch(row)


def save_lesson_raw(
    api: Arborito,
    lesson_id: str,
    raw_markdown: str,
    *,
    archive_path: Optional[Path] = None,
) -> str:
    """Persist lesson body to a local ``.arborito`` file. Returns entry path."""
    path = archive_path or getattr(api, "_source_path", None)
    if not path or not Path(path).is_file():
        raise ValueError("Lesson edit requires a local .arborito file (not Nostr/read-only).")
    node = find_tree_node(api, lesson_id)
    if not node:
        raise ValueError(f"Lesson node not found: {lesson_id}")
    entry = str(node.get("archive_entry") or "")
    if not entry:
        raise ValueError("No archive path for this lesson.")
    warnings = validate_lesson_markdown(raw_markdown)
    if warnings:
        raise ValueError("; ".join(warnings))
    from .lesson_toc_mutations import prepare_construct_outline_body

    raw_markdown = prepare_construct_outline_body(raw_markdown)
    update_archive_entry(Path(path), entry, raw_markdown)
    node["content"] = raw_markdown
    _apply_lesson_content(api, lesson_id, raw_markdown)
    return entry


def resolve_lesson(
    api: Arborito,
    sess: Any,
    identifier: Optional[str] = None,
) -> dict[str, Any]:
    """Focus, numeric index, or partial title."""
    lesson = None
    if identifier is None:
        lid = sess.focus.get("lesson_id")
        if lid:
            lesson = api.lesson.by_id(lid)
    elif str(identifier).isdigit():
        n = int(identifier)
        lesson = api.lesson.at(n - 1) if n >= 1 else None
    else:
        root = api.tree.root()
        if root:
            hits = find_node(root, identifier, partial=True)
            for h in hits:
                if str(h.get("type") or "") in ("leaf", "exam"):
                    lesson = api.lesson.by_id(str(h.get("id") or ""))
                    if lesson:
                        break
    if not lesson:
        raise ValueError("No lesson — go to a leaf or pass an index/title.")
    return lesson

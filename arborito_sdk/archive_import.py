"""Detect branch vs composed-tree ``.arborito`` archives."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Literal

CONTENT_KIND_TREE = "composed-tree"
COMPOSED_TREE_JSON = "composed-tree.json"


def _manifest_title(meta: dict[str, Any] | None, fallback: str = "") -> str:
    m = meta if isinstance(meta, dict) else {}
    titles = m.get("titles")
    if isinstance(titles, dict):
        for v in titles.values():
            t = str(v or "").strip()
            if t:
                return t
    return str(fallback or "").strip()


def analyze_arborito_import(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    with zipfile.ZipFile(p) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        if manifest.get("format") != "arborito":
            raise ValueError("Wrong archive format (expected format: \"arborito\")")
        entries = {i.filename: zf.read(i.filename) for i in zf.infolist() if not i.is_dir()}
    tree_bundle = None
    if COMPOSED_TREE_JSON in entries:
        try:
            tree_bundle = json.loads(entries[COMPOSED_TREE_JSON].decode("utf-8"))
        except json.JSONDecodeError:
            tree_bundle = None
    content_kind = str(manifest.get("contentKind") or "").strip()
    is_tree = content_kind == CONTENT_KIND_TREE or (
        tree_bundle is not None and content_kind != "branch"
    )
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    if is_tree and tree_bundle:
        tree = tree_bundle.get("tree") if isinstance(tree_bundle.get("tree"), dict) else tree_bundle
        refs = (tree or {}).get("branchRefs") or []
        title = str(
            (tree or {}).get("title")
            or _manifest_title(meta)
            or p.stem
        )
        return {
            "kind": "composed-tree",
            "title": title,
            "branch_count": len(refs),
            "path": str(p.resolve()),
            "manifest": manifest,
            "bundle": tree_bundle,
        }
    lesson_count = sum(1 for n in entries if n.startswith("lessons/") and n.endswith(".md"))
    title = _manifest_title(meta, p.stem) or p.stem
    return {
        "kind": "branch",
        "title": title,
        "lesson_count": lesson_count,
        "path": str(p.resolve()),
        "manifest": manifest,
    }

def import_kind(path: str | Path) -> Literal["branch", "composed-tree"]:
    return analyze_arborito_import(path)["kind"]  # type: ignore[return-value]

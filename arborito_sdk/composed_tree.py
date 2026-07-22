"""Composed tree (playlist) ``.arborito`` archives."""

from __future__ import annotations

import json
import uuid
import zipfile
from pathlib import Path
from typing import Any

COMPOSED_TREE_JSON = "composed-tree.json"
EMBEDDED_BRANCH_PREFIX = "branches/"
TREE_BUNDLE_FORMAT = "arborito-tree"


def _parse_tree_bundle(bundle: dict[str, Any]) -> dict[str, Any] | None:
    if not bundle or bundle.get("format") != TREE_BUNDLE_FORMAT:
        if isinstance(bundle.get("tree"), dict):
            return bundle["tree"]
        return None
    tree = bundle.get("tree")
    return tree if isinstance(tree, dict) else None


def read_composed_tree_archive(path: str | Path) -> dict[str, Any]:
    p = Path(path).resolve()
    with zipfile.ZipFile(p) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        entries = {i.filename: zf.read(i.filename) for i in zf.infolist() if not i.is_dir()}
    bundle = None
    if COMPOSED_TREE_JSON in entries:
        bundle = json.loads(entries[COMPOSED_TREE_JSON].decode("utf-8"))
    tree = _parse_tree_bundle(bundle or {})
    embedded: dict[str, bytes] = {}
    for name, data in entries.items():
        if name.startswith(EMBEDDED_BRANCH_PREFIX) and name.endswith(".arborito"):
            bid = name[len(EMBEDDED_BRANCH_PREFIX) : -len(".arborito")]
            if bid:
                embedded[bid] = data
    return {
        "manifest": manifest,
        "bundle": bundle,
        "tree": tree or {},
        "embedded": embedded,
        "path": str(p),
    }


def import_composed_tree(sess: Any, path: str | Path) -> dict[str, Any]:
    """Register composed tree and extract first embedded branch if present."""
    from pathlib import Path

    import click

    from .archive_write import tree_storage_dir, unique_copy_path
    from .cli_session import CliSession

    assert isinstance(sess, CliSession)
    p = Path(path).resolve()
    if not p.is_file():
        raise click.ClickException(f"Not found: {path}")
    data = read_composed_tree_archive(p)
    tree = data.get("tree") or {}
    title = str(tree.get("title") or data.get("manifest", {}).get("meta", {}).get("name") or p.stem)
    tree_id = str(tree.get("id") or f"tree-{uuid.uuid4().hex[:12]}")
    dest = unique_copy_path("tree", title)
    dest.write_bytes(p.read_bytes())
    refs = tree.get("branchRefs") or []
    embedded = data.get("embedded") or {}
    first_branch_path = ""
    if refs:
        ref0 = refs[0] if isinstance(refs[0], dict) else {}
        bid = str(ref0.get("branchId") or ref0.get("refId") or "").strip()
        if bid and bid in embedded:
            branch_dir = tree_storage_dir() / tree_id / "branches"
            branch_dir.mkdir(parents=True, exist_ok=True)
            first_branch_path = str((branch_dir / f"{bid}.arborito").resolve())
            Path(first_branch_path).write_bytes(embedded[bid])
            from .client import Arborito

            api = Arborito.from_arborito(first_branch_path, lang=sess.lang, username="cli", avatar="🌳")
            info = api.tree.info()
            sess.register_branch(
                branch_id=bid,
                name=str(ref0.get("displayName") or info.get("name") or bid),
                source=first_branch_path,
            )
    extra: dict[str, Any] = {}
    if first_branch_path:
        extra["first_branch"] = first_branch_path
    sess.register_tree(tree_id=tree_id, name=title, source=str(dest), extra=extra)
    sess.set_focus(source=str(dest), tree_name=title)
    if first_branch_path:
        sess.focus["study_source"] = first_branch_path
    sess.save()
    return {"id": tree_id, "name": title, "branch_count": len(refs), "path": str(dest)}

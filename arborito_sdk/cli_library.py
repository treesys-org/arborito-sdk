"""Branch / tree library (Bosque) — kubectl-style helpers."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Optional

import click

from .archive_import import import_kind
from .archive_write import export_branch_file, plant_branch, unique_copy_path
from .cli_emoji import BRANCH_CHIP, COMPOSED_TREE
from .cli_session import CliSession


def _resolve_ref(rows: list[dict[str, Any]], ref: Optional[str]) -> dict[str, Any]:
    if not ref:
        if len(rows) == 1:
            return rows[0]
        names = ", ".join(f'"{e.get("name")}"' for e in rows[:8])
        raise click.ClickException(
            f"Specify a name: branch open \"Course Name\"\n"
            f"Available: {names}" + (" …" if len(rows) > 8 else "")
        )
    ref = ref.strip().strip('"').strip("'")
    if ref.isdigit():
        n = int(ref)
        if 1 <= n <= len(rows):
            return rows[n - 1]
    ref_fold = ref.casefold()
    matches = [
        e
        for e in rows
        if ref_fold == str(e.get("name") or "").casefold()
        or ref_fold == str(e.get("id") or "").casefold()
        or ref_fold in str(e.get("name") or "").casefold()
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(f'"{m.get("name")}"' for m in matches)
        raise click.ClickException(f"Ambiguous name. Matches: {names}")
    raise click.ClickException(f"Not found: {ref}")


def list_branches(sess: CliSession, *, as_json: bool = False) -> None:
    rows = sess.list_branches()
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False))
        return
    if not rows:
        click.echo("No branches. branch add CODE | branch import file.arborito | branch new")
        return
    for e in rows:
        src = str(e.get("source") or "")
        tag = "local" if Path(src).is_file() else src.split(":", 1)[0] if ":" in src else src
        click.echo(f"  {BRANCH_CHIP} {e.get('name')}  ({tag})")
    click.echo('Open: branch open "Name"')


def list_trees(sess: CliSession, *, as_json: bool = False) -> None:
    rows = sess.list_trees()
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False))
        return
    if not rows:
        click.echo("No trees. tree import file.arborito")
        return
    for e in rows:
        click.echo(f"  {COMPOSED_TREE} {e.get('name')}")
    click.echo('Open: tree open "Name"')


def open_branch(sess: CliSession, ref: Optional[str] = None) -> dict[str, Any]:
    from .cli_focus import clear_nav_focus

    entry = _resolve_ref(sess.list_branches(), ref)
    clear_nav_focus(sess)
    sess.set_focus(source=str(entry.get("source") or ""), tree_name=str(entry.get("name") or ""))
    sess.focus.pop("study_source", None)
    nref = entry.get("nostr_ref")
    if isinstance(nref, dict) and nref.get("pub"):
        sess.set_nostr_ref(str(nref["pub"]), str(nref.get("universe_id") or ""))
    else:
        sess.focus.pop("nostr_ref", None)
    sess.save()
    return entry


def open_tree(sess: CliSession, ref: Optional[str] = None) -> dict[str, Any]:
    from .cli_focus import clear_nav_focus

    entry = _resolve_ref(sess.list_trees(), ref)
    clear_nav_focus(sess)
    sess.set_focus(source=str(entry.get("source") or ""), tree_name=str(entry.get("name") or ""))
    fb = str(entry.get("first_branch") or "").strip()
    if fb and Path(fb).is_file():
        sess.focus["study_source"] = fb
    else:
        sess.focus.pop("study_source", None)
    sess.save()
    return entry


def branch_add(
    sess: CliSession,
    code: str,
    *,
    relays: Optional[list[str]] = None,
) -> tuple[Any, str]:
    from .nostr_client import NostrClient
    from .session_nostr import join_share_code

    client = NostrClient(relays)
    joined = join_share_code(client, code, lang=sess.lang)
    api = joined.pop("api")
    info = api.tree.info()
    from .nostr_protocol import normalize_tree_share_code

    norm = normalize_tree_share_code(code) or code
    nref = None
    if getattr(api, "_nostr_ref", None):
        nref = dict(api._nostr_ref)
    sess.register_branch(
        branch_id=str(joined.get("id") or norm),
        name=str(info.get("name") or joined.get("name") or norm),
        source=f"share:{joined.get('share_code') or norm}",
        share_code=str(joined.get("share_code") or norm),
        nostr_ref=nref,
    )
    from .cli_focus import clear_nav_focus

    clear_nav_focus(sess)
    sess.set_focus(
        source=f"share:{joined.get('share_code') or norm}",
        tree_name=str(info.get("name") or joined.get("name") or norm),
    )
    if nref:
        sess.set_nostr_ref(nref["pub"], nref["universe_id"])
    sess.save()
    label = str(info.get("name") or norm)
    return api, label


def branch_import(sess: CliSession, path: str) -> None:
    p = Path(path).resolve()
    if p.is_dir():
        raise click.ClickException(f"Expected a .arborito file, got a directory: {path}")
    if not p.is_file():
        raise click.ClickException(f"Not found: {path}")
    if p.suffix.lower() != ".arborito":
        raise click.ClickException(f"Expected a .arborito file: {path}")
    kind = import_kind(p)
    if kind == "composed-tree":
        raise click.ClickException('Composed tree archive — use: tree import "file.arborito"')
    from .client import Arborito

    api = Arborito.from_arborito(p, lang=sess.lang, username="cli", avatar="🌳")
    info = api.tree.info()
    sess.register_branch(
        branch_id=str(info.get("id") or p.stem),
        name=str(info.get("name") or p.stem),
        source=str(p),
    )
    from .cli_focus import clear_nav_focus

    clear_nav_focus(sess)
    sess.set_focus(source=str(p), tree_name=str(info.get("name") or p.stem))
    sess.save()
    click.echo(f"Imported branch: {info.get('name')}")


def tree_import(sess: CliSession, path: str) -> None:
    p = Path(path).resolve()
    if p.is_dir():
        raise click.ClickException(f"Expected a .arborito file, got a directory: {path}")
    if not p.is_file():
        raise click.ClickException(f"Not found: {path}")
    if p.suffix.lower() != ".arborito":
        raise click.ClickException(f"Expected a .arborito file: {path}")
    kind = import_kind(p)
    if kind != "composed-tree":
        raise click.ClickException('Not a composed tree — use: branch import "file.arborito"')
    from .composed_tree import import_composed_tree

    info = import_composed_tree(sess, p)
    click.echo(f"Imported tree: {info.get('name')} ({info.get('branch_count')} branches)")


def branch_new(sess: CliSession, name: str) -> Path:
    out = unique_copy_path("branch", name)
    plant_branch(name, out, lang=sess.lang)
    from .client import Arborito

    api = Arborito.from_arborito(out, lang=sess.lang, username="cli", avatar="🌳")
    info = api.tree.info()
    bid = str(info.get("id") or f"branch-{uuid.uuid4().hex[:12]}")
    sess.register_branch(branch_id=bid, name=name, source=str(out))
    from .cli_focus import clear_nav_focus

    clear_nav_focus(sess)
    sess.set_focus(source=str(out), tree_name=name)
    sess.save()
    return out


def remove_entry(sess: CliSession, kind: str, ref: str) -> dict[str, Any]:
    rows = sess.list_branches() if kind == "branch" else sess.list_trees()
    entry = _resolve_ref(rows, ref)
    key = "branches" if kind == "branch" else "trees"
    kept = [e for e in rows if e.get("id") != entry.get("id")]
    sess._data[key] = kept
    if sess.focus.get("source") == entry.get("source"):
        for fkey in ("source", "tree_name", "module_id", "module_name", "lesson_id", "lesson_name", "study_source"):
            sess.focus.pop(fkey, None)
    sess.save()
    return entry


def export_entry(sess: CliSession, kind: str, ref: str, dest: str) -> Path:
    rows = sess.list_branches() if kind == "branch" else sess.list_trees()
    entry = _resolve_ref(rows, ref)
    src = str(entry.get("source") or "")
    if not src or not Path(src).is_file():
        raise click.ClickException("Export only works for local .arborito files.")
    return export_branch_file(src, dest)


def cp_entry(sess: CliSession, kind: str, ref: str) -> dict[str, Any]:
    rows = sess.list_branches() if kind == "branch" else sess.list_trees()
    entry = _resolve_ref(rows, ref)
    src = str(entry.get("source") or "")
    base_name = f"Copy of {entry.get('name') or 'item'}"
    if kind == "branch":
        if src.startswith("share:") or entry.get("nostr_ref"):
            raise click.ClickException(
                "Network branch: save locally first with branch export, then edit the copy."
            )
        if not Path(src).is_file():
            raise click.ClickException("Cannot copy: no local file. branch import or branch new first.")
        dest = unique_copy_path("branch", base_name)
        dest.write_bytes(Path(src).read_bytes())
        from .client import Arborito

        api = Arborito.from_arborito(dest, lang=sess.lang, username="cli", avatar="🌳")
        info = api.tree.info()
        new_id = str(info.get("id") or f"branch-{uuid.uuid4().hex[:12]}")
        sess.register_branch(branch_id=new_id, name=base_name, source=str(dest))
        from .cli_focus import clear_nav_focus

        clear_nav_focus(sess)
        sess.set_focus(source=str(dest), tree_name=base_name)
        sess.save()
        return {"name": base_name, "source": str(dest), "id": new_id}
    if not Path(src).is_file():
        raise click.ClickException("Cannot copy tree without local file.")
    dest = unique_copy_path("tree", base_name)
    dest.write_bytes(Path(src).read_bytes())
    new_id = f"tree-{uuid.uuid4().hex[:12]}"
    extra: dict[str, Any] = {}
    # Re-extract first embedded branch so the copy does not share the source path.
    try:
        from .composed_tree import read_composed_tree_archive
        from .archive_write import tree_storage_dir

        data = read_composed_tree_archive(dest)
        tree = data.get("tree") or {}
        refs = tree.get("branchRefs") or []
        embedded = data.get("embedded") or {}
        if refs:
            ref0 = refs[0] if isinstance(refs[0], dict) else {}
            bid = str(ref0.get("branchId") or ref0.get("refId") or "").strip()
            if bid and bid in embedded:
                branch_dir = tree_storage_dir() / new_id / "branches"
                branch_dir.mkdir(parents=True, exist_ok=True)
                first_branch_path = str((branch_dir / f"{bid}.arborito").resolve())
                Path(first_branch_path).write_bytes(embedded[bid])
                extra["first_branch"] = first_branch_path
    except Exception:
        if entry.get("first_branch"):
            extra["first_branch"] = entry.get("first_branch")
    sess.register_tree(tree_id=new_id, name=base_name, source=str(dest), extra=extra)
    from .cli_focus import clear_nav_focus

    clear_nav_focus(sess)
    sess.set_focus(source=str(dest), tree_name=base_name)
    if extra.get("first_branch"):
        sess.focus["study_source"] = str(extra["first_branch"])
    sess.save()
    return {"id": new_id, "name": base_name, "source": str(dest)}

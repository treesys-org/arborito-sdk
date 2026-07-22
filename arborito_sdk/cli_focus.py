"""CLI focus path, breadcrumb, and --node resolution."""

from __future__ import annotations

from typing import Any, Optional

from .client import Arborito
from .cli_emoji import FOCUS_LESSON, FOCUS_MODULE, FOCUS_ROOT
from .cli_session import CliSession
from .tree_nav import find_node, walk_tree


def snapshot_focus(sess: CliSession) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in sess.focus.items():
        if v is None:
            continue
        if k == "nostr_ref" and isinstance(v, dict):
            out[k] = v  # type: ignore[assignment]
        else:
            out[k] = str(v)
    return out


def restore_focus(sess: CliSession, snap: dict[str, Any]) -> None:
    f = sess.focus
    for key in ("source", "tree_name", "module_id", "module_name", "lesson_id", "lesson_name", "node_path"):
        if key in snap:
            f[key] = snap[key]
    if "nostr_ref" in snap:
        f["nostr_ref"] = snap["nostr_ref"]
    sess.save()


def remember_focus_undo(sess: CliSession) -> None:
    sess._data["focus_undo"] = snapshot_focus(sess)  # type: ignore[attr-defined]


def restore_focus_undo(sess: CliSession) -> bool:
    undo = sess._data.get("focus_undo")  # type: ignore[attr-defined]
    if not isinstance(undo, dict):
        return False
    restore_focus(sess, undo)
    del sess._data["focus_undo"]  # type: ignore[attr-defined]
    return True


def find_node_by_path(root: dict[str, Any], path_str: str) -> Optional[dict[str, Any]]:
    raw = (path_str or "").strip().strip("/")
    if not raw:
        return root
    raw_fold = raw.casefold()
    for node in walk_tree(root):
        np = str(node.get("path") or "").strip()
        if not np:
            continue
        if np.casefold() == raw_fold or np.casefold().endswith("/" + raw_fold):
            return node
    parts = [p.strip() for p in raw.replace(" / ", "/").split("/") if p.strip()]
    node: Optional[dict[str, Any]] = root
    for part in parts:
        if part.casefold() in ("raíz", "raiz", "root", "árbol", "arbol"):
            continue
        if node is None:
            return None
        children = [c for c in node.get("children") or [] if isinstance(c, dict)]
        nxt: Optional[dict[str, Any]] = None
        part_fold = part.casefold()
        for child in children:
            if str(child.get("name") or "").casefold() == part_fold:
                nxt = child
                break
        if nxt is None:
            hits = find_node(node, part, partial=False, global_search=False, scope_node=node)
            nxt = hits[0] if hits else None
        node = nxt
    return node


def resolve_scope_node(
    api: Arborito,
    sess: CliSession,
    *,
    node_path: str = "",
) -> Optional[dict[str, Any]]:
    root = api.tree.root()
    if not root:
        return None
    if node_path:
        hit = find_node_by_path(root, node_path)
        if not hit:
            raise ValueError(f"Node not found: {node_path}")
        return hit
    mid = sess.focus.get("module_id") or ""
    if mid:
        hits = api.tree.find(mid)
        if hits:
            return hits[0]
    lid = sess.focus.get("lesson_id") or ""
    if lid:
        hits = api.tree.find(lid)
        if hits:
            return hits[0]
    return root


def clear_nav_focus(sess: CliSession) -> None:
    """Clear module/lesson focus when switching courses."""
    sess.set_focus(module_id="", module_name="", lesson_id="", lesson_name="")
    sess.focus["node_path"] = ""
    sess._data.pop("focus_undo", None)


def apply_node_focus(
    api: Arborito,
    sess: CliSession,
    node: dict[str, Any],
    *,
    remember_undo: bool = False,
) -> None:
    if remember_undo:
        remember_focus_undo(sess)
    ntype = str(node.get("type") or "")
    if ntype == "branch":
        api.lesson.set_playlist_module(node)
        sess.set_focus(
            module_id=str(node.get("id") or ""),
            module_name=str(node.get("name") or ""),
            lesson_id="",
            lesson_name="",
        )
    elif ntype in ("leaf", "exam"):
        lid = str(node.get("id") or "")
        lesson = api.lesson.by_id(lid)
        title = str((lesson or {}).get("title") or node.get("name") or lid)
        module_id = ""
        module_name = ""
        parent_id = str(node.get("parentId") or "").strip()
        if parent_id:
            hits = api.tree.find(parent_id)
            for h in hits:
                if str(h.get("type") or "") == "branch":
                    module_id = str(h.get("id") or "")
                    module_name = str(h.get("name") or "")
                    break
        if module_id:
            parent = next((h for h in api.tree.find(module_id) if str(h.get("type")) == "branch"), None)
            if parent:
                api.lesson.set_playlist_module(parent)
        sess.set_focus(
            module_id=module_id,
            module_name=module_name,
            lesson_id=lid,
            lesson_name=title,
        )
    elif ntype == "root":
        api.lesson.restore_full_playlist()
        sess.set_focus(
            module_id="",
            module_name="",
            lesson_id="",
            lesson_name="",
        )


def update_node_path(sess: CliSession, api: Arborito) -> None:
    fid = sess.focus.get("lesson_id") or sess.focus.get("module_id") or ""
    if not fid:
        sess.focus["node_path"] = ""
        sess.save()
        return
    root = api.tree.root()
    if not root:
        return
    hits = find_node(root, fid, partial=False, global_search=True)
    if hits:
        sess.focus["node_path"] = str(hits[0].get("path") or hits[0].get("name") or "")
        sess.save()


def truncate_path(path: str, *, max_len: int = 52) -> str:
    """Middle-elide long tree paths while keeping ends readable."""
    path = (path or "").strip()
    if len(path) <= max_len:
        return path
    norm = path.replace(" / ", "/")
    parts = [p.strip() for p in norm.split("/") if p.strip()]
    if len(parts) <= 2:
        return path[: max_len - 1] + "…"
    head = parts[0]
    tail = parts[-1]
    mid = "…"
    out = f"{head}/{mid}/{tail}"
    if len(out) <= max_len:
        return out
    budget = max_len - len(mid) - 2
    h = max(8, budget // 2)
    t = max(8, budget - h - 1)
    return f"{head[:h]}…/{tail[-t:]}"


def format_where_line(sess: CliSession, *, show_full_path: bool = False) -> str:
    f = sess.focus
    tree = f.get("tree_name") or "Tree"
    parts = [f"{FOCUS_ROOT} {tree}"]
    if f.get("module_name"):
        parts.append(f"{FOCUS_MODULE} {f['module_name']}")
    if f.get("lesson_name"):
        parts.append(f"{FOCUS_LESSON} {f['lesson_name']}")
    line = " ➔ ".join(parts)
    path = str(f.get("node_path") or "").strip()
    if path:
        if show_full_path or not sess.config.truncate_paths:
            path_disp = path
        else:
            path_disp = truncate_path(path)
        return f"📍 {line}\n   {path_disp}"
    return f"📍 {line}"


def scope_children(
    api: Arborito,
    sess: CliSession,
    *,
    node_path: str = "",
) -> list[dict[str, Any]]:
    """Direct children at current focus (for numbered list / go N)."""
    try:
        scope = resolve_scope_node(api, sess, node_path=node_path)
    except ValueError:
        return []
    if not scope:
        return []
    return [c for c in scope.get("children") or [] if isinstance(c, dict)]


def format_repl_prompt(sess: CliSession) -> str:
    if sess.repl_mode:
        # Keep cognitive load low: don't echo lesson/module names in the prompt.
        f = sess.focus
        if f.get("lesson_name"):
            return f"{FOCUS_LESSON} Arborito $ "
        if f.get("module_name"):
            return f"{FOCUS_MODULE} Arborito $ "
        if f.get("tree_name"):
            return f"{FOCUS_ROOT} Arborito $ "
        return "arborito $ "
    f = sess.focus
    tree = f.get("tree_name") or "Tree"
    crumbs = [f"{FOCUS_ROOT} {tree}"]
    if f.get("module_name"):
        crumbs.append(f"{FOCUS_MODULE} {f['module_name']}")
    if f.get("lesson_name"):
        crumbs.append(f"{FOCUS_LESSON} {f['lesson_name']}")
    if len(crumbs) == 1:
        return f"{crumbs[0]} $ "
    return f"{' ➔ '.join(crumbs)} $ "

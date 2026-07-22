"""Navigate Arborito course trees (modules, lessons) from in-memory archive data."""

from __future__ import annotations

from typing import Any, Callable, Iterator, Optional

from .cli_emoji import TYPE_EMOJI

NODE_TYPE_ROOT = "root"
NODE_TYPE_BRANCH = "branch"
NODE_TYPE_LEAF = "leaf"
NODE_TYPE_EXAM = "exam"


def node_emoji(node: dict[str, Any]) -> str:
    icon = str(node.get("icon") or "").strip()
    if icon:
        return icon
    return TYPE_EMOJI.get(str(node.get("type") or ""), "•")


def node_summary(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node.get("id"),
        "name": node.get("name"),
        "type": node.get("type"),
        "icon": node.get("icon"),
        "path": node.get("path"),
    }


def walk_tree(
    root: dict[str, Any],
    *,
    type_filter: Optional[set[str]] = None,
) -> Iterator[dict[str, Any]]:
    def _walk(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
        ntype = str(node.get("type") or "")
        if not type_filter or ntype in type_filter:
            yield node
        for child in node.get("children") or []:
            if isinstance(child, dict):
                yield from _walk(child)

    yield from _walk(root)


def find_node(
    root: dict[str, Any],
    identifier: str,
    *,
    partial: bool = False,
    global_search: bool = True,
    scope_node: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    ident = (identifier or "").strip()
    if not ident:
        return []
    ident_fold = ident.casefold()
    start = scope_node if scope_node is not None else root
    matches: list[dict[str, Any]] = []

    for node in walk_tree(start):
        nid = str(node.get("id") or "")
        name = str(node.get("name") or "")
        path = str(node.get("path") or "")
        hay = [nid, name, path, path.split("/")[-1] if path else ""]
        for h in hay:
            if not h:
                continue
            hf = h.casefold()
            if partial:
                if ident_fold in hf:
                    matches.append(node)
                    break
            elif hf == ident_fold or hf.endswith("/" + ident_fold):
                matches.append(node)
                break

    if matches or global_search or scope_node is not None:
        return matches
    return find_node(root, identifier, partial=partial, global_search=True, scope_node=root)


def module_playlist(module_node: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def _collect(node: dict[str, Any]) -> None:
        ntype = str(node.get("type") or "")
        if ntype in (NODE_TYPE_LEAF, NODE_TYPE_EXAM):
            out.append(node)
            return
        for child in node.get("children") or []:
            if isinstance(child, dict):
                _collect(child)

    ntype = str(module_node.get("type") or "")
    if ntype in (NODE_TYPE_LEAF, NODE_TYPE_EXAM):
        return [module_node]
    for child in module_node.get("children") or []:
        if isinstance(child, dict):
            _collect(child)
    return out


def top_modules(root: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        c
        for c in root.get("children") or []
        if isinstance(c, dict) and str(c.get("type") or "") == NODE_TYPE_BRANCH
    ]


def search_nodes(
    root: dict[str, Any],
    query: str,
    *,
    in_content: bool = False,
    lesson_lookup: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
) -> list[dict[str, Any]]:
    q = (query or "").strip().casefold()
    if not q:
        return []
    hits: list[dict[str, Any]] = []
    for node in walk_tree(root):
        name = str(node.get("name") or "").casefold()
        path = str(node.get("path") or "").casefold()
        if q in name or q in path:
            hits.append(node)
            continue
        if in_content and lesson_lookup:
            nid = str(node.get("id") or "")
            lesson = lesson_lookup(nid)
            if lesson:
                body = f"{lesson.get('title') or ''} {lesson.get('text') or ''}".casefold()
                if q in body:
                    hits.append(node)
    return hits


def format_focus_path(
    *,
    tree_name: str = "",
    module_name: str = "",
    lesson_name: str = "",
    truncate: bool = True,
    max_part: int = 28,
) -> str:
    parts: list[tuple[str, str]] = []
    if tree_name:
        parts.append((TYPE_EMOJI["root"], _trunc(tree_name, max_part, truncate)))
    if module_name:
        parts.append((TYPE_EMOJI["branch"], _trunc(module_name, max_part, truncate)))
    if lesson_name:
        parts.append((TYPE_EMOJI["leaf"], _trunc(lesson_name, max_part, truncate)))
    if not parts:
        return ""
    return " › ".join(f"{emo} {label}" for emo, label in parts)


def _trunc(text: str, max_len: int, do: bool) -> str:
    if not do or len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def print_tree_structure(
    node: dict[str, Any],
    *,
    prefix: str = "",
    is_last: bool = True,
    show_emojis: bool = True,
    max_depth: int = 12,
    depth: int = 0,
) -> None:
    if depth > max_depth:
        return
    connector = "└── " if is_last else "├── "
    emo = f"{node_emoji(node)} " if show_emojis else ""
    name = node.get("name") or node.get("id") or "?"
    ntype = node.get("type") or ""
    print(f"{prefix}{connector}{emo}{name} ({ntype})")
    children = [c for c in (node.get("children") or []) if isinstance(c, dict)]
    ext_prefix = prefix + ("    " if is_last else "│   ")
    for i, child in enumerate(children):
        print_tree_structure(
            child,
            prefix=ext_prefix,
            is_last=i == len(children) - 1,
            show_emojis=show_emojis,
            max_depth=max_depth,
            depth=depth + 1,
        )

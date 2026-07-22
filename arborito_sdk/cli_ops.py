"""Shared imperative CLI operations (used by Click commands and REPL)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import click

from .cli_focus import (
    apply_node_focus,
    format_where_line,
    restore_focus_undo,
    resolve_scope_node,
    scope_children,
    truncate_path,
    update_node_path,
)
from .cli_interactive import run_quiz_loop
from .cli_session import CliSession
from .client import Arborito
from .tree_nav import find_node, node_emoji, print_tree_structure, search_nodes


def _parse_go_target(ident: str) -> tuple[bool, str]:
    """Return (is_literal_name, target). Quoted strings are always literal node names."""
    s = (ident or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return True, s[1:-1].strip()
    return False, s


def _go_reserved(ident: str) -> Optional[str]:
    low = ident.casefold()
    if low in ("back", "up", ".."):
        return "back"
    if low == "where":
        return "where"
    return None


def emit_footer(sess: CliSession) -> None:
    if sess.repl_mode:
        return
    path = sess.focus_footer()
    if not path:
        return
    if sess.config.truncate_paths:
        path = truncate_path(path)
    click.echo("-" * 40)
    click.echo(path)


def run_where(sess: CliSession, api: Arborito) -> None:
    update_node_path(sess, api)
    click.echo(format_where_line(sess))


def run_back(sess: CliSession, api: Arborito) -> None:
    if not restore_focus_undo(sess):
        raise click.ClickException("No previous focus.")
    update_node_path(sess, api)
    click.echo("↩️  Restored previous focus.")
    emit_footer(sess)


def run_list(
    sess: CliSession,
    api: Arborito,
    *,
    modules_only: bool = False,
    lessons_only: bool = False,
    as_json: bool = False,
    node_path: str = "",
    tree: bool = False,
) -> None:
    root = api.tree.root()
    if not root:
        raise click.ClickException("No tree structure.")
    if lessons_only:
        run_lesson_list(sess, api, as_json=as_json)
        return
    if modules_only:
        mods = api.tree.modules()
        if as_json:
            click.echo(json.dumps(mods, ensure_ascii=False))
            return
        for i, m in enumerate(mods, 1):
            emo = node_emoji(m) if sess.config.show_emojis else ""
            click.echo(f"  {i}. {emo} {m.get('name')} ({m.get('type') or 'branch'})")
        emit_footer(sess)
        return
    if tree:
        try:
            scope = resolve_scope_node(api, sess, node_path=node_path)
        except ValueError as e:
            raise click.ClickException(str(e)) from e
        node = scope or root
        print_tree_structure(node, show_emojis=sess.config.show_emojis)
        emit_footer(sess)
        return
    children = scope_children(api, sess, node_path=node_path)
    if not children:
        click.echo("(no children at this level — try go -g or list --tree)")
        emit_footer(sess)
        return
    for i, child in enumerate(children, 1):
        emo = node_emoji(child) if sess.config.show_emojis else ""
        click.echo(f"  {i}. {emo} {child.get('name')} ({child.get('type')})")
    emit_footer(sess)


def run_go(
    sess: CliSession,
    api: Arborito,
    identifier: str,
    *,
    label: str = "",
    global_search: bool = False,
    partial: bool = False,
    select: Optional[int] = None,
    remember_undo: bool = True,
) -> None:
    root = api.tree.root()
    if not root:
        raise click.ClickException("No tree.")
    ident = (identifier or "").strip()
    if not ident:
        raise click.ClickException("Usage: go N | NAME | back | where | \"literal name\"")

    literal, target = _parse_go_target(ident)
    if not literal:
        reserved = _go_reserved(target)
        if reserved == "back":
            run_back(sess, api)
            return
        if reserved == "where":
            run_where(sess, api)
            return

    ident = target
    if ident.isdigit() and not global_search:
        n = int(ident)
        children = scope_children(api, sess)
        if 1 <= n <= len(children):
            node = children[n - 1]
            apply_node_focus(api, sess, node, remember_undo=remember_undo)
            update_node_path(sess, api)
            click.echo(f"→ {node_emoji(node)} {node.get('name')}")
            emit_footer(sess)
            return
        lessons = api.lesson.list()
        if 1 <= n <= len(lessons):
            lesson = api.lesson.at(n - 1)
            if lesson:
                lid = str(lesson.get("id") or "")
                hits = api.tree.find(lid) if lid else []
                if hits:
                    apply_node_focus(api, sess, hits[0], remember_undo=remember_undo)
                    update_node_path(sess, api)
                    click.echo(f"→ {node_emoji(hits[0])} {hits[0].get('name')}")
                    emit_footer(sess)
                    return
    scope = None
    if not global_search and sess.focus.get("module_id"):
        hits = api.tree.find(sess.focus["module_id"])
        scope = hits[0] if hits else None
    matches = find_node(root, ident, partial=partial, scope_node=scope)
    if not matches:
        raise click.ClickException(f"Not found: {identifier}")
    if len(matches) > 1:
        if select is None:
            for i, m in enumerate(matches, 1):
                click.echo(f"  {i}. {node_emoji(m)} {m.get('name')} ({m.get('type')})")
            raise click.ClickException("Ambiguous — retry with -s N")
        if select < 1 or select > len(matches):
            raise click.ClickException("Invalid -s index")
        node = matches[select - 1]
    else:
        node = matches[0]
    apply_node_focus(api, sess, node, remember_undo=remember_undo)
    update_node_path(sess, api)
    click.echo(f"→ {node_emoji(node)} {node.get('name')}")
    emit_footer(sess)


def run_search(
    sess: CliSession,
    api: Arborito,
    query: str,
    *,
    in_content: bool = False,
    as_json: bool = False,
) -> None:
    root = api.tree.root()
    if not root:
        raise click.ClickException("No tree.")
    hits = search_nodes(
        root,
        query,
        in_content=in_content,
        lesson_lookup=lambda lid: api.lesson.by_id(lid),
    )
    if as_json:
        click.echo(json.dumps([{"id": h.get("id"), "name": h.get("name"), "type": h.get("type")} for h in hits]))
        return
    for h in hits[:30]:
        click.echo(f"{node_emoji(h)} {h.get('name')} ({h.get('type')})")
    emit_footer(sess)


def run_lesson_list(sess: CliSession, api: Arborito, *, as_json: bool = False) -> None:
    items = api.lesson.list()
    if as_json:
        click.echo(json.dumps(items, ensure_ascii=False))
        return
    for i, meta in enumerate(items, 1):
        lesson = api.lesson.at(i - 1)
        n = len(api.challenge.fromLesson(lesson)) if lesson else 0
        tag = f" ({n} quiz)" if n else ""
        click.echo(f"{i:3d}  {meta['title']}{tag}")
    emit_footer(sess)


def run_lesson_read(
    sess: CliSession,
    api: Arborito,
    identifier: Optional[str] = None,
    *,
    as_json: bool = False,
    raw: bool = False,
) -> None:
    lesson = None
    if identifier is None:
        lid = sess.focus.get("lesson_id")
        if lid:
            lesson = api.lesson.by_id(lid)
    elif identifier.isdigit():
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
        raise click.ClickException("No lesson — go to a leaf or pass an id/title/index.")
    if as_json:
        click.echo(json.dumps(lesson, ensure_ascii=False))
        return
    games = api.content.games(lesson)
    if raw:
        click.echo(f"# {lesson.get('title')}\n")
        body = (lesson.get("raw") or lesson.get("text") or "").strip() or "(empty)"
        click.echo(body)
    else:
        from .lesson_document import format_lesson_for_terminal

        raw_md = str(lesson.get("raw") or lesson.get("text") or "")
        click.echo(format_lesson_for_terminal(raw_md, title=str(lesson.get("title") or "")))
    if games:
        click.echo("\n--- @game ---")
        for g in games:
            g_label = g.get("label") or g.get("url") or "game"
            click.echo(f"  🎮 {g_label}: {g.get('url')}")
    emit_footer(sess)


def run_lesson_games(sess: CliSession, api: Arborito, *, as_json: bool = False) -> None:
    lid = sess.focus.get("lesson_id")
    if not lid:
        raise click.ClickException("No lesson in focus — go to a leaf first.")
    lesson = api.lesson.by_id(lid)
    if not lesson:
        raise click.ClickException("Lesson not loaded.")
    games = api.content.games(lesson)
    if as_json:
        click.echo(json.dumps(games, ensure_ascii=False))
        return
    if not games:
        click.echo("No @game blocks in this lesson.")
        return
    for g in games:
        opt = "optional" if g.get("optional") else "required"
        topics = ", ".join(g.get("topics") or [])
        click.echo(f"🎮 {g.get('label') or g.get('url')} [{opt}]")
        click.echo(f"   {g.get('url')}")
        if topics:
            click.echo(f"   topics: {topics}")
    emit_footer(sess)


def run_ask(
    sess: CliSession,
    api: Arborito,
    question: str,
    *,
    module_name: str = "",
    as_json: bool = False,
) -> None:
    mod = module_name or sess.focus.get("module_name") or ""
    lesson_id = sess.focus.get("lesson_id") or ""
    answer = api.ask.with_context(question, module=mod, lesson_id=lesson_id)
    if as_json:
        click.echo(json.dumps({"answer": answer}))
    else:
        click.echo(answer)
    emit_footer(sess)


def run_info(sess: CliSession, api: Arborito, label: str, *, as_json: bool = False) -> None:
    info = api.tree.info()
    info["label"] = label
    info["ai_mode"] = api.getAIMode()
    if as_json:
        click.echo(json.dumps(info, ensure_ascii=False))
        return
    click.echo(f"🌲 {info.get('name') or label}")
    click.echo(f"   lessons: {info.get('lessons')}")
    click.echo(f"   lang: {info.get('lang')}")
    click.echo(f"   ai: {api.getAIMode()}")
    emit_footer(sess)


def run_quiz(
    sess: CliSession,
    api: Arborito,
    *,
    rounds: int = 5,
    mode: Optional[str] = None,
) -> int:
    return run_quiz_loop(api, rounds, mode, sess=sess)


def run_module_use(sess: CliSession, api: Arborito, name: str) -> None:
    run_go(sess, api, name, remember_undo=True)


def run_fav_list(sess: CliSession) -> None:
    favs = sess.list_favorites()
    if not favs:
        click.echo("No favorites. go fav add at a lesson/module.")
        return
    for i, f in enumerate(favs, 1):
        click.echo(f"  {i}. {f.get('name')} ({f.get('id')})")


def run_fav_add(sess: CliSession) -> None:
    lid = sess.focus.get("lesson_id") or sess.focus.get("module_id")
    name = sess.focus.get("lesson_name") or sess.focus.get("module_name")
    if not lid:
        raise click.ClickException("No focus — go to a node first.")
    sess.add_favorite(lid, name or lid)
    click.echo(f"⭐ {name}")


def run_fav_go(sess: CliSession, api: Arborito, ref: str, *, label: str = "") -> None:
    favs = sess.list_favorites()
    if ref.isdigit():
        n = int(ref)
        if 1 <= n <= len(favs):
            ref = str(favs[n - 1].get("name") or favs[n - 1].get("id") or "")
        else:
            raise click.ClickException(f"Favorite index out of range: {ref}")
    ref_fold = ref.casefold()
    for f in favs:
        if ref_fold in str(f.get("id") or "").casefold() or ref_fold in str(f.get("name") or "").casefold():
            run_go(sess, api, str(f.get("name") or f.get("id") or ""), label=label)
            return
    raise click.ClickException("Favorite not found")


def run_edit(
    sess: CliSession,
    api: Arborito,
    identifier: Optional[str] = None,
    *,
    editor: Optional[str] = None,
    show_only: bool = False,
    no_launch: bool = False,
    raw: bool = False,
) -> None:
    """Edit lesson with enriched TUI (default) or raw ``$EDITOR`` markdown."""
    import os
    import subprocess
    import tempfile

    from .lesson_write import resolve_lesson, save_lesson_raw

    try:
        lesson = resolve_lesson(api, sess, identifier)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    raw_md = str(lesson.get("raw") or lesson.get("text") or "")
    lid = str(lesson.get("id") or "")
    if show_only:
        if raw:
            click.echo(raw_md)
        else:
            from .lesson_document import format_lesson_for_terminal

            click.echo(format_lesson_for_terminal(raw_md, title=str(lesson.get("title") or "")))
        emit_footer(sess)
        return
    if no_launch:
        click.echo(raw_md, nl=False)
        return
    if not getattr(api, "_source_path", None):
        raise click.ClickException(
            "Edit needs a local .arborito file. Nostr/read-only: fork locally in Arborito first."
        )

    if raw:
        import shlex

        ed = editor or os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
        cmd = shlex.split(ed) if ed.strip() else ["nano"]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", prefix="arborito-lesson-", encoding="utf-8", delete=False
        ) as tf:
            tf.write(raw_md)
            tmp_path = tf.name
        try:
            subprocess.run([*cmd, tmp_path], check=False)
            new_raw = Path(tmp_path).read_text(encoding="utf-8")
            if new_raw == raw_md:
                click.echo("Unchanged.")
                return
            entry = save_lesson_raw(api, lid, new_raw)
            click.echo(f"✅ Saved {entry}")
            emit_footer(sess)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        return

    from .cli_lesson_editor import run_lesson_editor_fallback, run_lesson_editor_tui

    try:
        run_lesson_editor_tui(api, lid, raw_md)
        emit_footer(sess)
    except ImportError:
        click.echo(
            "💡 Full UI: pip install 'arborito-sdk[tui]'  (editor with F2–F5 buttons)\n"
            "   Raw markdown: edit --raw\n"
        )
        run_lesson_editor_fallback(api, lid, raw_md)
        emit_footer(sess)


run_read = run_lesson_read


def repl_help_text() -> str:
    from .cli_emoji import CMD_EMOJI as E

    return f"""{E['shell']} Shell help

🧭 Basics
  {E['help']} help
  {E['exit']} exit

🗺️ Navigate
  {E['list']} list
  {E['go']} go
  {E['back']} back
  {E['where']} where

📖 Lesson & study
  {E['read']} read
  {E['edit']} edit          enriched TUI (F2 Quiz, F3 Section…) — edit --raw for $EDITOR
  {E['games']} games
  {E['info']} info
  {E['search']} search
  {E['quiz']} quiz
  {E['ask']} ask
  {E['memory']} memory

🌿 Library
  {E['branch']} branch
  {E['tree']} tree
  {E['cp']} cp
  {E['fav']} fav

👤 Account & settings
  {E['session']} session
  {E['config']} config

🖥️ System commands
  Type OS commands directly (e.g. `ls`, `pwd`, `python --version`).

Tip: inside the shell, use `help` (not `-h/--help`)."""

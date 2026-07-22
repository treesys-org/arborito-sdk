"""Interactive REPL — ``arborito-cli shell`` / ``arborito-cli course.arborito``."""

from __future__ import annotations

import shlex
import difflib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

import click

from .cli_focus import format_repl_prompt, update_node_path
from .cli_ops import (
    repl_help_text,
    run_ask,
    run_edit,
    run_go,
    run_lesson_games,
    run_list,
    run_quiz,
    run_read,
    run_search,
)
from .cli_session import CliSession

_REPL_META = frozenset(
    {
        "help",
        "-h",
        "--help",
        "exit",
        "quit",
        "branch",
        "tree",
        "session",
        "config",
        "forest",
        "bosque",
    }
)


def _load_course(sess: CliSession, path: Path):
    from .cli_app import _load_api

    return _load_api(sess, path=path)


def _reload_ctx(sess: CliSession, ctx: dict[str, Any], relays: tuple[str, ...]) -> None:
    from .cli_app import _effective_relays, _load_api

    eff = _effective_relays(sess, relays)
    ctx["api"], ctx["label"] = _load_api(sess, relays=eff)
    update_node_path(sess, ctx["api"])


def _needs_course(cmd: str) -> bool:
    return cmd not in _REPL_META


def _known_commands() -> list[str]:
    return [
        "help",
        "exit",
        "list",
        "go",
        "back",
        "where",
        "read",
        "edit",
        "games",
        "info",
        "search",
        "quiz",
        "ask",
        "branch",
        "tree",
        "cp",
        "fav",
        "session",
        "config",
        "forest",
        "bosque",
    ]


def _suggest_command(cmd: str) -> str:
    cmd = (cmd or "").strip().lower()
    if not cmd:
        return ""
    hits = difflib.get_close_matches(cmd, _known_commands(), n=1, cutoff=0.6)
    return hits[0] if hits else ""


def _parse_flags(argv: list[str]) -> tuple[list[str], dict[str, Any]]:
    flags: dict[str, Any] = {}
    rest: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in ("-g", "--global-search"):
            flags["global_search"] = True
        elif tok in ("-p", "--partial"):
            flags["partial"] = True
        elif tok in ("-c", "--content"):
            flags["content"] = True
        elif tok == "--modules":
            flags["modules_only"] = True
        elif tok == "--lessons":
            flags["lessons_only"] = True
        elif tok == "--tree":
            flags["tree"] = True
        elif tok == "--show":
            flags["show_only"] = True
        elif tok == "--raw":
            flags["raw"] = True
        elif tok == "--editor":
            i += 1
            if i < len(argv):
                flags["editor"] = argv[i]
        elif tok == "--rounds":
            i += 1
            if i < len(argv):
                flags["rounds"] = int(argv[i])
        elif tok == "--mode":
            i += 1
            if i < len(argv):
                flags["mode"] = argv[i]
        elif tok in ("-s", "--select"):
            i += 1
            if i < len(argv):
                flags["select"] = int(argv[i])
        elif not tok.startswith("-"):
            rest.append(tok)
        i += 1
    return rest, flags


def _dispatch(sess: CliSession, ctx: dict[str, Any], line: str) -> bool:
    line = line.strip()
    if not line:
        return True
    try:
        parts = shlex.split(line)
    except ValueError as e:
        click.echo(f"Parse error: {e}", err=True)
        return True
    if not parts:
        return True

    # If TAB just showed a completion menu and the user hits Enter on a bare group
    # command (e.g. `tree `), don't immediately print the group's help again.
    if ctx.get("_completion_shown") and len(parts) == 1 and parts[0].lower() in (
        "tree",
        "branch",
        "session",
        "config",
        "fav",
        "cp",
    ):
        ctx["_completion_shown"] = False
        return True

    ctx["_completion_shown"] = False

    # Shell convenience: map -h/--help to help, but preserve subcommand help.
    if any(p in ("-h", "--help") for p in parts):
        # `branch --help` → same as typing `branch`
        head = parts[0].lower() if parts else ""
        if head and head not in ("-h", "--help") and len(parts) >= 2:
            parts = [parts[0]]
        else:
            click.echo(repl_help_text())
            return True

    cmd = parts[0].lower()
    if cmd in ("forest", "bosque"):
        parts = ["branch", "list"]
        cmd = "branch"

    api = ctx.get("api")
    label = ctx.get("label") or ""

    # If it's not an Arborito command, try running it as a system command first.
    # This keeps the REPL feeling like a real shell (ls/pwd/python/etc).
    if cmd not in _known_commands():
        exe = shutil.which(parts[0])
        if exe:
            try:
                p = subprocess.run(parts, check=False, text=True, capture_output=True)
            except Exception as e:
                click.echo(f"Error: failed to run system command: {e}", err=True)
                return True
            if p.stdout:
                click.echo(p.stdout.rstrip("\n"))
            if p.stderr:
                click.echo(p.stderr.rstrip("\n"), err=True)
            return True

    if api is None and _needs_course(cmd):
        click.echo("No course loaded.")
        click.echo("Try: branch import · branch add · branch list · tree import")
        return True

    if cmd in ("exit", "quit"):
        return False
    if cmd == "help":
        click.echo(repl_help_text())
        return True
    if cmd == "session" and len(parts) == 1:
        from .cli_emoji import CMD_EMOJI, SUB_EMOJI
        click.echo(f"{CMD_EMOJI['session']} session")
        click.echo(f"  {SUB_EMOJI['login']} login")
        click.echo(f"  {SUB_EMOJI['logout']} logout")
        click.echo(f"  {SUB_EMOJI['whoami']} whoami")
        return True
    if cmd == "branch" and len(parts) == 1:
        from .cli_emoji import CMD_EMOJI, SUB_EMOJI
        click.echo(f"{CMD_EMOJI['branch']} branch")
        click.echo(f"  {SUB_EMOJI['list']} list")
        click.echo(f"  {SUB_EMOJI['open']} open")
        click.echo(f"  {SUB_EMOJI['add']} add")
        click.echo(f"  {SUB_EMOJI['import']} import")
        click.echo(f"  {SUB_EMOJI['export']} export")
        click.echo(f"  {SUB_EMOJI['remove']} remove")
        click.echo(f"  {SUB_EMOJI['new']} new")
        click.echo(f"  {SUB_EMOJI['publish']} publish")
        return True
    if cmd == "tree" and len(parts) == 1:
        from .cli_emoji import CMD_EMOJI, SUB_EMOJI
        click.echo(f"{CMD_EMOJI['tree']} tree")
        click.echo(f"  {SUB_EMOJI['list']} list")
        click.echo(f"  {SUB_EMOJI['open']} open")
        click.echo(f"  {SUB_EMOJI['import']} import")
        click.echo(f"  {SUB_EMOJI['export']} export")
        click.echo(f"  {SUB_EMOJI['remove']} remove")
        click.echo(f"  {SUB_EMOJI['publish']} publish")
        return True
    if cmd == "config" and len(parts) == 1:
        click.echo("⚙️ config")
        click.echo("  ⚙️ relay")
        click.echo("  ⚙️ ai")
        return True
    if cmd == "fav" and len(parts) == 1:
        from .cli_emoji import CMD_EMOJI, SUB_EMOJI
        click.echo(f"{CMD_EMOJI['fav']} fav")
        click.echo(f"  {SUB_EMOJI['list']} list")
        click.echo(f"  {SUB_EMOJI['add']} add")
        click.echo(f"  {SUB_EMOJI['go']} go")
        click.echo(f"  {SUB_EMOJI['remove']} remove")
        return True
    if cmd == "cp" and len(parts) == 1:
        from .cli_emoji import CMD_EMOJI
        click.echo(f"{CMD_EMOJI['cp']} cp")
        click.echo(f"  {CMD_EMOJI['branch']} branch")
        click.echo(f"  {CMD_EMOJI['tree']} tree")
        return True
    if cmd == "list":
        _rest, flags = _parse_flags(parts[1:])
        run_list(
            sess,
            api,
            modules_only=bool(flags.get("modules_only")),
            lessons_only=bool(flags.get("lessons_only")),
            tree=bool(flags.get("tree")),
        )
        return True
    if cmd == "go":
        rest, flags = _parse_flags(parts[1:])
        ident = " ".join(rest).strip()
        if not ident:
            click.echo('Usage: go N | NAME | back | where | "literal"', err=True)
            return True
        run_go(
            sess,
            api,
            ident,
            label=label,
            global_search=bool(flags.get("global_search")),
            partial=bool(flags.get("partial")),
            select=flags.get("select"),
        )
        return True
    if cmd in ("where", "back"):
        run_go(sess, api, cmd, label=label)
        return True
    if cmd == "info":
        from .cli_ops import run_info

        run_info(sess, api, label)
        return True
    if cmd == "read":
        rest, _flags = _parse_flags(parts[1:])
        ident: Optional[str] = " ".join(rest).strip() or None
        run_read(sess, api, ident)
        return True
    if cmd == "edit":
        rest, flags = _parse_flags(parts[1:])
        ident = " ".join(rest).strip() or None
        run_edit(
            sess,
            api,
            ident,
            show_only=bool(flags.get("show_only")),
            raw=bool(flags.get("raw")),
            editor=flags.get("editor"),
        )
        return True
    if cmd == "games":
        run_lesson_games(sess, api)
        return True
    if cmd == "search":
        rest, flags = _parse_flags(parts[1:])
        query = " ".join(rest).strip()
        if not query:
            click.echo("Usage: search QUERY [-c]", err=True)
            return True
        run_search(sess, api, query, in_content=bool(flags.get("content")))
        return True
    if cmd == "ask":
        rest, _flags = _parse_flags(parts[1:])
        question = " ".join(rest).strip()
        if not question:
            click.echo('Usage: ask "your question"', err=True)
            return True
        run_ask(sess, api, question)
        return True
    if cmd == "quiz":
        _rest, flags = _parse_flags(parts[1:])
        run_quiz(sess, api, rounds=int(flags.get("rounds") or 5), mode=flags.get("mode"))
        return True
    if cmd == "branch" and len(parts) >= 2:
        from .cli_library import (
            branch_add,
            branch_import,
            branch_new,
            export_entry,
            list_branches,
            open_branch,
            remove_entry,
        )

        sub = parts[1].lower()
        rest, _flags = _parse_flags(parts[2:])
        relays = tuple(ctx.get("relays") or ())
        if sub == "list":
            list_branches(sess, as_json=False)
        elif sub == "add":
            code = " ".join(rest).strip()
            if code:
                api2, label2 = branch_add(sess, code, relays=list(relays))
                ctx["api"], ctx["label"] = api2, label2
                update_node_path(sess, ctx["api"])
        elif sub == "open":
            ref = " ".join(rest).strip() or None
            e = open_branch(sess, ref)
            click.echo(f"Active: {e.get('name')}")
            _reload_ctx(sess, ctx, relays)
        elif sub == "import":
            path = " ".join(rest).strip()
            if path:
                branch_import(sess, path)
                _reload_ctx(sess, ctx, relays)
        elif sub == "new":
            name = " ".join(rest).strip() or "Draft"
            out = branch_new(sess, name)
            click.echo(f"Created: {out}")
            _reload_ctx(sess, ctx, relays)
        elif sub == "export":
            if len(rest) < 2:
                click.echo("Usage: branch export NAME DEST", err=True)
            else:
                dest = rest[-1]
                ref = " ".join(rest[:-1])
                out = export_entry(sess, "branch", ref, dest)
                click.echo(f"Exported: {out}")
        elif sub == "remove":
            ref = " ".join(rest).strip()
            if not ref:
                click.echo("Usage: branch remove NAME", err=True)
            else:
                e = remove_entry(sess, "branch", ref)
                click.echo(f"Removed: {e.get('name')}")
        elif sub == "publish":
            from .branch_publish import publish_branch
            from .cli_app import _effective_relays

            ref = " ".join(rest).strip() or None
            try:
                out = publish_branch(
                    sess,
                    ref,
                    relays=_effective_relays(sess, relays),
                    author=str(sess.user.get("username") or "CLI"),
                    description="Published from arborito-cli shell",
                )
                click.echo(f"Published: {out.get('url')} code={out.get('share_code')}")
                _reload_ctx(sess, ctx, relays)
            except Exception as exc:
                click.echo(str(exc), err=True)
        else:
            click.echo(f"Unknown branch subcommand: {sub}", err=True)
        return True
    if cmd == "tree" and len(parts) >= 2:
        from .cli_library import export_entry, list_trees, open_tree, remove_entry, tree_import

        sub = parts[1].lower()
        rest, _flags = _parse_flags(parts[2:])
        relays = tuple(ctx.get("relays") or ())
        if sub == "list":
            list_trees(sess, as_json=False)
        elif sub == "open":
            ref = " ".join(rest).strip() or None
            e = open_tree(sess, ref)
            click.echo(f"Active: {e.get('name')}")
            _reload_ctx(sess, ctx, relays)
        elif sub == "import":
            path = " ".join(rest).strip()
            if path:
                tree_import(sess, path)
                _reload_ctx(sess, ctx, relays)
        elif sub == "export":
            if len(rest) < 2:
                click.echo("Usage: tree export NAME DEST", err=True)
            else:
                dest = rest[-1]
                ref = " ".join(rest[:-1])
                out = export_entry(sess, "tree", ref, dest)
                click.echo(f"Exported: {out}")
        elif sub == "remove":
            ref = " ".join(rest).strip()
            if not ref:
                click.echo("Usage: tree remove NAME", err=True)
            else:
                e = remove_entry(sess, "tree", ref)
                click.echo(f"Removed: {e.get('name')}")
        else:
            click.echo(f"Unknown tree subcommand: {sub}", err=True)
        return True
    if cmd == "cp" and len(parts) >= 3:
        from .cli_app import cmd_cp

        cmd_cp.callback(sess, parts[1].lower(), " ".join(parts[2:]).strip())
        return True
    if cmd == "fav" and len(parts) >= 2:
        from .cli_ops import run_fav_add, run_fav_go, run_fav_list

        sub = parts[1].lower()
        rest, _flags = _parse_flags(parts[2:])
        if sub == "list":
            run_fav_list(sess)
        elif sub == "add":
            run_fav_add(sess)
        elif sub == "remove":
            ref = " ".join(rest).strip()
            if ref and not sess.remove_favorite(ref):
                click.echo("Favorite not found.", err=True)
            elif ref:
                click.echo("Removed.")
        elif sub == "go":
            ref = " ".join(rest).strip()
            if ref:
                run_fav_go(sess, api, ref, label=label)
        return True
    if cmd == "session" and len(parts) >= 2:
        from .cli_app import session_login, session_logout, session_whoami

        sub = parts[1].lower()
        rest, _flags = _parse_flags(parts[2:])
        if sub == "whoami":
            session_whoami.callback(sess, False)
        elif sub == "logout":
            session_logout.callback(sess)
        elif sub == "login":
            user = " ".join(rest).strip()
            if user:
                secret = click.prompt("Secret", hide_input=True)
                session_login.callback(sess, user, secret, tuple())
        return True
    if cmd == "config" and len(parts) >= 3:
        from .cli_app import (
            config_ai_list,
            config_ai_set,
            config_relay_list,
            config_relay_reset,
            config_relay_set,
        )

        area = parts[1].lower()
        sub = parts[2].lower()
        rest, _flags = _parse_flags(parts[3:])
        if area == "relay":
            if sub == "list":
                config_relay_list.callback(sess)
            elif sub == "set" and rest:
                config_relay_set.callback(sess, tuple(rest))
            elif sub == "reset":
                config_relay_reset.callback(sess)
        elif area == "ai":
            if sub == "list":
                config_ai_list.callback(sess)
            elif sub == "set" and len(rest) >= 2:
                config_ai_set.callback(sess, rest[0], rest[1])
        return True

    s = _suggest_command(cmd)
    if s:
        click.echo(f"Unknown: {cmd!r}. Did you mean: {s} ?", err=True)
    else:
        click.echo(f"Unknown: {cmd!r}. Type help.", err=True)
    return True


def _repl_banner(sess: CliSession, *, loaded: bool, label: str) -> None:
    from .cli_emoji import CMD_EMOJI, COMPOSED_TREE

    if loaded and label:
        click.echo(f"{COMPOSED_TREE} {label}")
    else:
        click.echo(f"{CMD_EMOJI['shell']} Arborito shell (empty)")
        click.echo(f"  {CMD_EMOJI['branch']} branch import")
        click.echo(f"  {CMD_EMOJI['branch']} branch add")
        click.echo(f"  {CMD_EMOJI['branch']} branch list")
        click.echo(f"  {CMD_EMOJI['tree']} tree import")
    click.echo(f"  {CMD_EMOJI['help']} help")
    click.echo(f"  {CMD_EMOJI['exit']} exit\n")


def _repl_loop(
    sess: CliSession,
    api: Any,
    label: str,
    *,
    relays: tuple[str, ...] = (),
) -> int:
    sess.repl_mode = True
    ctx: dict[str, Any] = {"api": api, "label": label, "relays": relays, "_completion_shown": False}
    if api is not None:
        update_node_path(sess, api)
    _repl_banner(sess, loaded=api is not None, label=label)
    _install_tab_completion(ctx)
    while True:
        try:
            # Expose the live prompt to the completion display hook so it can
            # redraw the prompt + buffer after printing candidates.
            ctx["_prompt"] = format_repl_prompt(sess)
            line = input(ctx["_prompt"])
        except (EOFError, KeyboardInterrupt):
            click.echo()
            break
        try:
            if not _dispatch(sess, ctx, line):
                break
        except click.ClickException as e:
            click.echo(f"Error: {e.message}", err=True)
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
    sess.repl_mode = False
    click.echo("Bye.")
    return 0


def _install_tab_completion(ctx: dict[str, Any]) -> None:
    """Best-effort TAB completion (readline on Unix)."""
    try:
        import readline  # type: ignore
    except Exception:
        return

    from .cli_emoji import CMD_EMOJI as _EMOJI_CMD, SUB_EMOJI as _EMOJI_SUB

    def _subcommands_for(head: str) -> list[str]:
        head = (head or "").lower()
        if head == "branch":
            return ["list", "open", "add", "import", "export", "remove", "new", "publish"]
        if head == "tree":
            return ["list", "open", "import", "export", "remove", "publish"]
        if head == "fav":
            return ["list", "add", "go", "remove"]
        if head == "session":
            return ["login", "logout", "whoami"]
        if head == "config":
            return ["relay", "ai"]
        if head == "cp":
            return ["branch", "tree"]
        return []

    def _completions(buf: str, text: str, begidx: int) -> list[str]:
        # readline's `text` is the token prefix being completed.
        if begidx == 0:
            prefix = (text or "").lower()
            return [c for c in _known_commands() if c.startswith(prefix)]
        parts = (buf or "").lstrip().split()
        head = parts[0].lower() if parts else ""

        # Filename completion for: branch import <PATH> / tree import <PATH>
        if head in ("branch", "tree") and len(parts) >= 2 and parts[1].lower() == "import":
            # completing PATH token (3rd token)
            if len(parts) >= 3:
                # If user already finished a path token and is starting another, don't spam.
                if (buf or "").endswith(" ") and not (text or ""):
                    return []
                prefix_raw = text or ""
                prefix = os.path.expanduser(prefix_raw)
                base_dir = os.path.dirname(prefix) if os.path.dirname(prefix) else "."
                base_name = os.path.basename(prefix)
                try:
                    entries = os.listdir(base_dir)
                except Exception:
                    return []
                out: list[str] = []
                for e in entries:
                    if base_name and not e.startswith(base_name):
                        continue
                    full = os.path.join(base_dir, e)
                    if os.path.isdir(full):
                        out.append(e + "/")
                    elif e.lower().endswith(".arborito"):
                        out.append(e)
                return sorted(out)[:200]

        subs = _subcommands_for(head)
        if not subs:
            return []
        # If the user already completed the subcommand and is starting a new token,
        # don't spam suggestions for unrelated subcommands.
        if (buf or "").endswith(" ") and len(parts) >= 2 and not (text or ""):
            return []
        prefix = (text or "").lower()
        return [s for s in subs if s.startswith(prefix)]

    matches: list[str] = []

    def completer(text: str, state: int) -> Optional[str]:
        nonlocal matches
        if state == 0:
            buf = readline.get_line_buffer()
            begidx = 0
            try:
                begidx = int(readline.get_begidx())
            except Exception:
                begidx = 0
            # de-dup while preserving order
            matches = list(dict.fromkeys(_completions(buf, text, begidx)))
        try:
            return matches[state]
        except Exception:
            return None

    try:
        readline.set_completer(completer)
        readline.parse_and_bind("tab: complete")
        # Avoid confusing auto-space / inconsistent UI after completion.
        try:
            readline.set_completion_append_character("")  # pyreadline/readline
        except Exception:
            try:
                readline.parse_and_bind('set completion-append-character ""')
            except Exception:
                pass
        # Prefer showing choices instead of mutating the line.
        try:
            readline.parse_and_bind("set show-all-if-ambiguous on")
        except Exception:
            pass
        # Show emojis in completion candidates, but keep a compact column layout.
        def _display_matches(substitution, matches2, longest_match_length):  # noqa: ANN001
            ctx["_completion_shown"] = True
            try:
                buf = readline.get_line_buffer()
                begidx = int(readline.get_begidx())
            except Exception:
                buf = ""
                begidx = 0
            parts = (buf or "").lstrip().split()
            head = parts[0].lower() if parts else ""
            is_sub = begidx > 0

            def fmt(tok: str) -> str:
                if not is_sub:
                    emo = _EMOJI_CMD.get(tok.lower(), "•")
                    return f"{emo} {tok}"
                emo = _EMOJI_SUB.get(tok.lower(), _EMOJI_CMD.get(head, "•"))
                return f"{emo} {tok}"

            items = [fmt(str(m)) for m in matches2]
            if not items:
                return
            width = max(len(s) for s in items) + 2
            # terminal columns: best-effort; default to 80
            cols = 80
            try:
                import shutil

                cols = shutil.get_terminal_size((80, 20)).columns
            except Exception:
                cols = 80
            per_row = max(1, cols // max(1, width))

            # Start completion list on a fresh line, but avoid double blank lines.
            import sys
            sys.stdout.write("\n")
            row = []
            for it in items:
                row.append(it.ljust(width))
                if len(row) >= per_row:
                    sys.stdout.write("".join(row).rstrip() + "\n")
                    row = []
            if row:
                sys.stdout.write("".join(row).rstrip() + "\n")
            try:
                sys.stdout.flush()
            except Exception:
                pass
            # Redraw prompt + buffer so the cursor isn't left "below".
            # Prefer doing it ourselves because some terminals don't reliably
            # restore the cursor with redisplay after custom printing.
            try:
                prompt = str(ctx.get("_prompt") or "")
                buf2 = readline.get_line_buffer()
                # Clear line, then print prompt + buffer.
                sys.stdout.write("\r\x1b[2K" + prompt + buf2)
                sys.stdout.flush()
            except Exception:
                try:
                    readline.on_new_line()
                    readline.redisplay()
                except Exception:
                    pass

        try:
            readline.set_completion_display_matches_hook(_display_matches)
        except Exception:
            pass
    except Exception:
        return


def run_repl(sess: CliSession, course_path: Path) -> int:
    api, label = _load_course(sess, course_path)
    return _repl_loop(sess, api, label)


def run_repl_from_session(
    sess: CliSession,
    *,
    relays: Optional[list[str]] = None,
    fresh: bool = False,
) -> int:
    """Interactive shell. ``fresh=True`` starts without loading the last course."""
    from .cli_app import _effective_relays, _load_api

    eff = _effective_relays(sess, tuple(relays or ()))
    if fresh:
        return _repl_loop(sess, None, "", relays=eff)
    try:
        api, label = _load_api(sess, relays=eff)
    except click.ClickException:
        return _repl_loop(sess, None, "", relays=eff)
    return _repl_loop(sess, api, label, relays=eff)

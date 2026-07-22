"""Click CLI — navigation, session, Arborito SDK."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import click

from . import __version__
from .cli_session import CliSession
from .cli_emoji import DEFAULT_AVATAR
from .client import Arborito
from .errors import ArboritoError
from .nostr_protocol import normalize_tree_share_code
from .session_nostr import login_with_secret
from .cli_interactive import run_quiz_loop
from .cli_ops import (
    emit_footer,
    run_ask,
    run_edit,
    run_go,
    run_lesson_games,
    run_lesson_read,
    run_list,
    run_read,
    run_search,
)
from .tree_nav import node_emoji

_CLI_COMMAND_ORDER = [
    "help",
    "go",
    "list",
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
    "memory",
    "session",
    "config",
    "script",
]


class _SDKGroup(click.Group):
    def list_commands(self, ctx: click.Context) -> list[str]:
        known = set(super().list_commands(ctx))
        ordered = [c for c in _CLI_COMMAND_ORDER if c in known]
        for c in sorted(known - set(ordered)):
            ordered.append(c)
        return ordered


pass_session = click.make_pass_decorator(CliSession)
pass_json = click.pass_context

# Reuse loaded courses within one CLI process (REPL, ``script run``).
_PROCESS_API_CACHE: dict[str, tuple[Arborito, str]] = {}


def _api_cache_key(
    *,
    path: Optional[Path] = None,
    code: Optional[str] = None,
    nref: Optional[dict[str, str]] = None,
    lang: str,
) -> Optional[str]:
    if path:
        return f"path:{path.resolve()}:{lang}"
    if code:
        norm = normalize_tree_share_code(code) or code
        return f"code:{norm}:{lang}"
    if nref and nref.get("pub") and nref.get("universe_id"):
        return f"nostr:{str(nref['pub']).lower()}:{nref['universe_id']}:{lang}"
    return None


def _api_cache_get(key: Optional[str]) -> Optional[tuple[Arborito, str]]:
    if not key:
        return None
    return _PROCESS_API_CACHE.get(key)


def _api_cache_put(key: Optional[str], api: Arborito, label: str) -> None:
    if key:
        _PROCESS_API_CACHE[key] = (api, label)


def _emit(data: Any, *, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False))
    elif isinstance(data, str):
        click.echo(data)


def _footer(sess: CliSession) -> None:
    emit_footer(sess)


def _nostr_ref_from_session(sess: CliSession) -> Optional[dict[str, str]]:
    ref = sess.get_nostr_ref()
    if ref:
        return ref
    entry = sess.active_library_entry()
    if entry:
        raw = entry.get("nostr_ref")
        if isinstance(raw, dict) and raw.get("pub") and raw.get("universe_id"):
            return {
                "pub": str(raw["pub"]).lower(),
                "universe_id": str(raw["universe_id"]),
            }
    return None


def _effective_relays(sess: CliSession, cli_relays: tuple[str, ...] | list[str] | None) -> list[str]:
    from .nostr_relays import default_nostr_relays, merge_nostr_relay_urls

    base = sess.get_relays() or default_nostr_relays()
    if cli_relays:
        return merge_nostr_relay_urls(base, cli_relays)
    return list(base)


def _auto_sync(sess: CliSession) -> None:
    """Pull/push progress when logged in (no user-facing command)."""
    from .progress_sync import auto_sync

    auto_sync(sess)


def _after_network_load(api: Arborito, sess: CliSession) -> None:
    if getattr(api, "_nostr_ref", None):
        try:
            api.refresh()
        except Exception:
            pass
    _auto_sync(sess)


def _sync_course_focus(sess: CliSession, *, source: str, tree_name: str) -> None:
    """Update course source; clear module/lesson only when the course changes."""
    from .cli_focus import clear_nav_focus

    prev = str(sess.focus.get("source") or "")
    src = str(source or "")
    same = prev == src or (
        prev
        and src
        and Path(prev).is_file()
        and Path(src).is_file()
        and Path(prev).resolve() == Path(src).resolve()
    )
    if not same:
        clear_nav_focus(sess)
    sess.set_focus(source=src, tree_name=tree_name)
    sess.save()


def _load_api(
    sess: CliSession,
    *,
    path: Optional[Path] = None,
    code: Optional[str] = None,
    nref: Optional[dict[str, str]] = None,
    relays: Optional[list[str]] = None,
) -> tuple[Arborito, str]:
    lang = sess.lang
    if path:
        if not path.is_file():
            raise click.ClickException(f"Not found: {path}")
        key = _api_cache_key(path=path, lang=lang)
        hit = _api_cache_get(key)
        label = path.name
        if hit:
            api, cached_label = hit
            _sync_course_focus(
                sess,
                source=str(path.resolve()),
                tree_name=api.tree.info().get("name") or cached_label or label,
            )
            return api, cached_label
        api = Arborito.from_arborito(path, lang=lang, username="cli", avatar=DEFAULT_AVATAR)
        label = path.name
        _sync_course_focus(
            sess,
            source=str(path.resolve()),
            tree_name=api.tree.info().get("name") or label,
        )
        _api_cache_put(key, api, label)
        return api, label
    if code:
        key = _api_cache_key(code=code, lang=lang)
        hit = _api_cache_get(key)
        if hit:
            api, cached_label = hit
            norm = normalize_tree_share_code(code) or code
            _sync_course_focus(sess, source=f"share:{norm}", tree_name=cached_label)
            return hit
        api = Arborito.from_share_code(code, lang=lang, relays=relays, username="cli", avatar=DEFAULT_AVATAR)
        norm = normalize_tree_share_code(code) or code
        label = f"share:{norm}"
        info = api.tree.info()
        nr = getattr(api, "_nostr_ref", None)
        sess.register_branch(
            branch_id=str(info.get("id") or norm),
            name=str(info.get("name") or norm),
            source=label,
            share_code=norm,
            nostr_ref=nr if isinstance(nr, dict) else None,
        )
        _sync_course_focus(sess, source=label, tree_name=str(info.get("name") or norm))
        if nr and nr.get("pub"):
            sess.set_nostr_ref(nr["pub"], nr.get("universe_id") or "")
        sess.save()
        _after_network_load(api, sess)
        _api_cache_put(key, api, label)
        return api, label
    if nref and nref.get("pub") and nref.get("universe_id"):
        key = _api_cache_key(nref=nref, lang=lang)
        hit = _api_cache_get(key)
        if hit:
            api, cached_label = hit
            _sync_course_focus(
                sess,
                source=str(sess.focus.get("source") or cached_label),
                tree_name=cached_label,
            )
            return hit
        api = Arborito.from_nostr(
            nref["pub"],
            nref["universe_id"],
            lang=lang,
            relays=relays,
            username="cli",
            avatar=DEFAULT_AVATAR,
        )
        label = f"share:{nref.get('universe_id', '')[:8]}"
        info = api.tree.info()
        _sync_course_focus(
            sess,
            source=str(sess.focus.get("source") or label),
            tree_name=str(info.get("name") or label),
        )
        _after_network_load(api, sess)
        _api_cache_put(key, api, info.get("name") or label)
        return api, info.get("name") or label

    src = sess.focus.get("source") or ""
    study = str(sess.focus.get("study_source") or "").strip()
    if study and Path(study).is_file():
        return _load_api(sess, path=Path(study), relays=relays)
    # Prefer a local archive over a stale nostr_ref left after publish.
    if src and Path(src).is_file():
        return _load_api(sess, path=Path(src), relays=relays)
    if src.startswith("share:"):
        c = src.split(":", 1)[1]
        return _load_api(sess, code=c, relays=relays)
    if src.startswith("nostr:") or _nostr_ref_from_session(sess):
        ref = _nostr_ref_from_session(sess)
        if ref:
            return _load_api(sess, nref=ref, relays=relays)
        raise click.ClickException("Incomplete network ref. branch add CODE")

    for entry in reversed(sess.list_branches() + sess.list_trees()):
        src2 = entry.get("source") or ""
        if Path(src2).is_file():
            return _load_api(sess, path=Path(src2), relays=relays)
        if src2.startswith("share:"):
            return _load_api(sess, code=src2.split(":", 1)[1], relays=relays)
        nref2 = entry.get("nostr_ref")
        if isinstance(nref2, dict) and nref2.get("pub"):
            return _load_api(sess, nref=nref2, relays=relays)

    raise click.ClickException(
        "No course loaded. branch add CODE, branch import file.arborito, or pass a path."
    )


def _source_opts(fn):
    opts = [
        click.option("--lang", default=None, help="Course language (ES, EN, …)."),
        click.argument(
            "arborito",
            required=False,
            type=click.Path(exists=False, path_type=Path),
        ),
        click.option("--code", metavar="XXXX-XXXX"),
        click.option("--relay", "relays", multiple=True, metavar="wss://…"),
        click.option("--json", "as_json", is_flag=True, help="JSON output."),
    ]
    for o in reversed(opts):
        fn = o(fn)
    return fn


def _list_opts(fn):
    """Source opts plus --node (only honored by ``list``)."""
    fn = click.option(
        "--node",
        "focus_node",
        default="",
        metavar="PATH",
        help="Scope to tree path.",
    )(fn)
    return _source_opts(fn)


@click.group(cls=_SDKGroup, invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.pass_context
@click.version_option(__version__, prog_name="arborito-cli")
def cli(ctx: click.Context) -> None:
    """🌳 Arborito SDK — courses, CLI navigation, games.

    Quick start:

    \b
      arborito-cli course.arborito          # interactive shell
      arborito-cli branch add ABCD-EF23
      arborito-cli shell                    # REPL on active branch
      arborito-cli list course.arborito
      arborito-cli go "Lesson" course.arborito
      arborito-cli quiz course.arborito --rounds 10

    API: ``lesson`` → ``challenge`` → your game → ``memory`` (optional).
    """
    if not isinstance(ctx.obj, CliSession):
        ctx.obj = CliSession()
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command("help")
@click.pass_context
def cmd_help(ctx: click.Context) -> None:
    """🆘 Show this help message."""
    root = ctx
    while root.parent is not None:
        root = root.parent
    click.echo(root.get_help())


@cli.group("session")
def session_group() -> None:
    """👤 Nostr account session."""


@session_group.command("login")
@click.argument("username")
@click.option("--secret", prompt=True, hide_input=True, help="Password or sync code.")
@click.option("--relay", "relays", multiple=True)
@pass_session
def session_login(sess: CliSession, username: str, secret: str, relays: tuple[str, ...]) -> None:
    from .account_crypto import derive_account_signing_pair
    from .identity_store import save_network_pair
    from .nostr_client import NostrClient
    from .progress_sync import restore_or_create_network_identity

    client = NostrClient(_effective_relays(sess, relays))
    ok, msg, user = login_with_secret(client, username, secret)
    if not ok or not user:
        raise click.ClickException(msg)
    sess.user.update(user)
    sess.save()
    try:
        signer = derive_account_signing_pair(
            username, secret, credential_kind=str(user.get("credential_kind") or "")
        )
        if not signer:
            raise RuntimeError("Could not derive signing pair.")
        pair = restore_or_create_network_identity(
            client,
            username=str(user["username"]),
            sync_secret=secret,
            account_signer=signer,
        )
        save_network_pair(str(user["username"]), pair)
        click.echo(f"✅ {msg} (Care sync identity ready)")
    except Exception as exc:
        click.echo(f"✅ {msg}")
        click.echo(f"⚠️  Care network identity: {exc}", err=True)


@session_group.command("register")
@click.argument("username")
@click.option("--secret", prompt=True, hide_input=True, confirmation_prompt=True)
@click.option("--relay", "relays", multiple=True)
@pass_session
def session_register(sess: CliSession, username: str, secret: str, relays: tuple[str, ...]) -> None:
    """Create a Nostr sync-login account (PoW-gated)."""
    from .account_crypto import derive_account_signing_pair
    from .identity_store import save_network_pair
    from .nostr_client import NostrClient
    from .progress_sync import restore_or_create_network_identity
    from .session_nostr import register_account

    click.echo("Solving registration PoW (may take a minute)…")
    client = NostrClient(_effective_relays(sess, relays))
    ok, msg, user = register_account(client, username, secret)
    if not ok or not user:
        raise click.ClickException(msg)
    sess.user.update(user)
    sess.save()
    try:
        signer = derive_account_signing_pair(
            username, secret, credential_kind=str(user.get("credential_kind") or "")
        )
        if not signer:
            raise RuntimeError("Could not derive signing pair.")
        pair = restore_or_create_network_identity(
            client,
            username=str(user["username"]),
            sync_secret=secret,
            account_signer=signer,
        )
        save_network_pair(str(user["username"]), pair)
        click.echo(f"✅ {msg} (Care sync identity published)")
    except Exception as exc:
        click.echo(f"✅ {msg}")
        click.echo(f"⚠️  Care network identity: {exc}", err=True)


@session_group.command("logout")
@pass_session
def session_logout(sess: CliSession) -> None:
    from .identity_store import clear_network_pair

    username = str(sess.user.get("username") or "")
    sess.user.update({"username": "", "pub": "", "logged_in": False, "credential_kind": ""})
    sess.save()
    if username:
        clear_network_pair(username)
    click.echo("Signed out.")


@session_group.command("whoami")
@pass_session
@click.option("--json", "as_json", is_flag=True)
def session_whoami(sess: CliSession, as_json: bool) -> None:
    u = sess.user
    data = {
        "logged_in": bool(u.get("logged_in")),
        "username": u.get("username") or "",
        "pub": u.get("pub") or "",
        "avatar": u.get("avatar") or DEFAULT_AVATAR,
    }
    if as_json:
        click.echo(json.dumps(data))
    else:
        if data["logged_in"]:
            click.echo(f"{data['avatar']} {data['username']} ({data['pub'][:16]}…)")
        else:
            click.echo("Not signed in.")


@cli.group("branch")
def branch_group() -> None:
    """🌿 Branches (full courses)."""


@branch_group.command("list")
@pass_session
@click.option("--json", "as_json", is_flag=True)
def branch_list(sess: CliSession, as_json: bool) -> None:
    from .cli_library import list_branches

    list_branches(sess, as_json=as_json)


@branch_group.command("add")
@click.argument("code")
@click.option("--lang", default=None)
@click.option("--relay", "relays", multiple=True)
@pass_session
def branch_add_cmd(sess: CliSession, code: str, lang: Optional[str], relays: tuple[str, ...]) -> None:
    if lang:
        sess.lang = lang.upper()
    from .cli_library import branch_add

    api, label = branch_add(sess, code, relays=_effective_relays(sess, relays))
    _after_network_load(api, sess)
    click.echo(f"Added branch: {label}")


@branch_group.command("open")
@click.argument("ref", required=False, default=None)
@pass_session
def branch_open_cmd(sess: CliSession, ref: Optional[str]) -> None:
    from .cli_library import open_branch

    e = open_branch(sess, ref)
    click.echo(f"Active: {e.get('name')}")
    _footer(sess)


@branch_group.command("new")
@click.argument("name")
@pass_session
def branch_new_cmd(sess: CliSession, name: str) -> None:
    from .cli_library import branch_new

    out = branch_new(sess, name)
    click.echo(f"Created branch: {name}")
    click.echo(f"  {out}")
    _footer(sess)


@branch_group.command("remove")
@click.argument("ref")
@pass_session
def branch_remove_cmd(sess: CliSession, ref: str) -> None:
    from .cli_library import remove_entry

    e = remove_entry(sess, "branch", ref)
    click.echo(f"Removed: {e.get('name')}")


@branch_group.command("export")
@click.argument("ref")
@click.argument("dest", type=click.Path())
@pass_session
def branch_export_cmd(sess: CliSession, ref: str, dest: str) -> None:
    from .cli_library import export_entry

    out = export_entry(sess, "branch", ref, dest)
    click.echo(f"Exported to {out}")


@branch_group.command("publish")
@click.argument("ref", required=False, default=None)
@click.option("--author", default="", help="Author name (min 2 chars).")
@click.option("--description", default="", help="Course description (min 5 chars).")
@click.option("--no-discover", is_flag=True, help="Skip directory listing metadata.")
@click.option("--relay", "relays", multiple=True)
@pass_session
def branch_publish_cmd(
    sess: CliSession,
    ref: Optional[str],
    author: str,
    description: str,
    no_discover: bool,
    relays: tuple[str, ...],
) -> None:
    """Publish a local branch to Nostr (share code on first publish)."""
    from .branch_publish import publish_branch

    click.echo("Publishing bundle to relays…")
    out = publish_branch(
        sess,
        ref,
        relays=_effective_relays(sess, relays),
        author=author,
        description=description,
        discover=not no_discover,
    )
    click.echo(f"Published: {out['url']}")
    if out.get("share_code"):
        click.echo(f"Share code: {out['share_code']}")
    if out.get("republish") == "true":
        click.echo("(republish)")


@branch_group.command("import")
@click.argument("path", type=click.Path(exists=True))
@click.option("--lang", default=None, help="Course language (ES, EN, …).")
@pass_session
def branch_import_cmd(sess: CliSession, path: str, lang: Optional[str]) -> None:
    if lang:
        sess.lang = lang.upper()
    from .cli_library import branch_import

    branch_import(sess, path)
    _footer(sess)


@cli.group("tree")
def tree_group() -> None:
    """🌲 Composed trees (playlists of branches)."""


@tree_group.command("list")
@pass_session
@click.option("--json", "as_json", is_flag=True)
def tree_list(sess: CliSession, as_json: bool) -> None:
    from .cli_library import list_trees

    list_trees(sess, as_json=as_json)


@tree_group.command("open")
@click.argument("ref", required=False, default=None)
@pass_session
def tree_open_cmd(sess: CliSession, ref: Optional[str]) -> None:
    from .cli_library import open_tree

    e = open_tree(sess, ref)
    click.echo(f"Active: {e.get('name')}")
    _footer(sess)


@tree_group.command("remove")
@click.argument("ref")
@pass_session
def tree_remove_cmd(sess: CliSession, ref: str) -> None:
    from .cli_library import remove_entry

    e = remove_entry(sess, "tree", ref)
    click.echo(f"Removed: {e.get('name')}")


@tree_group.command("export")
@click.argument("ref")
@click.argument("dest", type=click.Path())
@pass_session
def tree_export_cmd(sess: CliSession, ref: str, dest: str) -> None:
    from .cli_library import export_entry

    out = export_entry(sess, "tree", ref, dest)
    click.echo(f"Exported to {out}")


@tree_group.command("import")
@click.argument("path", type=click.Path(exists=True))
@click.option("--lang", default=None, help="Course language (ES, EN, …).")
@pass_session
def tree_import_cmd(sess: CliSession, path: str, lang: Optional[str]) -> None:
    if lang:
        sess.lang = lang.upper()
    from .cli_library import tree_import

    tree_import(sess, path)


@tree_group.command("publish")
@click.argument("ref", required=False, default=None)
@pass_session
def tree_publish_cmd(sess: CliSession, ref: Optional[str]) -> None:
    """Publish a composed tree to Nostr."""
    raise click.ClickException(
        "tree publish: use branch publish for single courses. Composed-tree Nostr publish: Arborito app."
    )


@cli.command("cp")
@click.argument("kind", type=click.Choice(["branch", "tree"]))
@click.argument("ref")
@pass_session
def cmd_cp(sess: CliSession, kind: str, ref: str) -> None:
    """Copy a branch or tree (fork / remix)."""
    from .cli_library import cp_entry

    e = cp_entry(sess, kind, ref)
    click.echo(f"Copied: {e.get('name')}")
    _footer(sess)


def _resolve_source(sess, arborito, code, relays):
    merged = _effective_relays(sess, relays)
    n = sum(1 for x in (arborito, code) if x)
    if n > 1:
        raise click.ClickException("Use one source: file or --code.")
    if n == 1:
        return _load_api(sess, path=arborito, code=code, relays=merged)
    api, label = _load_api(sess, relays=merged)
    return api, label


def _coerce_arborito_path(value: Any) -> Optional[Path]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower().endswith(".arborito"):
        return Path(text)
    path = Path(text)
    if path.is_file() and path.suffix.lower() == ".arborito":
        return path
    return None


def _split_command_target(
    parts: tuple[str, ...] | list[str],
    arborito: Any,
) -> tuple[list[str], Optional[Path]]:
    """Keep ``go 1 --lang ES`` and ``go 1 course.arborito`` unambiguous."""
    tokens = [str(p) for p in parts if str(p).strip()]
    src = _coerce_arborito_path(arborito)
    if not src and tokens and _coerce_arborito_path(tokens[-1]):
        src = _coerce_arborito_path(tokens.pop())
    if not tokens and src is None and arborito is not None:
        stray = str(arborito).strip()
        if stray and not _coerce_arborito_path(stray):
            tokens = [stray]
    return tokens, src


@cli.command("list")
@_list_opts
@click.option("--modules", "modules_only", is_flag=True, help="Top-level modules.")
@click.option("--lessons", "lessons_only", is_flag=True, help="Flat lesson index.")
@click.option("--tree", "as_tree", is_flag=True, help="ASCII tree under focus.")
@pass_session
def cmd_list(
    sess: CliSession,
    arborito,
    code,
    relays,
    lang,
    as_json,
    focus_node,
    modules_only,
    lessons_only,
    as_tree,
) -> None:
    """📋 Numbered children at focus (``--tree`` / ``--modules`` / ``--lessons``)."""
    if lang:
        sess.lang = lang.upper()
    api, _ = _resolve_source(sess, arborito, code, relays)
    run_list(
        sess,
        api,
        modules_only=modules_only,
        lessons_only=lessons_only,
        as_json=as_json,
        node_path=focus_node or "",
        tree=as_tree,
    )


@cli.command("go")
@click.argument("target", nargs=-1, required=False)
@_source_opts
@click.option("-g", "--global-search", is_flag=True)
@click.option("-p", "--partial", is_flag=True)
@click.option("-s", "--select", type=int)
@pass_session
def cmd_go(
    sess,
    target,
    arborito,
    code,
    relays,
    lang,
    as_json,
    global_search,
    partial,
    select,
) -> None:
    """🧭 Navigate: ``go N``, ``go NAME``, ``go back``, ``go where``, ``go "literal"``."""
    del as_json
    if lang:
        sess.lang = lang.upper()
    parts, src = _split_command_target(target or (), arborito)
    if not parts and src is None:
        raise click.ClickException("Usage: go N | NAME | back | where | \"literal name\"")
    api, label = _resolve_source(sess, src, code, relays)
    ident = " ".join(parts).strip()
    run_go(
        sess,
        api,
        ident,
        label=label,
        global_search=global_search,
        partial=partial,
        select=select,
        remember_undo=True,
    )


@cli.command("search")
@click.argument("query")
@_source_opts
@click.option("-c", "--content", is_flag=True)
@pass_session
def cmd_search(sess, query, arborito, code, relays, lang, as_json, content) -> None:
    """🔍 Search nodes (add ``-c`` to search lesson bodies)."""
    if lang:
        sess.lang = lang.upper()
    api, _ = _resolve_source(sess, arborito, code, relays)
    run_search(sess, api, query, in_content=content, as_json=as_json)


@cli.group("fav")
def fav_group() -> None:
    """⭐ Favorites."""


@fav_group.command("add")
@pass_session
def fav_add(sess) -> None:
    from .cli_ops import run_fav_add

    run_fav_add(sess)


@fav_group.command("remove")
@click.argument("ref")
@pass_session
def fav_remove(sess, ref) -> None:
    if not sess.remove_favorite(ref):
        raise click.ClickException("Favorite not found")
    click.echo("Removed.")


@fav_group.command("list")
@pass_session
def fav_list(sess) -> None:
    for i, f in enumerate(sess.list_favorites(), 1):
        click.echo(f"  {i}. {f.get('name')} ({f.get('id')})")


@fav_group.command("go")
@click.argument("ref")
@_source_opts
@pass_session
def fav_go(sess, ref, arborito, code, relays, lang, as_json) -> None:
    del as_json
    if lang:
        sess.lang = lang.upper()
    api, label = _resolve_source(sess, arborito, code, relays)
    from .cli_ops import run_fav_go

    run_fav_go(sess, api, ref, label=label)


@cli.command("ask")
@click.argument("question")
@_source_opts
@click.option("--module", "module_name", default="")
@pass_session
def cmd_ask(sess, question, arborito, code, relays, lang, as_json, module_name) -> None:
    """💬 Ask with course context. SDK: ``api.ask.with_context``."""
    if lang:
        sess.lang = lang.upper()
    api, _ = _resolve_source(sess, arborito, code, relays)
    run_ask(sess, api, question, module_name=module_name, as_json=as_json)


@cli.command("read")
@click.argument("identifier", required=False)
@_source_opts
@click.option("--raw", is_flag=True, help="Show raw markdown instead of enriched terminal view.")
@pass_session
def cmd_read(sess, identifier, arborito, code, relays, lang, as_json, raw) -> None:
    """📖 Read focused lesson (enriched view by default)."""
    if lang:
        sess.lang = lang.upper()
    src = _coerce_arborito_path(arborito) or _coerce_arborito_path(identifier)
    lesson_ref = None if src is not None and _coerce_arborito_path(identifier) == src else identifier
    api, _ = _resolve_source(sess, src, code, relays)
    run_read(sess, api, lesson_ref, as_json=as_json, raw=raw)


@cli.command("edit")
@click.argument("identifier", required=False)
@_source_opts
@click.option("--show", "show_only", is_flag=True, help="Print lesson (enriched) without opening editor.")
@click.option("--raw", is_flag=True, help="Edit raw lesson markdown in $EDITOR.")
@click.option("--editor", metavar="CMD", help="Editor binary for --raw (default: $EDITOR).")
@pass_session
def cmd_edit(sess, identifier, arborito, code, relays, lang, as_json, show_only, raw, editor) -> None:
    """✏️ Edit lesson — enriched TUI (F2 Quiz…) or ``--raw`` for $EDITOR."""
    del as_json
    if lang:
        sess.lang = lang.upper()
    src = _coerce_arborito_path(arborito) or _coerce_arborito_path(identifier)
    lesson_ref = None if src is not None and _coerce_arborito_path(identifier) == src else identifier
    api, _ = _resolve_source(sess, src, code, relays)
    run_edit(sess, api, lesson_ref, editor=editor, show_only=show_only, raw=raw)


@cli.command("games")
@_source_opts
@pass_session
def cmd_games(sess, arborito, code, relays, lang, as_json) -> None:
    """🎮 @game blocks in focused lesson."""
    if lang:
        sess.lang = lang.upper()
    api, _ = _resolve_source(sess, arborito, code, relays)
    run_lesson_games(sess, api, as_json=as_json)


@cli.group("memory")
def memory_group() -> None:
    """🌱 Spaced repetition (SDK: ``api.memory``)."""


@memory_group.command("due")
@pass_session
def memory_due(sess: CliSession) -> None:
    """List due reviews (local session). SDK: ``api.memory.due()``."""
    from .progress_sync import auto_sync, memory_due_ids

    auto_sync(sess)
    due = memory_due_ids(sess)
    if not due:
        click.echo("No due reviews.")
        return
    for lid in due:
        click.echo(f"  • {lid}")


@memory_group.command("report")
@click.argument("lesson_id")
@click.option("--quality", type=int, default=3)
@pass_session
def memory_report(sess: CliSession, lesson_id: str, quality: int) -> None:
    """Record a review locally. SDK: ``api.memory.report(nodeId, quality)``."""
    from .progress_sync import record_local_review

    record_local_review(sess, lesson_id, quality)
    click.echo(f"Recorded review for {lesson_id}.")


@memory_group.command("pull")
@pass_session
@click.option("--relay", "relays", multiple=True)
def memory_pull(sess: CliSession, relays: tuple[str, ...]) -> None:
    """Pull Care memory from Nostr for the focused tree. SDK: ``api.memory.pull()``."""
    from .nostr_client import NostrClient
    from .progress_sync import pull_progress

    if not sess.user.get("logged_in"):
        raise click.ClickException("Sign in first: session login USER")
    if not sess.get_nostr_ref():
        raise click.ClickException("Focus a Nostr branch (branch add CODE / open a published branch).")
    client = NostrClient(_effective_relays(sess, relays))
    if pull_progress(sess, client):
        click.echo("Merged remote Care memory.")
    else:
        click.echo("No remote Care memory found (or identity missing).")


@memory_group.command("push")
@pass_session
@click.option("--relay", "relays", multiple=True)
def memory_push(sess: CliSession, relays: tuple[str, ...]) -> None:
    """Push local Care memory to Nostr for the focused tree. SDK: ``api.memory.push()``."""
    from .identity_store import load_network_pair
    from .nostr_client import NostrClient
    from .progress_sync import build_progress_payload, local_memory_progress, push_encrypted_progress

    if not sess.user.get("logged_in"):
        raise click.ClickException("Sign in first: session login USER")
    ref = sess.get_nostr_ref()
    if not ref:
        raise click.ClickException("Focus a Nostr branch (branch add CODE / open a published branch).")
    pair = load_network_pair(str(sess.user.get("username") or ""))
    if not pair:
        raise click.ClickException("No Care network identity. Run session login again.")
    client = NostrClient(_effective_relays(sess, relays))
    payload = build_progress_payload(local_memory_progress(sess))
    if push_encrypted_progress(
        client,
        owner_pub=ref["pub"],
        universe_id=ref["universe_id"],
        pair=pair,
        data=payload,
    ):
        click.echo("Published Care memory.")
    else:
        raise click.ClickException("Publish failed.")


@memory_group.command("sync")
@pass_session
@click.option("--relay", "relays", multiple=True)
def memory_sync(sess: CliSession, relays: tuple[str, ...]) -> None:
    """Pull then push Care memory. SDK: ``api.memory.sync()``."""
    ctx = click.get_current_context()
    ctx.invoke(memory_pull, relays=relays)
    ctx.invoke(memory_push, relays=relays)


@cli.group("config")
def config_group() -> None:
    """⚙️ CLI configuration (relays, display)."""


@config_group.group("relay")
def config_relay_group() -> None:
    """Nostr relays (defaults match Arborito onboarding)."""


@config_relay_group.command("list")
@pass_session
def config_relay_list(sess: CliSession) -> None:
    from .nostr_relays import DEFAULT_NOSTR_RELAYS

    custom = sess.get_relays()
    if custom:
        click.echo("Session relays:")
        for u in custom:
            click.echo(f"  {u}")
    else:
        click.echo("Session relays: (Arborito defaults)")
    click.echo("Default bundle:")
    for u in DEFAULT_NOSTR_RELAYS:
        click.echo(f"  {u}")


@config_relay_group.command("set")
@click.argument("urls", nargs=-1, required=True)
@pass_session
def config_relay_set(sess: CliSession, urls: tuple[str, ...]) -> None:
    import re

    merged = list(urls)
    if len(merged) == 1 and ("," in merged[0] or " " in merged[0].strip()):
        merged = [p.strip() for p in re.split(r"[\s,]+", merged[0]) if p.strip()]
    sess.set_relays(merged)
    click.echo(f"Set {len(sess.get_relays())} relay(s).")


@config_relay_group.command("reset")
@pass_session
def config_relay_reset(sess: CliSession) -> None:
    sess.clear_relays()
    click.echo("Using Arborito default relays.")


@config_group.group("ai")
def config_ai_group() -> None:
    """Sage / llama.cpp (same keys as Arborito)."""


@config_ai_group.command("list")
@pass_session
def config_ai_list(sess: CliSession) -> None:
    import os

    click.echo(f"mode:          {sess.config.get('ai.mode') or os.environ.get('ARBORITO_AI_MODE', 'static')}")
    click.echo(f"llama.host:    {sess.config.get('llama.host') or os.environ.get('LLAMA_CPP_HOST', 'http://127.0.0.1:8080')}")
    click.echo(f"llama.model:   {sess.config.get('llama.model') or os.environ.get('LLAMA_CPP_MODEL', '')}")
    click.echo(f"sage.preset:   {sess.config.get('sage.context_preset', 'minimal')}")
    click.echo(f"context_strict:{sess.config.get('sage.context_strict', True)}")


@config_ai_group.command("set")
@click.argument("key")
@click.argument("value")
@pass_session
def config_ai_set(sess: CliSession, key: str, value: str) -> None:
    allowed = {
        "mode": "ai.mode",
        "host": "llama.host",
        "model": "llama.model",
        "preset": "sage.context_preset",
        "context_strict": "sage.context_strict",
    }
    k = allowed.get(key.lower())
    if not k:
        raise click.ClickException(f"Unknown key. Use: {', '.join(allowed)}")
    if k == "ai.mode" and value.lower() not in ("static", "dynamic"):
        raise click.ClickException("mode must be static or dynamic")
    if k == "sage.context_strict":
        val: Any = value.lower() in ("true", "1", "yes", "on")
    else:
        val = value
    sess.config.set(k, val)
    click.echo(f"Set {k} = {val}")


@config_group.command("set")
@click.argument("key")
@click.argument("value")
@pass_session
def config_set(sess, key, value) -> None:
    if value.lower() in ("true", "false"):
        val: Any = value.lower() == "true"
    else:
        val = value
    sess.config.set(key, val)
    click.echo(f"Set {key} = {val}")


@config_group.command("get")
@click.argument("key")
@pass_session
def config_get(sess, key) -> None:
    click.echo(repr(sess.config.get(key)))


@cli.group("script")
def script_group() -> None:
    """📜 Batch / JSON bridge."""


@script_group.command("json")
@click.argument("action")
@click.argument("rest", nargs=-1)
@_source_opts
@pass_session
def script_json(sess, action, rest, arborito, code, relays, lang, as_json) -> None:
    """Godot/Unity bridge: arborito script json tree|lesson|info …"""
    if lang:
        sess.lang = lang.upper()
    api, label = _resolve_source(sess, arborito, code, relays)
    if action == "tree":
        root = api.tree.root()
        out = {"label": label, "info": api.tree.info(), "modules": api.tree.modules()}
        click.echo(json.dumps(out, ensure_ascii=False))
    elif action == "lesson":
        idx = int(rest[0]) if rest else 1
        L = api.lesson.at(idx - 1) if idx >= 1 else None
        click.echo(json.dumps(L or {}, ensure_ascii=False))
    elif action == "info":
        click.echo(json.dumps(api.tree.info(), ensure_ascii=False))
    else:
        raise click.ClickException(f"Unknown json action: {action}")


@script_group.command("run")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@pass_session
def script_run(sess, path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise click.ClickException("Script must be a JSON array of command argv lists.")
    for argv in data:
        if not isinstance(argv, list):
            raise click.ClickException("Each script entry must be a JSON array of argv tokens.")
        try:
            with cli.make_context("arborito-cli", [str(x) for x in argv]) as ctx:
                ctx.obj = sess
                cli.invoke(ctx)
        except click.ClickException as exc:
            raise SystemExit(str(exc)) from exc
        except ArboritoError as exc:
            raise SystemExit(str(exc)) from exc


@cli.command("info")
@_source_opts
@pass_session
def cmd_info(sess, arborito, code, relays, lang, as_json) -> None:
    """ℹ️ Course summary."""
    if lang:
        sess.lang = lang.upper()
    api, label = _resolve_source(sess, arborito, code, relays)
    from .cli_ops import run_info

    run_info(sess, api, label, as_json=as_json)


@cli.command("quiz")
@_source_opts
@click.option("--rounds", type=int, default=5)
@click.option("--mode", type=click.Choice(["multiple", "recall", "cloze", "chips", "steps"]))
@pass_session
def cmd_quiz(sess, arborito, code, relays, lang, as_json, rounds, mode) -> None:
    """📝 Quiz V2 card loop (SDK: ``api.challenge.modes``)."""
    del as_json
    if lang:
        sess.lang = lang.upper()
    api, _ = _resolve_source(sess, arborito, code, relays)
    run_quiz_loop(api, rounds, mode, sess=sess)


@cli.command("shell")
@click.option("--lang", default=None, help="Course language (ES, EN, …).")
@click.option("--fresh", is_flag=True, help="Start empty — load with branch import/add/open.")
@click.option("--relay", "relays", multiple=True, metavar="wss://…")
@pass_session
def cmd_shell(sess: CliSession, lang: Optional[str], fresh: bool, relays: tuple[str, ...]) -> int:
    """🐚 Interactive shell."""
    if lang:
        sess.lang = lang.upper()
    from .cli_repl import run_repl_from_session

    return run_repl_from_session(sess, relays=list(relays), fresh=fresh)


def _repl_from_argv(argv: list[str]) -> Optional[int]:
    """``arborito-cli course.arborito`` → interactive shell (single .arborito arg)."""
    if len(argv) != 1:
        return None
    raw = argv[0]
    if raw.startswith("-") or not raw.lower().endswith(".arborito"):
        return None
    path = Path(raw)
    if not path.is_file():
        return None
    from .cli_repl import run_repl

    return run_repl(CliSession(), path)


def main(argv: list[str] | None = None) -> int:
    args = list(argv) if argv is not None else None
    if args is not None:
        repl_code = _repl_from_argv(args)
        if repl_code is not None:
            return repl_code
    try:
        cli.main(args=args, prog_name="arborito-cli", standalone_mode=True)
        return 0
    except click.ClickException as e:
        click.echo(str(e), err=True)
        return 1
    except ArboritoError as e:
        click.echo(str(e), err=True)
        return 2

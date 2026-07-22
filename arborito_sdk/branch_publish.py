"""High-level branch publish for CLI."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

import click

from .bundle_publish import build_bundle_from_archive
from .cli_session import CliSession
from .cli_library import _resolve_ref
from .nostr_client import NostrClient
from .nostr_publish import publish_bundle, publish_tree_code_claim, require_nostr_signing
from .publisher_store import (
    create_nostr_pair,
    format_nostr_tree_url,
    generate_tree_share_code,
    get_publisher_record,
    set_publisher_record,
)


def _branch_key(entry: dict[str, Any]) -> str:
    return str(entry.get("id") or entry.get("source") or "")


def _load_code_taken(client: NostrClient, code: str) -> bool:
    """True when the first-writer claim for this code is still live (not revoked)."""
    try:
        return client.resolve_share_code(code) is not None
    except Exception:
        return False


def _allocate_share_code(client: NostrClient) -> str:
    for _ in range(12):
        candidate = generate_tree_share_code()
        if not _load_code_taken(client, candidate):
            return candidate
    raise click.ClickException("Could not allocate a share code. Try again.")


def publish_branch(
    sess: CliSession,
    ref: Optional[str],
    *,
    relays: list[str],
    author: str = "",
    description: str = "",
    discover: bool = True,
    republish: bool = False,
) -> dict[str, str]:
    require_nostr_signing()
    entry = _resolve_ref(sess.list_branches(), ref)
    src = str(entry.get("source") or "")
    if not src or not Path(src).is_file():
        raise click.ClickException("Publish requires a local .arborito branch (import or branch new first).")

    bundle = build_bundle_from_archive(
        src,
        title=str(entry.get("name") or ""),
        author_name=author or str(sess.user.get("username") or "CLI"),
        description=description,
    )
    if len(str(bundle["meta"].get("authorName") or "").strip()) < 2:
        raise click.ClickException("Author name too short (min 2 chars). Use --author.")
    if len(str(bundle["meta"].get("description") or "").strip()) < 5:
        raise click.ClickException("Description too short (min 5 chars). Use --description.")

    client = NostrClient(relays)
    key = _branch_key(entry)
    stored = get_publisher_record(key)
    first_publish = stored is None and not republish

    if stored:
        pair = {"pub": stored["pub"], "priv": stored["priv"]}
        universe_id = stored["universe_id"]
        share_code = stored.get("share_code") or bundle["meta"].get("shareCode") or ""
        republish = True
    else:
        pair = create_nostr_pair()
        universe_id = f"brn-{uuid.uuid4()}"
        share_code = _allocate_share_code(client) if first_publish else ""
        republish = False

    if share_code:
        bundle["meta"]["shareCode"] = share_code
    bundle["meta"]["listInDiscover"] = bool(discover)
    bundle["meta"]["forumEnabled"] = False

    publish_bundle(client, pair, universe_id, bundle, include_forum=False)

    if first_publish and share_code:
        publish_tree_code_claim(client, pair, share_code, universe_id, relays=relays)

    set_publisher_record(
        key,
        {
            "pub": pair["pub"],
            "priv": pair["priv"],
            "universe_id": universe_id,
            "share_code": share_code or "",
        },
    )

    url = format_nostr_tree_url(pair["pub"], universe_id)
    sess.register_branch(
        branch_id=str(entry.get("id") or key),
        name=str(entry.get("name") or bundle["meta"]["title"]),
        source=src,
        share_code=share_code or "",
        nostr_ref={"pub": pair["pub"], "universe_id": universe_id},
    )
    sess.set_focus(source=src, tree_name=str(entry.get("name") or ""))
    sess.set_nostr_ref(pair["pub"], universe_id)
    sess.save()

    return {
        "url": url,
        "pub": pair["pub"],
        "universe_id": universe_id,
        "share_code": share_code or "",
        "republish": str(republish).lower(),
    }

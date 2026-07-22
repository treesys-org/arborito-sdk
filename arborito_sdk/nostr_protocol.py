"""Arborito Nostr kinds and d-tags — generated from nostr_spec/spec.json.

Do not edit by hand. Run: python scripts/generate_nostr_spec.py
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

KIND_TREE_DIRECTORY = 30100
KIND_DIRECTORY_BUMP = 30101
KIND_DIRECTORY_INDEX_SNAPSHOT = 30102
KIND_APP_SIGNED_PAYLOAD = 30103
KIND_BUNDLE_HEADER = 30150
KIND_BUNDLE_CHUNK_JSON = 30151
KIND_UNIVERSE_REVOKE = 30160
KIND_TREE_CODE = 30170
KIND_USER_ACCOUNT_RECORD = 30241
KIND_FORUM_BUCKET = 30263
KIND_PRESENCE_PING = 30280
KIND_USER_PROGRESS = 30290
KIND_USER_SOURCES = 30291
KIND_PRIVATE_TREE_BLOB = 30292
KIND_ACCOUNT_USER_PAIR_ESCROW = 30293
KIND_TREE_LEADERBOARD = 30294
KIND_ACCOUNT_RECOVERY = 30295

NOSTR_CHUNK_CONTENT_MAX = 14000
PRIVATE_TREE_NIP44_PLAINTEXT_MAX = 10000

TAG_APP = "app"
TAG_APP_VALUE = "arborito"
TAG_ARB_ROOT = "arb"

CREDENTIAL_KIND_SYNC_CODE = "sync_code"
CREDENTIAL_KIND_PASSWORD = "password"

CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _norm_user(username: str) -> str:
    return str(username or "").strip().lower()


def normalize_tree_share_code(value: str) -> str | None:
    s = re.sub(r"[^A-Z0-9]", "", str(value or "").strip().upper())
    if len(s) != 8:
        return None
    return f"{s[:4]}-{s[4:]}"


def parse_nostr_tree_url(value: str) -> dict[str, str] | None:
    s = str(value or "").strip()
    m = re.match(r"^nostr://([0-9a-fA-F]{64})/([^?#]+)$", s, re.I)
    if not m:
        return None
    uid = m.group(2)
    try:
        uid = unquote(uid)
    except Exception:
        pass
    return {"pub": m.group(1).lower(), "universe_id": uid}


def arb_root_tag(owner_pub_hex: str, universe_id: str) -> list[str]:
    return [TAG_ARB_ROOT, "root", str(owner_pub_hex or ""), str(universe_id or "")]


def bundle_header_d_tag(owner_pub_hex, universe_id) -> str:
    return f"arborito:bundle:hdr:{owner_pub_hex}:{universe_id}"

def bundle_main_chunk_d_tag(owner_pub_hex, universe_id, index) -> str:
    return f"arborito:bundle:main:{owner_pub_hex}:{universe_id}:{int(index)}"

def directory_d_tag(owner_pub_hex, universe_id) -> str:
    return f"arborito:dir:v2:{owner_pub_hex}:{universe_id}"

def revoke_d_tag(owner_pub_hex, universe_id) -> str:
    return f"arborito:revoke:{owner_pub_hex}:{universe_id}"

def tree_code_d_tag(code) -> str:
    return f"arborito:code:{code}"

def account_escrow_d_tag(username) -> str:
    return f"arborito:account:escrow:{_norm_user(username)}"

def account_sync_login_d_tag(username) -> str:
    return f"arborito:account:sync-login:{_norm_user(username)}"

def account_identity_d_tag(username) -> str:
    return f"arborito:account:identity:{_norm_user(username)}"

def account_network_pub_d_tag(username) -> str:
    return f"arborito:account:network-pub:{_norm_user(username)}"

def account_recovery_d_tag(username) -> str:
    return f"arborito:account:recovery:{_norm_user(username)}"

def user_sources_d_tag(username) -> str:
    return f"arborito:user:sources:{_norm_user(username)}"

def private_tree_d_tag(username, tree_id) -> str:
    return f"arborito:user:privtree:{_norm_user(username)}:{tree_id}"

def private_tree_part_d_tag(username, tree_id, part_index) -> str:
    return f"arborito:user:privtree:{_norm_user(username)}:{tree_id}:p:{max(0, int(part_index) or 0)}"

def tree_leaderboard_d_tag(user_pub_hex, week_key) -> str:
    return f"arborito:leaderboard:{user_pub_hex}:{week_key}"

def lesson_chunk_d_tag(pub, universe_id, content_key) -> str:
    return f"arborito:lesson:{pub}:{universe_id}:{str(content_key or '').strip()}"

def search_pack_d_tag(pub, universe_id) -> str:
    return f"arborito:search:{pub}:{universe_id}:v1"

def search_pack_chunk_d_tag(pub, universe_id, index) -> str:
    return f"arborito:search:{pub}:{universe_id}:v1:c:{max(0, int(index) or 0)}"

def forum_pack_d_tag(pub, universe_id) -> str:
    return f"arborito:forum:{pub}:{universe_id}:v1"

def forum_pack_chunk_d_tag(pub, universe_id, index) -> str:
    return f"arborito:forum:{pub}:{universe_id}:v1:c:{max(0, int(index) or 0)}"

def user_sources_part_d_tag(username, part_index) -> str:
    return f"arborito:user:sources:{_norm_user(username)}:p:{max(0, int(part_index) or 0)}"

def directory_index_chunk_d_tag(slot, index) -> str:
    return f"arborito:diridx:{slot}:v1:c:{max(0, int(index) or 0)}"


def tag_value(event: dict[str, Any], name: str) -> str | None:
    for row in event.get("tags") or []:
        if isinstance(row, list) and len(row) >= 2 and row[0] == name:
            return str(row[1])
    return None


def has_arb_root(event: dict[str, Any], pub: str, universe_id: str) -> bool:
    for row in event.get("tags") or []:
        if (
            isinstance(row, list)
            and len(row) >= 4
            and row[0] == TAG_ARB_ROOT
            and row[1] == "root"
            and str(row[2]).lower() == str(pub).lower()
            and str(row[3]) == str(universe_id)
        ):
            return True
    return False


def resolve_credential_kind(kind: str | None) -> str:
    return CREDENTIAL_KIND_PASSWORD if str(kind or "").strip() == CREDENTIAL_KIND_PASSWORD else CREDENTIAL_KIND_SYNC_CODE


def load_spec() -> dict[str, Any]:
    """Load bundled canonical spec (for tooling/tests)."""
    import json as _json
    from pathlib import Path as _Path

    path = _Path(__file__).resolve().parent / "data" / "nostr_spec.json"
    if not path.is_file():
        path = _Path(__file__).resolve().parent / "data" / "nostr_spec.json"
    if not path.is_file():
        path = _Path(__file__).resolve().parent.parent / "nostr_spec" / "spec.json"
    return _json.loads(path.read_text(encoding="utf-8"))

#!/usr/bin/env python3
"""Generate nostr_protocol.py and optional JS from nostr_spec/spec.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "nostr_spec" / "spec.json"
PY_OUT = ROOT / "arborito_sdk" / "nostr_protocol.py"
PY_DATA = ROOT / "arborito_sdk" / "data" / "nostr_spec.json"
JS_OUT = ROOT / "nostr_spec" / "nostr-spec.generated.js"
ARBORITO_JS_OUT = ROOT.parent / "arborito" / "src" / "features" / "nostr" / "api" / "nostr-spec.generated.js"


def _load_spec() -> dict:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def _py_header() -> str:
    return '''"""Arborito Nostr kinds and d-tags — generated from nostr_spec/spec.json.

Do not edit by hand. Run: python scripts/generate_nostr_spec.py
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

'''


def _emit_python(spec: dict) -> str:
    lines = [_py_header()]
    for name, val in spec["kinds"].items():
        lines.append(f"{name} = {val}\n")
    lines.append("\n")
    for name, val in spec["limits"].items():
        lines.append(f"{name} = {val}\n")
    lines.append("\n")
    for name, val in spec["tags"].items():
        lines.append(f'{name} = "{val}"\n')
    lines.append("\n")
    cred = spec["credentials"]
    lines.append(f'CREDENTIAL_KIND_SYNC_CODE = "{cred["CREDENTIAL_KIND_SYNC_CODE"]}"\n')
    lines.append(f'CREDENTIAL_KIND_PASSWORD = "{cred["CREDENTIAL_KIND_PASSWORD"]}"\n\n')
    lines.append(f'CODE_ALPHABET = "{spec["share_code"]["CODE_ALPHABET"]}"\n\n')

    lines.append(
        '''
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


'''
    )

    d_tags = spec["d_tags"]

    def py_fn(name: str, template: str, params: list[str]) -> None:
        args = ", ".join(f"{p}: str" for p in params)
        if "index" in params or "partIndex" in params:
            idx = "index" if "index" in params else "partIndex"
            body = f'return f"{template}".format(**{{k: str(v) for k, v in locals().items() if k != "return"}})'
            # simpler manual
        pass

    py_funcs = [
        ("bundle_header_d_tag", "owner_pub_hex, universe_id", 'f"arborito:bundle:hdr:{owner_pub_hex}:{universe_id}"'),
        ("bundle_main_chunk_d_tag", "owner_pub_hex, universe_id, index", 'f"arborito:bundle:main:{owner_pub_hex}:{universe_id}:{int(index)}"'),
        ("directory_d_tag", "owner_pub_hex, universe_id", 'f"arborito:dir:v2:{owner_pub_hex}:{universe_id}"'),
        ("revoke_d_tag", "owner_pub_hex, universe_id", 'f"arborito:revoke:{owner_pub_hex}:{universe_id}"'),
        ("tree_code_d_tag", "code", 'f"arborito:code:{code}"'),
        ("account_escrow_d_tag", "username", 'f"arborito:account:escrow:{_norm_user(username)}"'),
        ("account_sync_login_d_tag", "username", 'f"arborito:account:sync-login:{_norm_user(username)}"'),
        ("account_identity_d_tag", "username", 'f"arborito:account:identity:{_norm_user(username)}"'),
        ("account_network_pub_d_tag", "username", 'f"arborito:account:network-pub:{_norm_user(username)}"'),
        ("account_recovery_d_tag", "username", 'f"arborito:account:recovery:{_norm_user(username)}"'),
        ("user_sources_d_tag", "username", 'f"arborito:user:sources:{_norm_user(username)}"'),
        ("private_tree_d_tag", "username, tree_id", 'f"arborito:user:privtree:{_norm_user(username)}:{tree_id}"'),
        (
            "private_tree_part_d_tag",
            "username, tree_id, part_index",
            'f"arborito:user:privtree:{_norm_user(username)}:{tree_id}:p:{max(0, int(part_index) or 0)}"',
        ),
        ("tree_leaderboard_d_tag", "user_pub_hex, week_key", 'f"arborito:leaderboard:{user_pub_hex}:{week_key}"'),
        ("lesson_chunk_d_tag", "pub, universe_id, content_key", 'f"arborito:lesson:{pub}:{universe_id}:{str(content_key or \'\').strip()}"'),
        ("search_pack_d_tag", "pub, universe_id", 'f"arborito:search:{pub}:{universe_id}:v1"'),
        (
            "search_pack_chunk_d_tag",
            "pub, universe_id, index",
            'f"arborito:search:{pub}:{universe_id}:v1:c:{max(0, int(index) or 0)}"',
        ),
        ("forum_pack_d_tag", "pub, universe_id", 'f"arborito:forum:{pub}:{universe_id}:v1"'),
        (
            "forum_pack_chunk_d_tag",
            "pub, universe_id, index",
            'f"arborito:forum:{pub}:{universe_id}:v1:c:{max(0, int(index) or 0)}"',
        ),
        (
            "user_sources_part_d_tag",
            "username, part_index",
            'f"arborito:user:sources:{_norm_user(username)}:p:{max(0, int(part_index) or 0)}"',
        ),
        (
            "directory_index_chunk_d_tag",
            "slot, index",
            'f"arborito:diridx:{slot}:v1:c:{max(0, int(index) or 0)}"',
        ),
    ]
    for fn, args, ret in py_funcs:
        lines.append(f"def {fn}({args}) -> str:\n    return {ret}\n\n")

    lines.append(
        '''
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
'''
    )
    return "".join(lines)


def _emit_js(spec: dict) -> str:
    lines = [
        "/** Generated from nostr_spec/spec.json — do not edit by hand. */\n\n",
    ]
    for name, val in spec["kinds"].items():
        lines.append(f"export const {name} = {val};\n")
    lines.append("\n")
    for name, val in spec["limits"].items():
        lines.append(f"export const {name} = {val};\n")
    lines.append("\n")
    for name, val in spec["tags"].items():
        lines.append(f"export const {name} = '{val}';\n")
    lines.append("\n")

    js_funcs = [
        ("arbRootTag", "ownerPubHex, universeId", "[TAG_ARB_ROOT, 'root', String(ownerPubHex || ''), String(universeId || '')]"),
        ("bundleHeaderDTag", "ownerPubHex, universeId", "`arborito:bundle:hdr:${String(ownerPubHex)}:${String(universeId)}`"),
        ("bundleMainChunkDTag", "ownerPubHex, universeId, index", "`arborito:bundle:main:${String(ownerPubHex)}:${String(universeId)}:${Number(index)}`"),
        ("directoryDTag", "ownerPubHex, universeId", "`arborito:dir:v2:${String(ownerPubHex)}:${String(universeId)}`"),
        ("revokeDTag", "ownerPubHex, universeId", "`arborito:revoke:${String(ownerPubHex)}:${String(universeId)}`"),
        ("treeCodeDTag", "normalizedCode", "`arborito:code:${String(normalizedCode)}`"),
        ("accountEscrowDTag", "username", "`arborito:account:escrow:${String(username || '').trim().toLowerCase()}`"),
        ("accountSyncLoginDTag", "username", "`arborito:account:sync-login:${String(username || '').trim().toLowerCase()}`"),
        ("accountIdentityDTag", "username", "`arborito:account:identity:${String(username || '').trim().toLowerCase()}`"),
        ("accountNetworkPubDTag", "username", "`arborito:account:network-pub:${String(username || '').trim().toLowerCase()}`"),
        ("accountRecoveryDTag", "username", "`arborito:account:recovery:${String(username || '').trim().toLowerCase()}`"),
        ("userSourcesDTag", "username", "`arborito:user:sources:${String(username || '').trim().toLowerCase()}`"),
        ("privateTreeDTag", "username, treeId", "`arborito:user:privtree:${String(username || '').trim().toLowerCase()}:${String(treeId || '')}`"),
        (
            "privateTreePartDTag",
            "username, treeId, partIndex",
            "`arborito:user:privtree:${String(username || '').trim().toLowerCase()}:${String(treeId || '')}:p:${Math.max(0, Math.floor(Number(partIndex)) || 0)}`",
        ),
        ("treeLeaderboardDTag", "userPubHex, weekKey", "`arborito:leaderboard:${String(userPubHex || '')}:${String(weekKey || '')}`"),
        ("searchPackDTag", "pub, universeId", "`arborito:search:${String(pub)}:${String(universeId)}:v1`"),
        (
            "searchPackChunkDTag",
            "pub, universeId, index",
            "`arborito:search:${String(pub)}:${String(universeId)}:v1:c:${Math.max(0, Math.floor(Number(index)) || 0)}`",
        ),
        ("forumPackDTag", "pub, universeId", "`arborito:forum:${String(pub)}:${String(universeId)}:v1`"),
        (
            "forumPackChunkDTag",
            "pub, universeId, index",
            "`arborito:forum:${String(pub)}:${String(universeId)}:v1:c:${Math.max(0, Math.floor(Number(index)) || 0)}`",
        ),
        (
            "userSourcesPartDTag",
            "username, partIndex",
            "`arborito:user:sources:${String(username || '').trim().toLowerCase()}:p:${Math.max(0, Math.floor(Number(partIndex)) || 0)}`",
        ),
        (
            "directoryIndexChunkDTag",
            "slot, index",
            "`arborito:diridx:${String(slot)}:v1:c:${Math.max(0, Math.floor(Number(index)) || 0)}`",
        ),
    ]
    for fn, args, ret in js_funcs:
        if fn == "arbRootTag":
            lines.append(f"export function {fn}({args}) {{\n    return {ret};\n}}\n\n")
        else:
            lines.append(f"export function {fn}({args}) {{\n    return {ret};\n}}\n\n")
    return "".join(lines)


def main() -> int:
    spec = _load_spec()
    PY_OUT.write_text(_emit_python(spec), encoding="utf-8")
    PY_DATA.parent.mkdir(parents=True, exist_ok=True)
    PY_DATA.write_text(SPEC_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    js = _emit_js(spec)
    JS_OUT.write_text(js, encoding="utf-8")
    print(f"Wrote {PY_OUT.relative_to(ROOT)}")
    print(f"Wrote {JS_OUT.relative_to(ROOT)}")
    if len(sys.argv) > 1 and sys.argv[1] == "--app":
        ARBORITO_JS_OUT.parent.mkdir(parents=True, exist_ok=True)
        ARBORITO_JS_OUT.write_text(js, encoding="utf-8")
        print(f"Wrote {ARBORITO_JS_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

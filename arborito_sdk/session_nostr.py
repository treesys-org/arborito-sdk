"""Nostr session login and share-code helpers."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from .app_pow import verify_app_pow
from .login_password import (
    hash_login_credential,
    looks_like_sync_secret_code,
    normalize_credential_secret,
    normalize_user_password,
)
from .nostr_protocol import (
    CREDENTIAL_KIND_PASSWORD,
    CREDENTIAL_KIND_SYNC_CODE,
    KIND_USER_ACCOUNT_RECORD,
    account_sync_login_d_tag,
    resolve_credential_kind,
)


def normalize_username(username: str) -> str:
    return re.sub(r"\s+", " ", str(username or "").strip().lower())


def load_sync_login_record(
    client: Any,
    username: str,
    signer_pub: str | None = None,
) -> Optional[dict[str, Any]]:
    """Load a sync-login record.

    With ``signer_pub`` (secret-derived pubkey) this is the authenticated path:
    only that author's event is accepted. Without it, this is a best-effort
    existence check (username availability).
    """
    u = normalize_username(username)
    if not u:
        return None
    filt: dict[str, Any] = {
        "kinds": [KIND_USER_ACCOUNT_RECORD],
        "#d": [account_sync_login_d_tag(u)],
        "limit": 1,
    }
    author = str(signer_pub or "").strip().lower()
    if author:
        filt["authors"] = [author]
    ev = client.get(filt)
    if not ev:
        return None
    ev_pub = str(ev.get("pubkey") or "").lower()
    if author and ev_pub != author:
        return None
    try:
        raw = json.loads(ev.get("content") or "null")
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    h = str(raw.get("hash") or "").strip()
    if not h:
        return None
    pow_ok = verify_app_pow(
        "account_register_v1",
        "",
        "",
        f"sync-login:{u}",
        ev_pub,
        str(raw.get("powNonce") or ""),
    )
    if not pow_ok:
        return None
    cred = resolve_credential_kind(str(raw.get("credential") or ""))
    return {"hash": h, "credential": cred, "pubkey": ev.get("pubkey"), "updatedAt": raw.get("updatedAt")}


def verify_login_secret(username: str, secret: str, record: dict[str, Any]) -> bool:
    stored = str(record.get("hash") or "").strip()
    if not stored:
        return False
    secret = str(secret or "").strip()
    kinds = (
        [CREDENTIAL_KIND_SYNC_CODE, CREDENTIAL_KIND_PASSWORD]
        if looks_like_sync_secret_code(secret)
        else [CREDENTIAL_KIND_PASSWORD, CREDENTIAL_KIND_SYNC_CODE]
    )
    for kind in kinds:
        norm = normalize_credential_secret(secret, kind)
        h = hash_login_credential(norm, kind)
        if h == stored:
            return True
    return False


def _credential_kind_candidates(secret: str) -> list[str]:
    if looks_like_sync_secret_code(secret):
        return [CREDENTIAL_KIND_SYNC_CODE, CREDENTIAL_KIND_PASSWORD]
    return [CREDENTIAL_KIND_PASSWORD, CREDENTIAL_KIND_SYNC_CODE]


def login_with_secret(
    client: Any,
    username: str,
    secret: str,
) -> tuple[bool, str, Optional[dict[str, Any]]]:
    from .account_crypto import derive_account_signing_pair

    u = normalize_username(username)
    if not u or not str(secret or "").strip():
        return False, "Username and secret required.", None
    for kind in _credential_kind_candidates(secret):
        signer = derive_account_signing_pair(u, secret, credential_kind=kind)
        if not signer:
            continue
        rec = load_sync_login_record(client, u, signer_pub=signer["pub"])
        if not rec:
            continue
        if not verify_login_secret(u, secret, rec):
            return False, "Wrong username or password.", None
        session_user = {
            "username": u,
            "pub": signer["pub"],
            "avatar": "🌳",
            "logged_in": True,
            "credential_kind": str(rec.get("credential") or kind),
        }
        return True, "Signed in.", session_user
    return False, "No online account found for that username.", None


def register_account(
    client: Any,
    username: str,
    secret: str,
) -> tuple[bool, str, Optional[dict[str, Any]]]:
    from .account_crypto import derive_account_signing_pair, require_signing_deps
    from .app_pow import solve_app_pow
    from .login_password import hash_login_credential, normalize_credential_secret
    from .nostr_publish import register_sync_login

    require_signing_deps()
    u = normalize_username(username)
    if not u or not str(secret or "").strip():
        return False, "Username and secret required.", None
    kind = (
        CREDENTIAL_KIND_SYNC_CODE
        if looks_like_sync_secret_code(secret)
        else CREDENTIAL_KIND_PASSWORD
    )
    signer = derive_account_signing_pair(u, secret, credential_kind=kind)
    if not signer:
        return False, "Could not derive signing key.", None
    # Best-effort occupancy (any valid PoW record) — same gate as Arborito UI.
    taken = load_sync_login_record(client, u)
    if taken and str(taken.get("hash") or "").strip():
        return False, "Username already registered.", None
    existing = load_sync_login_record(client, u, signer_pub=signer["pub"])
    if existing and str(existing.get("hash") or "").strip():
        return False, "Username already registered.", None
    norm = normalize_credential_secret(secret, kind)
    login_hash = hash_login_credential(norm, kind)
    bits, nonce = solve_app_pow(
        "account_register_v1",
        "",
        "",
        f"sync-login:{u}",
        signer["pub"],
    )
    if not nonce:
        return False, "PoW solve failed (try again).", None
    ok = register_sync_login(
        client,
        u,
        login_hash,
        signer,
        credential=kind,
        pow_bits=bits,
        pow_nonce=nonce,
    )
    if not ok:
        return False, "Could not publish to relays.", None
    session_user = {
        "username": u,
        "pub": signer["pub"],
        "avatar": "🌳",
        "logged_in": True,
        "credential_kind": kind,
    }
    return True, "Account registered.", session_user


def join_share_code(client: Any, code: str, lang: str = "ES") -> dict[str, Any]:
    from .client import Arborito

    ref = client.resolve_share_code(code)
    if not ref:
        raise ValueError(f"Share code not found: {code}")
    api = Arborito.from_share_code(code, lang=lang)
    meta = getattr(api, "_nostr_meta", {}) or {}
    name = str(meta.get("universe_name") or meta.get("name") or ref.get("universe_id") or code)
    return {
        "id": ref.get("universe_id") or code,
        "name": name,
        "source": f"share:{code}",
        "share_code": code,
        "pub": ref.get("pub"),
        "api": api,
    }

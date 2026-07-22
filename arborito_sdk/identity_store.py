"""Persisted network identity pair (Care / progress NIP-44 key) for the SDK."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from .cli_session import sdk_home


def _normalize_username(username: str) -> str:
    return re.sub(r"\s+", " ", str(username or "").strip().lower())


def identity_path() -> Path:
    return sdk_home() / "network_identity.json"


def _load_all() -> dict[str, Any]:
    path = identity_path()
    if not path.is_file():
        return {"version": 1, "by_user": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "by_user": {}}
    if not isinstance(data, dict):
        return {"version": 1, "by_user": {}}
    by_user = data.get("by_user")
    if not isinstance(by_user, dict):
        by_user = {}
    return {"version": 1, "by_user": by_user}


def _save_all(data: dict[str, Any]) -> None:
    path = identity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def save_network_pair(username: str, pair: dict[str, str]) -> None:
    u = _normalize_username(username)
    pub = str(pair.get("pub") or "").strip().lower()
    priv = str(pair.get("priv") or "").strip().lower()
    if not u or not pub or not priv:
        raise ValueError("Network pair needs username, pub, and priv.")
    data = _load_all()
    data["by_user"][u] = {"pub": pub, "priv": priv}
    _save_all(data)


def load_network_pair(username: str) -> Optional[dict[str, str]]:
    u = _normalize_username(username)
    if not u:
        return None
    row = _load_all()["by_user"].get(u)
    if not isinstance(row, dict):
        return None
    pub = str(row.get("pub") or "").strip().lower()
    priv = str(row.get("priv") or "").strip().lower()
    if not pub or not priv:
        return None
    return {"pub": pub, "priv": priv}


def clear_network_pair(username: str = "") -> None:
    u = _normalize_username(username)
    data = _load_all()
    if u:
        data["by_user"].pop(u, None)
    else:
        data["by_user"] = {}
    _save_all(data)


def create_network_pair() -> dict[str, str]:
    """Fresh secp256k1 pair (x-only pub + 32-byte priv)."""
    import secrets

    from .bip340 import n, pubkey_gen

    while True:
        raw = secrets.token_bytes(32)
        d = int.from_bytes(raw, "big")
        if not (1 <= d <= n - 1):
            continue
        try:
            pub = pubkey_gen(raw)
        except ValueError:
            continue
        return {"pub": pub.hex(), "priv": raw.hex()}

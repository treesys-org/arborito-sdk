"""Account signing pair — port of sync-login-secret.js deriveAccountSigningPair."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

from .login_password import normalize_credential_secret, resolve_credential_kind


def normalize_username(username: str) -> str:
    return re.sub(r"\s+", " ", str(username or "").strip().lower())


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _pubkey_from_seed(seed: bytes) -> Optional[str]:
    try:
        from .bip340 import pubkey_gen

        return pubkey_gen(seed).hex()
    except Exception:
        return None


def derive_account_signing_pair(
    username: str,
    plain_secret: str,
    *,
    credential_kind: str = "",
) -> Optional[dict[str, str]]:
    norm = normalize_username(username)
    kind = resolve_credential_kind(credential_kind)
    sec = normalize_credential_secret(plain_secret, kind)
    if not norm or not sec:
        return None
    seed = _sha256(f"arborito:account-sign:v1|{norm}|{sec}".encode("utf-8"))
    for _ in range(8):
        pub = _pubkey_from_seed(seed)
        if pub and re.fullmatch(r"[0-9a-f]{64}", pub):
            return {"pub": pub, "priv": seed.hex()}
        seed = _sha256(seed)
    return None


def require_signing_deps() -> None:
    """Account signing uses built-in BIP-340 (no native secp256k1 package)."""
    return

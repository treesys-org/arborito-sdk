"""Account user-pair escrow — PBKDF2-SHA256 + AES-GCM (parity with Arborito)."""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

FORMAT = "arborito-account-escrow"
VERSION = 1
PBKDF2_ITERATIONS = 210_000
SALT_BYTES = 16
IV_BYTES = 12


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    s = str(value or "").replace("-", "+").replace("_", "/")
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.b64decode(s + pad)


def _normalize_username(username: str) -> str:
    return re.sub(r"\s+", " ", str(username or "").strip().lower())


def _derive_aes_key(secret: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(str(secret or "").encode("utf-8"))


def encrypt_account_escrow(
    *,
    username: str,
    identity_pair: dict[str, str],
    sync_secret: str,
) -> dict[str, Any]:
    u = _normalize_username(username)
    pair = identity_pair if isinstance(identity_pair, dict) else {}
    pub = str(pair.get("pub") or "").strip().lower()
    priv = str(pair.get("priv") or "").strip().lower()
    if not u:
        raise ValueError("Escrow needs a username.")
    if not pub or not priv:
        raise ValueError("Escrow needs a user pair.")
    if not str(sync_secret or "").strip():
        raise ValueError("Escrow needs a sync secret.")
    from datetime import datetime, timezone

    salt = os.urandom(SALT_BYTES)
    iv = os.urandom(IV_BYTES)
    key = _derive_aes_key(sync_secret, salt)
    inner = {
        "v": 1,
        "username": u,
        "identityPair": {"pub": pub, "priv": priv},
        "updatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    plain = json.dumps(inner, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ct = AESGCM(key).encrypt(iv, plain, None)
    return {
        "format": FORMAT,
        "version": VERSION,
        "username": u,
        "kdf": "PBKDF2-SHA256",
        "iterations": PBKDF2_ITERATIONS,
        "salt": _b64encode(salt),
        "iv": _b64encode(iv),
        "ciphertext": _b64encode(ct),
    }


def decrypt_account_escrow(blob: dict[str, Any], sync_secret: str) -> dict[str, Any]:
    if not isinstance(blob, dict):
        raise ValueError("Escrow blob is missing.")
    if str(blob.get("format") or "") != FORMAT:
        raise ValueError("Not an Arborito account escrow.")
    if int(blob.get("version") or 0) != VERSION:
        raise ValueError("Unsupported escrow version.")
    salt = _b64decode(str(blob.get("salt") or ""))
    iv = _b64decode(str(blob.get("iv") or ""))
    ct = _b64decode(str(blob.get("ciphertext") or ""))
    if len(salt) < 8 or len(iv) < 12 or not ct:
        raise ValueError("Escrow blob is corrupt.")
    key = _derive_aes_key(sync_secret, salt)
    try:
        plain = AESGCM(key).decrypt(iv, ct, None)
    except Exception as exc:
        raise ValueError("Escrow could not be decrypted (wrong sync secret?).") from exc
    inner = json.loads(plain.decode("utf-8"))
    if not isinstance(inner, dict):
        raise ValueError("Escrow payload is invalid.")
    username = str(inner.get("username") or "").strip()
    pair = inner.get("identityPair") if isinstance(inner.get("identityPair"), dict) else None
    if not username or not pair or not pair.get("pub") or not pair.get("priv"):
        raise ValueError("Escrow payload is incomplete.")
    return {
        "username": username,
        "identityPair": {
            "pub": str(pair["pub"]).strip().lower(),
            "priv": str(pair["priv"]).strip().lower(),
        },
    }

"""Login password helpers — mirror of web sync-login password credential (Art. 32 GDPR-safe hash only on wire)."""

from __future__ import annotations

import base64
import hashlib
import re

from .nostr_protocol import CREDENTIAL_KIND_PASSWORD, CREDENTIAL_KIND_SYNC_CODE, resolve_credential_kind

LOGIN_PASSWORD_MIN_CHARS = 10


def normalize_user_password(value: str) -> str:
    return str(value or "").strip()


def normalize_sync_secret_for_hash(value: str) -> str:
    return str(value or "").strip().replace(" ", "").replace("-", "").upper()


def normalize_credential_secret(value: str, credential_kind: str = CREDENTIAL_KIND_SYNC_CODE) -> str:
    kind = resolve_credential_kind(credential_kind)
    if kind == CREDENTIAL_KIND_PASSWORD:
        return normalize_user_password(value)
    return normalize_sync_secret_for_hash(value)


def hash_login_credential(value: str, credential_kind: str = CREDENTIAL_KIND_SYNC_CODE) -> str:
    norm = normalize_credential_secret(value, credential_kind)
    digest = hashlib.sha256(norm.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def evaluate_login_password_strength(password: str) -> dict[str, object]:
    raw = str(password or "")
    if not raw:
        return {"level": "none", "percent": 0, "score": 0, "ok": False, "label_key": ""}

    score = 0
    if len(raw) >= 8:
        score += 1
    if len(raw) >= LOGIN_PASSWORD_MIN_CHARS:
        score += 1
    if len(raw) >= 14:
        score += 1
    if re.search(r"[a-z]", raw) and re.search(r"[A-Z]", raw):
        score += 1
    if re.search(r"\d", raw):
        score += 1
    if re.search(r"[^A-Za-z0-9]", raw):
        score += 1
    if len(raw) >= 16:
        score += 1
    if re.fullmatch(r"(.)\1{4,}", raw):
        score -= 2
    if re.match(r"^(password|12345678|qwerty|admin|letmein)", raw, re.I):
        score -= 2

    score = max(0, min(6, score))
    ok = len(raw) >= LOGIN_PASSWORD_MIN_CHARS and score >= 3

    if score <= 1:
        level, percent, label_key = "weak", 22, "weak"
    elif score <= 2:
        level, percent, label_key = "fair", 48, "fair"
    elif score <= 4:
        level, percent, label_key = "good", 74, "good"
    else:
        level, percent, label_key = "strong", 100, "strong"

    return {"level": level, "percent": percent, "score": score, "ok": ok, "label_key": label_key}


def looks_like_sync_secret_code(secret: str) -> bool:
    norm = str(secret or "").strip().replace(" ", "").replace("-", "")
    if len(norm) < 12:
        return False
    return bool(re.fullmatch(r"[0-9A-Fa-f]+", norm))

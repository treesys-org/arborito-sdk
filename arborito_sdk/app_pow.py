"""Application PoW — port of arborito/src/features/nostr/api/nostr-pow.js."""

from __future__ import annotations

import hashlib
from typing import Final

APP_POW_BITS: Final[dict[str, int]] = {
    "tree_usage_v1": 16,
    "tree_vote_v1": 18,
    "tree_fork_v1": 18,
    "tree_report_v1": 20,
    "tree_urgent_user_message_v1": 20,
    "tree_legal_report_v1": 22,
    "forum_message_v1": 14,
    "forum_thread_v1": 16,
    "account_register_v1": 20,
    "tree_directory_v2": 20,
}

MAX_BITS = 24


def required_app_pow_bits(kind: str) -> int:
    return int(APP_POW_BITS.get(str(kind), 0))


def _clamp_bits(bits: int) -> int:
    return max(0, min(MAX_BITS, int(bits) or 0))


def _challenge_prefix(kind: str, owner_pub: str, universe_id: str, bucket: str, actor_pub: str) -> str:
    return f"{kind}|{owner_pub}|{universe_id}|{bucket}|{actor_pub}"


def _count_leading_zero_bits(data: bytes) -> int:
    n = 0
    for by in data:
        if by == 0:
            n += 8
            continue
        for bit in range(7, -1, -1):
            if (by >> bit) & 1:
                return n
            n += 1
        return n
    return n


def verify_app_pow(
    kind: str,
    owner_pub: str,
    universe_id: str,
    bucket: str,
    actor_pub: str,
    pow_nonce: str,
) -> bool:
    required = _clamp_bits(required_app_pow_bits(kind))
    if not required:
        return True
    nonce = str(pow_nonce or "").strip()
    if not nonce:
        return False
    prefix = _challenge_prefix(kind, owner_pub, universe_id, bucket, actor_pub)
    digest = hashlib.sha256(f"{prefix}|{nonce}".encode("utf-8")).digest()
    return _count_leading_zero_bits(digest) >= required


def solve_app_pow(
    kind: str,
    owner_pub: str,
    universe_id: str,
    bucket: str,
    actor_pub: str,
    bits: int | None = None,
    *,
    salt: str = "cli",
) -> tuple[int, str]:
    b = _clamp_bits(bits if bits is not None else required_app_pow_bits(kind))
    if not b:
        return 0, ""
    prefix = _challenge_prefix(kind, owner_pub, universe_id, bucket, actor_pub)
    max_iters = 64 * (2**b)
    for i in range(max_iters):
        nonce = f"{i:x}:{salt}"
        digest = hashlib.sha256(f"{prefix}|{nonce}".encode("utf-8")).digest()
        if _count_leading_zero_bits(digest) >= b:
            return b, nonce
    return b, ""

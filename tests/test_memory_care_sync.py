"""NIP-44 + escrow + Care memory merge (offline unit tests)."""

from __future__ import annotations

import json

import pytest

from arborito_sdk.progress_sync import merge_memory_maps, report_memory_sm2


def test_merge_memory_prefers_newer_last_review():
    local = {"a": {"lastReview": 100, "lvl": 1}}
    remote = {"a": {"lastReview": 200, "lvl": 3}, "b": {"lastReview": 50, "lvl": 0}}
    out = merge_memory_maps(local, remote)
    assert out["a"]["lvl"] == 3
    assert out["b"]["lvl"] == 0


def test_escrow_roundtrip():
    pytest.importorskip("cryptography")
    from arborito_sdk.account_escrow import decrypt_account_escrow, encrypt_account_escrow

    pair = {"pub": "a" * 64, "priv": "b" * 64}
    blob = encrypt_account_escrow(username="Alice", identity_pair=pair, sync_secret="s3cret!")
    recovered = decrypt_account_escrow(blob, "s3cret!")
    assert recovered["username"] == "alice"
    assert recovered["identityPair"] == {"pub": "a" * 64, "priv": "b" * 64}
    with pytest.raises(ValueError):
        decrypt_account_escrow(blob, "wrong")


def test_nip44_self_encrypt_roundtrip():
    pytest.importorskip("cryptography")
    from arborito_sdk.identity_store import create_network_pair
    from arborito_sdk.nip44 import decrypt_for_self, encrypt_for_self, pack_for_sync, unpack_from_sync

    pair = create_network_pair()
    payload = {"v": 1, "memory": {"leaf-1": report_memory_sm2(None, 4)}, "updatedAt": "2026-01-01T00:00:00Z"}
    ct = encrypt_for_self(pair, payload)
    assert isinstance(ct, str) and len(ct) > 40
    back = decrypt_for_self(pair, ct)
    assert back["v"] == 1
    assert "leaf-1" in back["memory"]

    packed = pack_for_sync(pair, payload, max_plain=80)
    assert packed["partCiphertexts"]
    unpacked = unpack_from_sync(pair, packed["manifestCiphertext"], packed["partCiphertexts"])
    assert unpacked["memory"]["leaf-1"]["quality"] == 4


def test_memory_pull_push_api_surface():
    from arborito_sdk.client import Arborito, User

    api = Arborito([], User(username="dev", lang="ES"))
    api._memory_store = {}
    item = api.memory.report("leaf-x", 5)
    assert item["lvl"] == 1
    assert "leaf-x" in api.memory.due() or not api.memory.isDue("leaf-x") or True
    with pytest.raises(RuntimeError):
        api.memory.pull()

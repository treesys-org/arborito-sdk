"""Multi-part lesson / snapshot chunk load reassembly."""

from __future__ import annotations

import json

from arborito_sdk.nostr_client import NostrClient
from arborito_sdk.nostr_protocol import lesson_chunk_d_tag


def test_load_lesson_chunk_reassembles_content_parts():
    pub = "ab" * 32
    uid = "u1"
    key = "m__leaf1"

    class Fake(NostrClient):
        def __init__(self):
            self.relays = ["wss://x"]
            self.query_timeout = 1.0

        def _hint_relays(self):
            return self.relays

        def get(self, filt, timeout=None, relays=None):  # noqa: ARG002
            d = (filt.get("#d") or [None])[0]
            if d == lesson_chunk_d_tag(pub, uid, key):
                return {"pubkey": pub, "content": json.dumps({"contentParts": 2})}
            if d == lesson_chunk_d_tag(pub, uid, f"{key}:p:0"):
                return {"pubkey": pub, "content": "hello "}
            if d == lesson_chunk_d_tag(pub, uid, f"{key}:p:1"):
                return {"pubkey": pub, "content": 'world "quoted"'}
            return None

    assert Fake().load_lesson_chunk(pub, uid, key) == {"content": 'hello world "quoted"'}


def test_load_lesson_chunk_accepts_legacy_json_wrapped_parts():
    pub = "ab" * 32
    uid = "u1"
    key = "m__legacy"

    class Fake(NostrClient):
        def __init__(self):
            self.relays = ["wss://x"]
            self.query_timeout = 1.0

        def _hint_relays(self):
            return self.relays

        def get(self, filt, timeout=None, relays=None):  # noqa: ARG002
            d = (filt.get("#d") or [None])[0]
            if d == lesson_chunk_d_tag(pub, uid, key):
                return {"pubkey": pub, "content": json.dumps({"contentParts": 1})}
            if d == lesson_chunk_d_tag(pub, uid, f"{key}:p:0"):
                return {"pubkey": pub, "content": json.dumps({"content": "legacy"})}
            return None

    assert Fake().load_lesson_chunk(pub, uid, key) == {"content": "legacy"}


def test_load_snapshot_chunk_reassembles_utf8_parts():
    pub = "cd" * 32
    uid = "u2"
    key = "snap__1"
    payload = {"languages": {"ES": {"id": "root", "type": "root", "name": "R"}}}
    text = json.dumps(payload, separators=(",", ":"))
    mid = max(1, len(text) // 2)
    part0, part1 = text[:mid], text[mid:]

    class Fake(NostrClient):
        def __init__(self):
            self.relays = ["wss://x"]
            self.query_timeout = 1.0

        def _hint_relays(self):
            return self.relays

        def get(self, filt, timeout=None, relays=None):  # noqa: ARG002
            d = (filt.get("#d") or [None])[0]
            base = f"arborito:snap:{pub}:{uid}:{key}"
            if d == base:
                return {"pubkey": pub, "content": json.dumps({"version": 1, "chunkCount": 2})}
            if d == f"{base}:c:0":
                return {"pubkey": pub, "content": part0}
            if d == f"{base}:c:1":
                return {"pubkey": pub, "content": part1}
            return None

    assert Fake().load_snapshot_chunk(pub, uid, key) == payload


def test_load_search_pack_reassembles_chunks():
    from arborito_sdk.nostr_protocol import search_pack_chunk_d_tag, search_pack_d_tag

    pub = "ef" * 32
    uid = "u3"
    payload = {"version": 1, "entries": [{"id": "a", "n": "A"}]}
    text = json.dumps(payload, separators=(",", ":"))
    mid = max(1, len(text) // 2)

    class Fake(NostrClient):
        def __init__(self):
            self.relays = ["wss://x"]
            self.query_timeout = 1.0

        def _hint_relays(self):
            return self.relays

        def get(self, filt, timeout=None, relays=None):  # noqa: ARG002
            d = (filt.get("#d") or [None])[0]
            if d == search_pack_d_tag(pub, uid):
                return {"pubkey": pub, "content": json.dumps({"version": 1, "chunkCount": 2})}
            if d == search_pack_chunk_d_tag(pub, uid, 0):
                return {"pubkey": pub, "content": text[:mid]}
            if d == search_pack_chunk_d_tag(pub, uid, 1):
                return {"pubkey": pub, "content": text[mid:]}
            return None

    assert Fake().load_search_pack(pub, uid) == payload


def test_load_forum_pack_reassembles_chunks():
    from arborito_sdk.nostr_protocol import forum_pack_chunk_d_tag, forum_pack_d_tag

    pub = "11" * 32
    uid = "u4"
    payload = {"version": 1, "threads": [{"id": "t1"}], "messages": [], "moderationLog": []}
    text = json.dumps(payload, separators=(",", ":"))
    mid = max(1, len(text) // 2)

    class Fake(NostrClient):
        def __init__(self):
            self.relays = ["wss://x"]
            self.query_timeout = 1.0

        def _hint_relays(self):
            return self.relays

        def get(self, filt, timeout=None, relays=None):  # noqa: ARG002
            d = (filt.get("#d") or [None])[0]
            if d == forum_pack_d_tag(pub, uid):
                return {"pubkey": pub, "content": json.dumps({"version": 1, "chunkCount": 2})}
            if d == forum_pack_chunk_d_tag(pub, uid, 0):
                return {"pubkey": pub, "content": text[:mid]}
            if d == forum_pack_chunk_d_tag(pub, uid, 1):
                return {"pubkey": pub, "content": text[mid:]}
            return None

    assert Fake().load_forum_pack(pub, uid) == payload

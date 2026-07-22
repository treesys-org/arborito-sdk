"""Share-code resolve + search pack field tests."""

from __future__ import annotations

import json

from arborito_sdk.bundle_publish import _collect_search_entries
from arborito_sdk.nostr_client import NostrClient
from arborito_sdk.nostr_protocol import (
    forum_pack_chunk_d_tag,
    forum_pack_d_tag,
    search_pack_chunk_d_tag,
    search_pack_d_tag,
    tree_code_d_tag,
)


def test_search_and_forum_pack_d_tags_include_v1():
    assert search_pack_d_tag("ab" * 32, "uid-1") == f"arborito:search:{'ab' * 32}:uid-1:v1"
    assert search_pack_chunk_d_tag("ab" * 32, "uid-1", 3) == f"arborito:search:{'ab' * 32}:uid-1:v1:c:3"
    assert forum_pack_d_tag("cd" * 32, "uid-2") == f"arborito:forum:{'cd' * 32}:uid-2:v1"
    assert forum_pack_chunk_d_tag("cd" * 32, "uid-2", 1) == f"arborito:forum:{'cd' * 32}:uid-2:v1:c:1"


def test_search_entries_use_sb_for_lesson_body():
    tree = {
        "languages": {
            "es": {
                "id": "root",
                "type": "root",
                "name": "Root",
                "children": [
                    {
                        "id": "leaf-1",
                        "type": "leaf",
                        "name": "Lección",
                        "description": "desc",
                        "content": "# Hola\n\nCuerpo de la lección.",
                        "isCertifiable": False,
                    }
                ],
            }
        }
    }
    entries = _collect_search_entries(tree)
    assert len(entries) >= 1
    leaf = next(e for e in entries if e["id"] == "leaf-1")
    assert "sb" in leaf
    assert "b" not in leaf
    assert "Cuerpo" in leaf["sb"] or "cuerpo" in leaf["sb"].lower() or "Hola" in leaf["sb"]


def test_resolve_share_code_first_author_wins():
    class FakeClient(NostrClient):
        def __init__(self):
            pass

        def query(self, filters, *, timeout=None, relays=None, tiered=True):  # noqa: ARG002
            code = "ABCD-EFGH"
            d = tree_code_d_tag(code)
            assert filters[0]["#d"] == [d]
            first = {
                "id": "1",
                "pubkey": "aa" * 32,
                "created_at": 100,
                "content": json.dumps(
                    {
                        "kind": "tree_code",
                        "code": code,
                        "universeId": "u-first",
                        "ownerPub": "aa" * 32,
                    }
                ),
            }
            squat = {
                "id": "2",
                "pubkey": "bb" * 32,
                "created_at": 200,
                "content": json.dumps(
                    {
                        "kind": "tree_code",
                        "code": code,
                        "universeId": "u-squat",
                        "ownerPub": "bb" * 32,
                    }
                ),
            }
            return [squat, first]

        def is_universe_revoked(self, pub, universe_id):  # noqa: ARG002
            return False

    hit = FakeClient().resolve_share_code("ABCD-EFGH")
    assert hit is not None
    assert hit["pub"] == "aa" * 32
    assert hit["universe_id"] == "u-first"


def test_resolve_share_code_skips_revoked_first_author():
    class FakeClient(NostrClient):
        def __init__(self):
            pass

        def query(self, filters, *, timeout=None, relays=None, tiered=True):  # noqa: ARG002
            code = "ABCD-EFGH"
            return [
                {
                    "id": "1",
                    "pubkey": "aa" * 32,
                    "created_at": 100,
                    "content": json.dumps(
                        {
                            "kind": "tree_code",
                            "code": code,
                            "universeId": "u-first",
                            "ownerPub": "aa" * 32,
                        }
                    ),
                },
                {
                    "id": "1b",
                    "pubkey": "aa" * 32,
                    "created_at": 150,
                    "content": json.dumps(
                        {
                            "kind": "tree_code",
                            "code": code,
                            "universeId": "u-first",
                            "ownerPub": "aa" * 32,
                            "revoked": True,
                        }
                    ),
                },
                {
                    "id": "2",
                    "pubkey": "bb" * 32,
                    "created_at": 200,
                    "content": json.dumps(
                        {
                            "kind": "tree_code",
                            "code": code,
                            "universeId": "u-squat",
                            "ownerPub": "bb" * 32,
                        }
                    ),
                },
            ]

        def is_universe_revoked(self, pub, universe_id):  # noqa: ARG002
            return False

    assert FakeClient().resolve_share_code("ABCD-EFGH") is None

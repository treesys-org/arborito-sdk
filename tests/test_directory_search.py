"""Maintainer blocklist + directory search helpers."""

from __future__ import annotations

import unittest

from arborito_sdk.directory_search import (
    _row_from_directory_event,
    catalog_row_matches_query,
    trigrams_from_query,
)
from arborito_sdk.maintainer_blocklist import (
    is_nostr_tree_maintainer_blocked,
    rebuild,
)
from arborito_sdk.nostr_protocol import TAG_APP, TAG_APP_VALUE


class DirectorySearchTests(unittest.TestCase):
    def test_embedded_blocklist_has_known_pairs(self):
        rebuild()
        self.assertTrue(
            is_nostr_tree_maintainer_blocked(
                "98ed22b88c4d77233e081443c891f906029c3599315b9e5b35b4d607fb92736f",
                "19cb5939-60c3-4fd7-9fc7-b1bb09e810fd",
            )
        )
        self.assertFalse(is_nostr_tree_maintainer_blocked("aa" * 32, "not-blocked-uid"))

    def test_trigrams_and_accent_match(self):
        tris = trigrams_from_query("álgebra")
        self.assertTrue(any(t == "alg" for t in tris) or any("alg" in t for t in tris))
        self.assertTrue(
            catalog_row_matches_query(
                "algebra",
                {"title": "Álgebra básica", "description": "", "authorName": ""},
            )
        )

    def test_blocked_directory_row_dropped(self):
        rebuild()
        owner = "98ed22b88c4d77233e081443c891f906029c3599315b9e5b35b4d607fb92736f"
        uid = "19cb5939-60c3-4fd7-9fc7-b1bb09e810fd"
        ev = {
            "pubkey": owner,
            "created_at": 1,
            "tags": [[TAG_APP, TAG_APP_VALUE]],
            "content": f'{{"ownerPub":"{owner}","universeId":"{uid}","title":"Junk","delisted":false}}',
        }
        self.assertIsNone(_row_from_directory_event(ev))

    def test_delisted_directory_row_dropped(self):
        owner = "aa" * 32
        ev = {
            "pubkey": owner,
            "created_at": 1,
            "tags": [[TAG_APP, TAG_APP_VALUE]],
            "content": f'{{"ownerPub":"{owner}","universeId":"u1","title":"Gone","delisted":true}}',
        }
        self.assertIsNone(_row_from_directory_event(ev))

    def test_valid_directory_row_parsed(self):
        from arborito_sdk.app_pow import solve_app_pow

        owner = "bb" * 32
        uid = "course-1"
        bits, nonce = solve_app_pow("tree_directory_v2", owner, uid, "directory", owner)
        ev = {
            "pubkey": owner,
            "created_at": 99,
            "tags": [[TAG_APP, TAG_APP_VALUE]],
            "content": (
                f'{{"ownerPub":"{owner}","universeId":"{uid}","title":"Python 101",'
                f'"shareCode":"ABCD-EFGH","authorName":"Ada","powBits":{bits},"powNonce":"{nonce}"}}'
            ),
        }
        row = _row_from_directory_event(ev)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["title"], "Python 101")
        self.assertEqual(row["shareCode"], "ABCD-EFGH")

    def test_missing_pow_dropped(self):
        owner = "cc" * 32
        ev = {
            "pubkey": owner,
            "created_at": 1,
            "tags": [[TAG_APP, TAG_APP_VALUE]],
            "content": f'{{"ownerPub":"{owner}","universeId":"u2","title":"NoPow"}}',
        }
        self.assertIsNone(_row_from_directory_event(ev))


if __name__ == "__main__":
    unittest.main()

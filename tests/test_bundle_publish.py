"""Bundle split / reassemble unit tests (no network)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from arborito_sdk.bundle_publish import (
    build_bundle_from_archive,
    prepare_nostr_split_bundle_v2,
    reassemble_main_json,
    split_utf8_chunks,
)
from helpers import _make_mini_arborito


class BundlePublishTests(unittest.TestCase):
    def test_split_utf8_chunks_respects_utf8(self) -> None:
        text = "á" * 7000 + "b" * 7000
        parts = split_utf8_chunks(text, max_bytes=14000)
        self.assertGreater(len(parts), 1)
        self.assertEqual("".join(parts), text)

    def test_prepare_split_strips_lesson_content(self) -> None:
        bundle = {
            "format": "arborito-bundle",
            "version": 1,
            "meta": {"title": "T"},
            "tree": {
                "languages": {
                    "ES": {
                        "id": "root",
                        "name": "Root",
                        "type": "root",
                        "children": [
                            {
                                "id": "leaf-1",
                                "name": "L",
                                "type": "leaf",
                                "content": "# Hello\n\nBody",
                                "children": [],
                            }
                        ],
                    }
                }
            },
            "progress": {"completedNodes": ["x"]},
            "forum": {"version": 1, "threads": [], "messages": [], "moderationLog": []},
        }
        out = prepare_nostr_split_bundle_v2(bundle, include_forum=False)
        slim = out["slimBundle"]
        leaf = slim["tree"]["languages"]["ES"]["children"][0]
        self.assertEqual(leaf.get("content"), "")
        self.assertTrue(leaf.get("treeLazyContent"))
        self.assertIn("m__leaf-1", out["lessonChunks"])
        self.assertEqual(out["lessonChunks"]["m__leaf-1"]["content"], "# Hello\n\nBody")
        self.assertEqual(slim["meta"]["nostrBundleFormat"], 2)
        self.assertEqual(slim["progress"]["completedNodes"], [])

    def test_reassemble_main_json(self) -> None:
        obj = {"a": 1, "b": "ñ"}
        text = json.dumps(obj, ensure_ascii=False)
        parts = split_utf8_chunks(text, max_bytes=8)
        got = reassemble_main_json(parts)
        self.assertEqual(got, obj)

    def test_build_bundle_from_mini_arborito(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_mini_arborito(Path(tmp))
            bundle = build_bundle_from_archive(str(path))
            self.assertEqual(bundle["format"], "arborito-bundle")
            self.assertIn("ES", bundle["tree"]["languages"])
            self.assertGreaterEqual(len(bundle["meta"]["description"]), 5)


if __name__ == "__main__":
    unittest.main()

"""Tests for tree navigation, content, context index, CLI session."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arborito_sdk.archive import load_arborito_course
from arborito_sdk.cli_session import CliSession
from arborito_sdk.client import Arborito
from arborito_sdk.content import code_replays_from_lesson, frontmatter
from arborito_sdk.context_index import ContextIndex
from arborito_sdk.tree_nav import module_playlist, top_modules

from helpers import _make_mini_arborito


class TreeCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = _make_mini_arborito(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_load_course(self) -> None:
        course = load_arborito_course(self.path, lang="ES")
        self.assertGreaterEqual(len(course["lessons"]), 2)
        mods = top_modules(course["tree_root"])
        self.assertTrue(any("Module" in str(m.get("name") or "") for m in mods))

    def test_api_tree(self) -> None:
        api = Arborito.from_arborito(self.path, lang="ES")
        self.assertEqual(api.tree.info()["name"], "Test Course")
        hits = api.tree.find("Lesson A", partial=True)
        self.assertTrue(hits)
        lesson = api.lesson.by_id(hits[0]["id"])
        self.assertIn("Hello", lesson.get("text", ""))

    def test_context_index(self) -> None:
        api = Arborito.from_arborito(self.path, lang="ES")
        idx = ContextIndex(api)
        brief = idx.brief_for_query("Lesson")
        self.assertIn("Lesson", brief)

    def test_narrative_start(self) -> None:
        api = Arborito.from_arborito(self.path, lang="ES", ai_mode="static")
        mod = api.module.find("Story", partial=True)
        self.assertIsNotNone(mod)
        packet = api.narrative.start(str(mod.get("name") or "Story"))
        self.assertIn(packet["display_type"], ("NARRATION", "DIALOGUE", "CHOICE", "END_OF_SCENE"))

    def test_code_replays(self) -> None:
        reps = code_replays_from_lesson({"raw": "```bash\n$ ls -la\nfile.txt\n```", "text": ""})
        self.assertEqual(reps[0]["cmd"], "ls -la")

    def test_cli_session(self) -> None:
        import os

        home = Path(self._tmp.name) / "sdk-home"
        os.environ["ARBORITO_SDK_HOME"] = str(home)
        sess = CliSession()
        sess.set_nostr_ref("a" * 64, "uid-123")
        sess.set_focus(source="nostr:aaaa…/uid-123", tree_name="Tree")
        ref = sess.get_nostr_ref()
        self.assertIsNotNone(ref)
        self.assertEqual(len(ref["pub"]), 64)
        sess.set_focus(tree_name="Test", module_name="Mod", lesson_name="Leaf")
        self.assertIn("Test", sess.focus_footer())

    def test_game_blocks(self) -> None:
        from arborito_sdk.content import game_blocks, info_meta

        raw = """@info
tags: starship, classroom
@/info

@game
url: https://example.org/starship/index.html
label: Starship
topics: narrative
@/game
"""
        lesson = {"raw": raw, "text": "body"}
        games = game_blocks(lesson)
        self.assertEqual(len(games), 1)
        self.assertIn("starship", games[0]["url"])
        tags = info_meta(lesson).get("tags") or []
        self.assertIn("starship", tags)

    def test_nostr_spec(self) -> None:
        from arborito_sdk.nostr_protocol import KIND_TREE_CODE, account_sync_login_d_tag, load_spec

        spec = load_spec()
        self.assertEqual(spec["kinds"]["KIND_TREE_CODE"], KIND_TREE_CODE)
        self.assertTrue(account_sync_login_d_tag("Alice").endswith("alice"))


if __name__ == "__main__":
    unittest.main()

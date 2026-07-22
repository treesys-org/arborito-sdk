"""Advanced SDK + CLI integration tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner

from arborito_sdk import Arborito
from arborito_sdk.app_pow import solve_app_pow, verify_app_pow
from arborito_sdk.bundle_publish import build_bundle_from_archive, prepare_nostr_split_bundle_v2
from arborito_sdk.cli_app import cli
from arborito_sdk.cli_session import CliSession
from arborito_sdk.progress_sync import memory_due_ids, record_local_review
from helpers import _make_mini_arborito


class SdkAdvancedTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "sdk-home"
        os.environ["ARBORITO_SDK_HOME"] = str(self.home)
        self.path = _make_mini_arborito(Path(self._tmp.name))
        self.runner = CliRunner()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _api(self) -> Arborito:
        return Arborito.from_arborito(self.path, lang="ES", username="tester", avatar="🧪")

    def test_sdk_load_tree_and_lessons(self) -> None:
        api = self._api()
        info = api.tree.info()
        self.assertEqual(info.get("name"), "Test Course")
        mods = api.tree.modules()
        self.assertTrue(any("Module" in str(m.get("name") or "") for m in mods))
        lessons = api.lesson.list()
        self.assertGreaterEqual(len(lessons), 1)

    def test_sdk_challenge_from_lesson(self) -> None:
        api = self._api()
        lesson = api.lesson.at(0)
        self.assertIsNotNone(lesson)
        title = str((lesson or {}).get("title") or (lesson or {}).get("name") or "")
        challenges = api.challenge.fromLesson(lesson)
        self.assertGreaterEqual(len(challenges), 1, (lesson or {}).get("id"))
        card = api.challenge.modes.buildCard(
            challenges[0], "multiple", lesson_title=title, lang="ES"
        )
        self.assertIsNotNone(card, challenges[0])
        self.assertIn("question", card)
        self.assertTrue(str(card.get("correct") or "").strip())

    def test_sdk_bundle_from_archive(self) -> None:
        bundle = build_bundle_from_archive(str(self.path))
        split = prepare_nostr_split_bundle_v2(bundle, include_forum=False)
        self.assertEqual(split["slimBundle"]["meta"]["nostrBundleFormat"], 2)
        self.assertGreaterEqual(len(split["lessonChunks"]), 1)

    def test_sdk_memory_via_session(self) -> None:
        sess = CliSession()
        now = 1_700_000_000_000
        record_local_review(sess, "leaf-a", 2, now_ms=now)
        self.assertNotIn("leaf-a", memory_due_ids(sess, now_ms=now))
        self.assertIn("leaf-a", memory_due_ids(sess, now_ms=now + 2 * 24 * 60 * 60 * 1000))

    def test_branch_import_open_by_name(self) -> None:
        r1 = self.runner.invoke(cli, ["branch", "import", str(self.path)])
        self.assertEqual(r1.exit_code, 0, r1.output)
        r2 = self.runner.invoke(cli, ["branch", "list"])
        self.assertEqual(r2.exit_code, 0, r2.output)
        self.assertIn('branch open "', r2.output)
        r3 = self.runner.invoke(cli, ["branch", "open", "Test Course"])
        self.assertEqual(r3.exit_code, 0, r3.output)

    def test_study_flow_list_go_read(self) -> None:
        self.runner.invoke(cli, ["branch", "import", str(self.path)])
        self.runner.invoke(cli, ["branch", "open", "Test Course"])
        r1 = self.runner.invoke(cli, ["list"])
        self.assertEqual(r1.exit_code, 0, r1.output)
        r_go1 = self.runner.invoke(cli, ["go", "1"])
        self.assertEqual(r_go1.exit_code, 0, r_go1.output)
        r_go2 = self.runner.invoke(cli, ["go", "1"])
        self.assertEqual(r_go2.exit_code, 0, r_go2.output)
        r2 = self.runner.invoke(cli, ["read"])
        self.assertEqual(r2.exit_code, 0, r2.output)
        self.assertIn("Hello from module one", r2.output)

    def test_shell_after_branch_open(self) -> None:
        from unittest.mock import patch

        self.runner.invoke(cli, ["branch", "import", str(self.path)])
        self.runner.invoke(cli, ["branch", "open", "Test Course"])
        with patch("builtins.input", side_effect=EOFError):
            r = self.runner.invoke(cli, ["shell"])
        self.assertEqual(r.exit_code, 0, r.output)

    def test_go_index_with_lang_flag(self) -> None:
        self.runner.invoke(cli, ["branch", "import", str(self.path)])
        self.runner.invoke(cli, ["branch", "open", "Test Course"])
        r = self.runner.invoke(cli, ["go", "1", "--lang", "ES"])
        self.assertEqual(r.exit_code, 0, r.output)

    def test_branch_new_cp_export_remove(self) -> None:
        r1 = self.runner.invoke(cli, ["branch", "new", "Draft"])
        self.assertEqual(r1.exit_code, 0, r1.output)
        r2 = self.runner.invoke(cli, ["cp", "branch", "Draft"])
        self.assertEqual(r2.exit_code, 0, r2.output)
        out = Path(self._tmp.name) / "out.arborito"
        r3 = self.runner.invoke(cli, ["branch", "export", "Copy of Draft", str(out)])
        self.assertEqual(r3.exit_code, 0, r3.output)
        self.assertTrue(out.is_file())
        r4 = self.runner.invoke(cli, ["branch", "remove", "Copy of Draft"])
        self.assertEqual(r4.exit_code, 0, r4.output)

    def test_memory_cli(self) -> None:
        r1 = self.runner.invoke(cli, ["memory", "report", "lesson-1", "--quality", "2"])
        self.assertEqual(r1.exit_code, 0, r1.output)
        # SM-2 schedules a failed review for +1 day; force due for the listing check.
        sess = CliSession()
        prog = (sess._data.get("memory") or {}).get("local_progress") or {}
        row = prog.get("lesson-1")
        self.assertIsInstance(row, dict)
        row["dueDate"] = 0
        sess.save()
        r2 = self.runner.invoke(cli, ["memory", "due"])
        self.assertEqual(r2.exit_code, 0, r2.output)
        self.assertIn("lesson-1", r2.output)

    def test_no_retired_commands(self) -> None:
        for argv in (["forest", "list"], ["refresh"], ["narrative", "--help"], ["session", "sync"]):
            result = self.runner.invoke(cli, argv)
            self.assertNotEqual(result.exit_code, 0, argv)

    def test_app_pow_roundtrip(self) -> None:
        _bits, nonce = solve_app_pow(
            "forum_message_v1", "owner", "uid", "bucket", "actor", salt="test"
        )
        self.assertTrue(nonce)
        self.assertTrue(
            verify_app_pow("forum_message_v1", "owner", "uid", "bucket", "actor", nonce)
        )


if __name__ == "__main__":
    unittest.main()

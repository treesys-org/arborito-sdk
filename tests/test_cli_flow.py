"""CLI integration — numbered list → go → lesson read (advance-test style)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner

from arborito_sdk.cli_app import cli
from helpers import _make_mini_arborito


class CliFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "sdk-home"
        import os

        os.environ["ARBORITO_SDK_HOME"] = str(self.home)
        self.path = _make_mini_arborito(Path(self._tmp.name))
        self.runner = CliRunner()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_list_numbered_children(self) -> None:
        result = self.runner.invoke(cli, ["list", str(self.path)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("1.", result.output)
        self.assertIn("Module", result.output)

    def test_go_where_and_back(self) -> None:
        runner = CliRunner()
        runner.invoke(cli, ["go", "1", str(self.path)])
        r2 = runner.invoke(cli, ["go", "where", str(self.path)])
        self.assertEqual(r2.exit_code, 0, r2.output)
        self.assertIn("Module", r2.output)
        r3 = runner.invoke(cli, ["go", "back", str(self.path)])
        self.assertEqual(r3.exit_code, 0, r3.output)

    def test_quoted_literal_name(self) -> None:
        runner = CliRunner()
        runner.invoke(cli, ["go", "1", str(self.path)])
        r = runner.invoke(cli, ["go", "where", str(self.path)])
        self.assertEqual(r.exit_code, 0, r.output)

    def test_read_and_edit_show(self) -> None:
        runner = CliRunner()
        runner.invoke(cli, ["go", "1", str(self.path)])
        runner.invoke(cli, ["go", "1", str(self.path)])
        r1 = runner.invoke(cli, ["read", str(self.path)])
        self.assertEqual(r1.exit_code, 0, r1.output)
        self.assertIn("Hello from module one", r1.output)
        self.assertIn("Quiz", r1.output)
        self.assertNotIn("@/quiz", r1.output)
        r2 = runner.invoke(cli, ["edit", "--show", "--raw", str(self.path)])
        self.assertEqual(r2.exit_code, 0, r2.output)
        self.assertIn("@quiz", r2.output)

    def test_list_lessons_flag(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["list", "--lessons", str(self.path)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Lesson A", result.output)

    def test_go_by_index_and_lesson_read(self) -> None:
        r1 = self.runner.invoke(cli, ["go", "1", str(self.path)])
        self.assertEqual(r1.exit_code, 0, r1.output)
        r2 = self.runner.invoke(cli, ["list", str(self.path)])
        self.assertEqual(r2.exit_code, 0, r2.output)
        self.assertIn("Lesson", r2.output)
        r3 = self.runner.invoke(cli, ["go", "1", str(self.path)])
        self.assertEqual(r3.exit_code, 0, r3.output)
        r4 = self.runner.invoke(cli, ["read", str(self.path)])
        self.assertEqual(r4.exit_code, 0, r4.output)
        self.assertIn("Hello from module one", r4.output)

    def test_list_modules_flag(self) -> None:
        result = self.runner.invoke(cli, ["list", "--modules", str(self.path)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Module", result.output)
        self.assertIn("Story", result.output)

    def test_config_relay_session(self) -> None:
        r1 = self.runner.invoke(cli, ["config", "relay", "set", "wss://relay.example.com"])
        self.assertEqual(r1.exit_code, 0, r1.output)
        r2 = self.runner.invoke(cli, ["config", "relay", "list"])
        self.assertEqual(r2.exit_code, 0, r2.output)
        self.assertIn("wss://relay.example.com", r2.output)
        r3 = self.runner.invoke(cli, ["config", "relay", "reset"])
        self.assertEqual(r3.exit_code, 0, r3.output)

    def test_config_ai_list(self) -> None:
        result = self.runner.invoke(cli, ["config", "ai", "list"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("mode:", result.output)

    def test_branch_list_empty(self) -> None:
        result = self.runner.invoke(cli, ["branch", "list"])
        self.assertEqual(result.exit_code, 0, result.output)

    def test_no_refresh_command(self) -> None:
        result = self.runner.invoke(cli, ["refresh", str(self.path)])
        self.assertNotEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()

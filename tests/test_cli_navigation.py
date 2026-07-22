"""CLI navigation / load correctness."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from arborito_sdk.cli_app import cli
from arborito_sdk.cli_focus import apply_node_focus
from arborito_sdk.cli_session import CliSession
from arborito_sdk.client import Arborito
from helpers import _make_mini_arborito


def test_second_module_go_keeps_catalog(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ARBORITO_SDK_HOME", str(tmp_path / "home"))
    path = _make_mini_arborito(tmp_path)
    api = Arborito.from_arborito(path, lang="ES", username="cli", avatar="🌳")
    root = api.tree.root()
    assert root
    modules = [c for c in (root.get("children") or []) if c.get("type") == "branch"]
    assert len(modules) >= 2
    sess = CliSession()
    apply_node_focus(api, sess, modules[0])
    assert api.lesson.list()
    apply_node_focus(api, sess, modules[1])
    assert api.lesson.list(), "second module must still resolve lessons from catalog"
    apply_node_focus(api, sess, root)
    assert len(api.lesson.list()) >= 2


def test_local_file_preferred_over_stale_nostr_ref(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ARBORITO_SDK_HOME", str(tmp_path / "home"))
    path = _make_mini_arborito(tmp_path)
    sess = CliSession()
    sess.set_focus(source=str(path.resolve()), tree_name="Test")
    sess.set_nostr_ref("ab" * 32, "uid-fake")
    sess.save()
    from arborito_sdk.cli_app import _load_api

    api, _label = _load_api(sess)
    assert Path(sess.focus["source"]).is_file()
    assert api.lesson.list()


def test_open_branch_clears_stale_lesson_focus(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ARBORITO_SDK_HOME", str(tmp_path / "home"))
    path = _make_mini_arborito(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["branch", "import", str(path)])
    sess = CliSession()
    sess.set_focus(module_id="mod-stale", module_name="Stale", lesson_id="leaf-stale", lesson_name="Stale")
    sess.save()
    from arborito_sdk.cli_library import open_branch

    open_branch(sess, "Test Course")
    assert sess.focus.get("lesson_id") == ""
    assert sess.focus.get("module_id") == ""


def test_list_lessons_is_one_based(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ARBORITO_SDK_HOME", str(tmp_path / "home"))
    path = _make_mini_arborito(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["list", "--lessons", str(path)])
    assert result.exit_code == 0, result.output
    assert "  1  " in result.output or "\n  1  " in result.output or result.output.lstrip().startswith("1")
    assert not any(line.lstrip().startswith("0 ") for line in result.output.splitlines())


def test_go_same_path_preserves_module_focus(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ARBORITO_SDK_HOME", str(tmp_path / "home"))
    path = _make_mini_arborito(tmp_path)
    runner = CliRunner()
    r1 = runner.invoke(cli, ["go", "1", str(path)])
    assert r1.exit_code == 0, r1.output
    sess = CliSession()
    mid = sess.focus.get("module_id")
    assert mid
    r2 = runner.invoke(cli, ["go", "where", str(path)])
    assert r2.exit_code == 0, r2.output
    sess2 = CliSession()
    assert sess2.focus.get("module_id") == mid

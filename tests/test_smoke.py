"""Smoke tests — no .arborito fixture required."""

from __future__ import annotations

from arborito_sdk import Arborito, ArboritoError, ERROR_CODES
from arborito_sdk.quiz_v2 import (
    challenge_for_play,
    is_challenge_complete,
    mode_label,
    parse_all_challenges_from_content,
    static_quiz_from_challenge,
    tokenize_quiz_answer_chips,
)


def test_import_public_api():
    assert Arborito is not None
    assert ArboritoError is not None
    assert ERROR_CODES["TIMEOUT"] == "AI_TIMEOUT"


def test_flashcard_items_recall():
    md = """@quiz
items:
  - concept: ging
    definition: fue
@/quiz
"""
    challenges = parse_all_challenges_from_content(md)
    assert len(challenges) == 1
    assert is_challenge_complete(challenges[0])
    played = challenge_for_play(challenges[0])
    assert played["correct_answer"] == "fue"
    sq = static_quiz_from_challenge(challenges[0], "T", 1, "EN")
    assert "What is" in sq[0]["q"]


def test_chips_tokenizer_parentheses():
    tokens = tokenize_quiz_answer_chips("(saludo informal) Hola")
    assert tokens == ["(saludo informal)", "Hola"]


def test_share_code_normalize():
    from arborito_sdk.nostr_protocol import normalize_tree_share_code

    assert normalize_tree_share_code("abcd-ef23") == "ABCD-EF23"
    assert normalize_tree_share_code("ABCD EF23") == "ABCD-EF23"
    assert normalize_tree_share_code("short") is None


def test_default_relays_match_arborito():
    from arborito_sdk.nostr_relays import DEFAULT_NOSTR_RELAYS

    assert "wss://relay.tchncs.de" in DEFAULT_NOSTR_RELAYS
    assert len(DEFAULT_NOSTR_RELAYS) >= 5


def test_bundle_main_chunk_d_tag():
    from arborito_sdk.nostr_protocol import bundle_main_chunk_d_tag

    d = bundle_main_chunk_d_tag("ab" * 32, "uid-1", 2)
    assert d == f"arborito:bundle:main:{'ab' * 32}:uid-1:2"


def test_websocket_client_dependency():
    from arborito_sdk.nostr_client import require_websocket_client

    require_websocket_client()
    import websocket

    assert hasattr(websocket, "create_connection")


def test_nostr_client_relay_health():
    from arborito_sdk.nostr_client import NostrClient, require_websocket_client

    require_websocket_client()
    client = NostrClient(["wss://relay.primal.net"], query_timeout=1.0)
    client._note_relay_fail("wss://127.0.0.1:9")
    snap = client.relay_health_snapshot()
    assert snap["count"] == 1
    assert not client._relay_live("wss://127.0.0.1:9")
    live = client._filter_live_relays(["wss://127.0.0.1:9", "wss://relay.primal.net"])
    assert live == ["wss://relay.primal.net"]


def test_mode_label_en():
    assert mode_label("cloze", "EN") == "Fill blank"
    assert mode_label("cloze", "ES") == "Hueco"


def test_cli_console_script_entry_point():
    """Installed wheel must expose ``arborito-cli`` only (no retired console script names)."""
    from importlib.metadata import entry_points

    names = {ep.name for ep in entry_points(group="console_scripts") if ep.value == "arborito_sdk.cli:main"}
    assert names == {"arborito-cli"}, names
    retired = {"arborito-sdk", "arborito"}
    assert not (names & retired), f"retired console scripts still registered: {names & retired}"


def test_cli_help_loads():
    from click.testing import CliRunner

    from arborito_sdk.cli_app import cli

    runner = CliRunner()
    result = runner.invoke(cli, [])
    assert result.exit_code == 0, result.output
    assert "Arborito SDK" in result.output
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(cli, ["branch", "list", "--help"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(cli, ["memory", "due", "--help"])
    assert result.exit_code == 0, result.output


def test_repl_entry_single_arborito(tmp_path, monkeypatch):
    from arborito_sdk.cli_app import _repl_from_argv

    from helpers import _make_mini_arborito

    monkeypatch.setenv("ARBORITO_SDK_HOME", str(tmp_path / "sdk-home"))
    path = _make_mini_arborito(tmp_path)
    from unittest.mock import patch

    with patch("builtins.input", side_effect=EOFError):
        code = _repl_from_argv([str(path)])
    assert code == 0


def test_cli_subcommand_session_context():
    """Subcommands must receive CliSession (regression: make_pass_decorator)."""
    from click.testing import CliRunner

    from arborito_sdk.cli_app import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["session", "whoami"])
    assert result.exit_code == 0, result.output
    assert "Managed to invoke callback without a context" not in (result.output or result.exception or "")


def test_login_password_strength():
    from arborito_sdk.login_password import evaluate_login_password_strength

    weak = evaluate_login_password_strength("abc")
    assert weak["level"] == "weak" and not weak["ok"]
    strong = evaluate_login_password_strength("Arborito2026!")
    assert strong["ok"] and strong["level"] in ("good", "strong")


def test_login_password_hash_kinds():
    from arborito_sdk.login_password import hash_login_credential
    from arborito_sdk.nostr_protocol import CREDENTIAL_KIND_PASSWORD, CREDENTIAL_KIND_SYNC_CODE

    pw = hash_login_credential("MyPassword10!", CREDENTIAL_KIND_PASSWORD)
    code = hash_login_credential("A1B2-C3D4-E5F6-7890-ABCD-EF01", CREDENTIAL_KIND_SYNC_CODE)
    assert pw != code
    assert hash_login_credential("MyPassword10!", CREDENTIAL_KIND_PASSWORD) == pw


def test_looks_like_sync_secret_code():
    from arborito_sdk.login_password import looks_like_sync_secret_code

    assert looks_like_sync_secret_code("A1B2-C3D4-E5F6-7890-ABCD-EF01")
    assert looks_like_sync_secret_code("0000-0000-0000-0000")
    assert not looks_like_sync_secret_code("short")
    assert not looks_like_sync_secret_code("MyPassword10!")
    assert not looks_like_sync_secret_code("ABCD-EFGH-IJKL-MNOP")

"""Rsync-style Care/progress merge (parity with Arborito progress-sync-merge.js)."""

from __future__ import annotations

from arborito_sdk.progress_sync import (
    fingerprint_progress_payload,
    is_progress_payload_empty,
    merge_progress_snapshots,
    merge_remote_gamification,
    should_publish_merged_progress,
)


def test_empty_payload_guards():
    assert is_progress_payload_empty(None) is True
    assert is_progress_payload_empty({"progress": [], "gamification": {"avatar": "👤"}}) is True
    assert is_progress_payload_empty({"progress": ["lesson-1"]}) is False
    assert is_progress_payload_empty({"progress": [], "gamification": {"avatar": "🦊"}}) is False
    assert is_progress_payload_empty({"progress": [], "gamification": {"weeklyLumens": 3}}) is False


def test_fingerprint_ignores_top_level_updated_at():
    a = {
        "v": 1,
        "updatedAt": "2026-01-01T00:00:00.000Z",
        "progress": ["b", "a"],
        "gamification": {"avatar": "🦊", "xp": 10, "profileUpdatedAt": "2026-01-02"},
        "memory": {},
        "bookmarks": {},
        "gameData": {},
        "arcadeSaves": {},
    }
    b = {**a, "updatedAt": "2026-07-22T00:00:00.000Z", "progress": ["a", "b"]}
    assert fingerprint_progress_payload(a) == fingerprint_progress_payload(b)


def test_merge_unions_progress_and_keeps_newer_emoji():
    merged = merge_progress_snapshots(
        {
            "progress": ["local-only"],
            "gamification": {"avatar": "🌱", "profileUpdatedAt": "2026-01-01T00:00:00.000Z", "xp": 3},
        },
        {
            "progress": ["remote-only"],
            "gamification": {
                "avatar": "🦊",
                "profileUpdatedAt": "2026-06-01T00:00:00.000Z",
                "xp": 12,
            },
        },
    )
    assert sorted(merged["progress"]) == ["local-only", "remote-only"]
    assert merged["gamification"]["avatar"] == "🦊"
    assert merged["gamification"]["xp"] == 12


def test_should_publish_only_when_content_differs():
    remote = {
        "progress": ["a"],
        "gamification": {"avatar": "🦊", "xp": 5, "profileUpdatedAt": "2026-06-01"},
        "memory": {},
        "bookmarks": {},
        "gameData": {},
        "arcadeSaves": {},
    }
    same = merge_progress_snapshots({}, remote)
    assert should_publish_merged_progress(remote=remote, merged=same) is False

    richer = merge_progress_snapshots({"progress": ["b"]}, remote)
    assert should_publish_merged_progress(remote=remote, merged=richer) is True

    assert (
        should_publish_merged_progress(
            remote=None,
            merged={
                "progress": ["a"],
                "gamification": {},
                "memory": {},
                "bookmarks": {},
                "gameData": {},
                "arcadeSaves": {},
            },
        )
        is True
    )
    assert should_publish_merged_progress(remote=None, merged={"progress": []}) is False


def test_local_newer_emoji_not_overwritten_by_stale_remote():
    local = {"avatar": "🐸", "profileUpdatedAt": "2026-07-01T00:00:00.000Z", "xp": 1}
    remote = {"avatar": "🦊", "profileUpdatedAt": "2026-01-01T00:00:00.000Z", "xp": 9}
    out = merge_remote_gamification(local, remote)
    assert out["avatar"] == "🐸"
    assert out["xp"] == 9

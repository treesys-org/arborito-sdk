"""Unit tests for ask.fromCourse / speak / reply / check prompts (no live LLM)."""

from __future__ import annotations

from arborito_sdk.play_session import (
    COURSE_TOPICS,
    build_check_judge_prompt,
    build_course_card_from_playlist,
    build_reply_prompt,
    build_speak_prompt,
    score_topic_blob,
)


def test_course_topics_cover_basics() -> None:
    assert "greeting" in COURSE_TOPICS
    assert "origin" in COURSE_TOPICS
    assert "purpose" in COURSE_TOPICS
    assert "goodbye" in COURSE_TOPICS


def test_score_topic_blob_greeting() -> None:
    assert score_topic_blob("greeting", "Hello / My name is Bob") >= 2
    assert score_topic_blob("greeting", "photosynthesis chloroplast") == 0


def test_speak_prompt_has_no_questionnaire_pollution() -> None:
    p = build_speak_prompt("Mike, strict boss", "Julius is missing. Go to Hotel Pentfive.")
    assert "Julius" in p
    assert "questionnaire" not in p.lower()
    assert "playlist" not in p.lower()
    assert "Never talk about lessons" in p
    assert '{"line"' in p


def test_reply_prompt_uses_facts_only() -> None:
    p = build_reply_prompt(
        "Mike. Wants the player to accept the mission.",
        "What happened to Julius?",
        ["Julius disappeared in England", "Last lead is Hotel Pentfive"],
    )
    assert "Julius disappeared in England" in p
    assert "What happened to Julius?" in p
    assert "questionnaire" not in p.lower()
    assert "practice hooks" not in p.lower()


def test_check_judge_prompt() -> None:
    card = {
        "question": "Comment vous appelez-vous ?",
        "accept": ["je m'appelle"],
        "example": "Je m'appelle Bob.",
    }
    p = build_check_judge_prompt("je mappelle bob", card)
    assert "Comment vous appelez-vous" in p
    assert "je m'appelle" in p


class _FakeClient:
    def __init__(self, playlist: list) -> None:
        self._playlist = playlist


def test_from_course_builds_card_from_quiz_items() -> None:
    lesson = {
        "title": "Greetings",
        "text": "Hello. My name is Ana.",
        "challenges": [
            {
                "main_question": "How do you say your name?",
                "correct_answer": "My name is Bob",
                "core_concept": "greeting name",
                "traps": ["Goodbye"],
            }
        ],
    }
    client = _FakeClient([lesson])
    card = build_course_card_from_playlist(client, "greeting", lang="EN")
    assert card is not None
    assert card["topic"] == "greeting"
    assert card["question"] or card["accept"]
    assert any(
        "name" in a.lower() or "hello" in a.lower()
        for a in (card["accept"] or [card["question"]])
    )


def test_from_course_unknown_topic() -> None:
    assert build_course_card_from_playlist(_FakeClient([]), "algebra") is None

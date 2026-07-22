"""Quiz helper tests."""

from __future__ import annotations

from arborito_sdk import Arborito, User
from arborito_sdk.quiz_v2 import (
    answers_match,
    normalize_answer_text,
    pick_unused_quiz,
)


def test_normalize_answer_text_smart_quotes():
    assert normalize_answer_text('"Hola"') == '"hola"'
    assert normalize_answer_text("\u201cHola\u201d") == '"hola"'


def test_answers_match_typo_levenshtein():
    assert answers_match("photosynthesis", "photosyntesis")
    assert answers_match("alpha", "alphea")
    assert not answers_match("totally unrelated", "photosynthesis")


def test_answers_match_substring_and_overlap():
    assert answers_match("the correct answer", "correct answer")
    assert not answers_match("", "x")
    assert not answers_match("totally unrelated", "photosynthesis")


def test_pick_unused_quiz_persists_dict_session():
    pool = [
        {"q": "Q1", "correct": "A", "topic": "T"},
        {"q": "Q2", "correct": "B", "topic": "T"},
    ]
    session: dict = {}
    first = pick_unused_quiz(pool, session)
    second = pick_unused_quiz(pool, session)
    assert first and second
    assert first["q"] != second["q"]
    assert isinstance(session.get("used"), set)
    assert len(session["used"]) == 2


def test_matches_any():
    from arborito_sdk.client import attach_helpers

    api = Arborito([], User("t", "EN"), ai_mode="static")
    attach_helpers(api)
    hit = api.quiz.matches_any("alpha", ["beta", "Alpha"])
    assert hit == {"ok": True, "matched": "Alpha"}
    miss = api.quiz.matches_any("nope", ["beta", "gamma"])
    assert miss == {"ok": False, "matched": None}


def test_lesson_by_id_after_set_playlist():
    api = Arborito([], User("t", "EN"), ai_mode="static")
    lesson = {"id": "L1", "title": "One", "text": "Body"}
    api.lesson.set_playlist([lesson])
    hit = api.lesson.by_id("L1")
    assert hit is not None
    assert hit["title"] == "One"


def test_context_for_ai_includes_title():
    api = Arborito([], User("t", "EN"), ai_mode="static")
    lesson = {"id": "L1", "title": "Photosynthesis", "text": "Plants use light."}
    block = api.lesson.context_for_ai(lesson)
    assert "Photosynthesis" in block


def test_grade_answer_static_exact_match():
    from arborito_sdk.client import attach_helpers

    api = Arborito([], User("t", "EN"), ai_mode="static")
    attach_helpers(api)
    lesson = {"id": "L1", "title": "T", "text": "x"}
    item = {"q": "What?", "correct": "Alpha"}
    assert api.quiz.grade_answer(lesson, item, "alpha") is True
    assert api.quiz.grade_answer(lesson, item, "wrong") is False


def test_grade_answer_resolves_lesson_from_pool_item():
    from arborito_sdk.client import attach_helpers

    lesson = {"id": "L1", "title": "T", "text": "Plants.", "raw": "Plants."}
    api = Arborito([lesson], User("t", "EN"), ai_mode="static")
    attach_helpers(api)
    item = {"q": "What?", "correct": "Light", "lessonId": "L1"}
    resolved = api.lesson.by_id(item["lessonId"])
    assert api.quiz.grade_answer(resolved, item, "light") is True


def test_challenge_tasks_from_lesson():
    api = Arborito([], User("t", "EN"), ai_mode="static")
    lesson = {
        "id": "L1",
        "title": "Shell",
        "raw": (
            "@quiz\n"
            "core_concept: ls\n"
            "short_definition: list files\n"
            "main_question: What lists files?\n"
            "correct_answer: ls\n"
            "traps: cd, pwd\n"
            "@/quiz\n"
            "```bash\n$ echo hi\nhi\n```\n"
        ),
        "text": "What lists files?",
        "challenge": {
            "core_concept": "ls",
            "short_definition": "list files",
            "main_question": "What lists files?",
            "correct_answer": "ls",
            "traps": ["cd", "pwd"],
        },
    }
    tasks = api.challenge.tasksFromLesson(lesson, {"max": 20, "lang": "EN"})
    assert tasks
    kinds = {t.get("kind") for t in tasks}
    assert "quiz" in kinds
    assert "code" in kinds
    no_code = api.challenge.tasksFromLesson(
        lesson, {"max": 20, "includeCodeReplays": False}
    )
    assert all(t.get("kind") != "code" for t in no_code)


def test_find_code_replay():
    from arborito_sdk.client import attach_helpers
    from arborito_sdk.content import code_replays_from_lesson

    api = Arborito([], User("t", "EN"), ai_mode="static")
    attach_helpers(api)
    lesson = {"raw": "```bash\n$ echo hi\nhi\n```\n", "text": ""}
    replays = code_replays_from_lesson(lesson)
    hit = api.quiz.find_code_replay("echo hi", replays)
    assert hit and hit["replay"]["cmd"] == "echo hi" and hit["fuzzy"] is False
    fuzzy = api.quiz.find_code_replay("echo hii", replays)
    assert fuzzy and fuzzy["fuzzy"] is True
    miss = api.quiz.find_code_replay("ls -la", replays)
    assert miss is None
    via_lesson = api.quiz.find_code_replay("$ echo hi", lesson=lesson)
    assert via_lesson and via_lesson["replay"]["output"] == "hi"

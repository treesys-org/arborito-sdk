"""Regression: flashcard-style quizzes must never show blank MC pads."""

from __future__ import annotations

from arborito_sdk.quiz_v2 import (
    build_mode_card,
    build_quiz_options,
    get_challenges_from_lesson,
    lesson_answer_pool,
    pick_static_wrong,
    static_quiz_from_lesson,
    tasks_from_lesson,
)

FLASHCARD_LESSON = {
    "title": "Flashcards palabras",
    "raw": """@quiz
items:
  - concept: erledigen
    definition: resolver, diligenciar debidamente
  - concept: beantragen
    definition: solicitar (p. ej. un Visum)
  - concept: Behörde
    definition: autoridad competente
@/quiz
""",
}

JUNK = {":", ": ", "—", "-", "–", "…", "...", "N/A", "Unknown", "___", "______"}


def _assert_clean_options(options: list[str]) -> None:
    assert len(options) >= 2
    for opt in options:
        assert str(opt).strip()
        assert str(opt).strip() not in JUNK


def test_flashcard_recall_uses_sibling_answers():
    challenges = get_challenges_from_lesson(FLASHCARD_LESSON)
    pool = lesson_answer_pool(challenges)
    assert len(pool) == 3
    card = build_mode_card(challenges[0], "recall", lang="ES", distractor_pool=pool)
    assert card is not None
    _assert_clean_options(card["options"])
    assert "resolver, diligenciar debidamente" in card["options"]
    assert "solicitar (p. ej. un Visum)" in card["options"] or "autoridad competente" in card["options"]
    assert not any(str(o).startswith("Incorrecto") for o in card["options"])


def test_tasks_from_lesson_includes_real_options():
    tasks = tasks_from_lesson(FLASHCARD_LESSON, lang="ES", max_tasks=20, include_code_replays=False)
    recall = [t for t in tasks if t.get("mode") == "recall"]
    assert recall
    for t in recall:
        opts = t.get("options") or []
        _assert_clean_options(opts)
        assert t.get("correct") or t.get("output")
        assert not any(str(o).strip() in JUNK for o in opts)


def test_lonely_flashcard_pads_readable_not_blank():
    lonely = {
        "core_concept": "solo",
        "short_definition": "única definición",
        "traps": [],
    }
    assert pick_static_wrong(lonely) == ""
    card = build_mode_card(lonely, "recall", lang="ES")
    assert card is not None
    _assert_clean_options(card["options"])
    assert any(str(o).startswith("Incorrecto") for o in card["options"])


def test_static_quiz_sibling_wrongs():
    items = static_quiz_from_lesson(FLASHCARD_LESSON, count=5, lang="ES")
    assert len(items) >= 2
    for it in items:
        assert it["wrong"]
        assert it["wrong"] not in JUNK
        assert it["wrong"] != it["correct"]


def test_static_quiz_count_one_still_gets_sibling_wrong():
    """curriculum pool uses count=1; wrong must come from the full lesson pool."""
    item = static_quiz_from_lesson(FLASHCARD_LESSON, count=1, lang="ES")
    assert len(item) == 1
    assert item[0]["wrong"]
    assert item[0]["wrong"] not in JUNK
    assert item[0]["wrong"] != item[0]["correct"]
    opts = build_quiz_options(item[0], count=4, lang="ES")
    _assert_clean_options(opts)
    assert item[0]["correct"] in opts
    assert item[0]["wrong"] in opts


def test_build_quiz_options_rejects_junk_pads():
    opts = build_quiz_options(
        {"correct": "foo", "wrong": ": ", "traps": ["—", "N/A"]},
        count=3,
        lang="ES",
        distractor_pool=["bar"],
    )
    _assert_clean_options(opts)
    assert "foo" in opts and "bar" in opts


def test_multiple_mode_rejects_junk_only_traps():
    from arborito_sdk.quiz_v2 import mode_is_playable

    ch = {
        "main_question": "¿Qué es X?",
        "correct_answer": "bien",
        "traps": [": ", "—", "N/A"],
    }
    assert mode_is_playable(ch, "multiple") is False

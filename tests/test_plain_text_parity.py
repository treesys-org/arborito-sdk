"""Parity helpers: plainText and naming aliases."""

from __future__ import annotations

from arborito_sdk.content import lesson_plain_text
from arborito_sdk.client import _LessonNS


def test_lesson_plain_text_strips_section_and_quiz():
    raw = """@section
index: 1
title: Intro
@/section

Hello **world**.

@quiz
concept: c
correct_answer: a
@/quiz
"""
    assert lesson_plain_text(raw) == "Hello world."
    assert lesson_plain_text({"raw": raw}) == "Hello world."
    assert _LessonNS.plainText(raw) == "Hello world."
    assert _LessonNS.plain_text(raw) == "Hello world."


def test_lesson_arcade_aliases_exist():
    assert _LessonNS.readMeta is _LessonNS.read_meta
    assert _LessonNS.byId is _LessonNS.by_id
    assert _LessonNS.contextForAi is _LessonNS.context_for_ai
    assert _LessonNS.branchProfile is _LessonNS.branch_profile

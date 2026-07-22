"""Lesson document parse/serialize for CLI editor."""

from __future__ import annotations

import unittest

from arborito_sdk.lesson_document import (
    LessonDocument,
    ProseBlock,
    QuizBlock,
    format_lesson_for_terminal,
    parse_lesson_document,
)
from arborito_sdk.quiz_v2 import parse_quiz_block, serialize_quiz_block


SAMPLE = """@info
title: Demo
tags: test, cli
@/info

# Intro

Hello world.

@quiz
concept: Linux
definition: Sistema {operativo} libre
question: ¿Qué es Linux?
answer: Un SO open source
traps:
  - Un editor
  - Una DB
@/quiz

@section
title: Siguiente tema
@/section

More text.
"""


class LessonDocumentTests(unittest.TestCase):
    def test_roundtrip_quiz(self) -> None:
        body = """@quiz
concept: A
question: Q?
answer: R
traps:
  - X
@/quiz"""
        c = parse_quiz_block(body.splitlines()[1:-1])
        again = serialize_quiz_block(c)
        self.assertIn("concept: A", again)
        self.assertIn("@/quiz", again)
        doc = parse_lesson_document(body)
        self.assertEqual(len(doc.blocks), 1)
        self.assertIsInstance(doc.blocks[0], QuizBlock)

    def test_parse_and_serialize_document(self) -> None:
        doc = parse_lesson_document(SAMPLE)
        self.assertIsNotNone(doc.info)
        self.assertEqual(doc.info.fields.get("title"), "Demo")
        kinds = [type(b).__name__ for b in doc.blocks]
        self.assertIn("ProseBlock", kinds)
        self.assertIn("QuizBlock", kinds)
        raw = doc.to_markdown()
        doc2 = parse_lesson_document(raw)
        self.assertEqual(len(doc2.blocks), len(doc.blocks))

    def test_format_terminal_hides_quiz_fence(self) -> None:
        out = format_lesson_for_terminal(SAMPLE, title="Demo")
        self.assertIn("Quiz", out)
        self.assertIn("Concept: Linux", out)
        self.assertNotIn("@/quiz", out)

    def test_prose_only(self) -> None:
        doc = LessonDocument(blocks=[ProseBlock(text="Hola\nmundo")])
        md = doc.to_markdown()
        self.assertIn("Hola", md)
        self.assertNotIn("@quiz", md)


if __name__ == "__main__":
    unittest.main()

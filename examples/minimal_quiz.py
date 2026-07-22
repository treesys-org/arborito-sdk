#!/usr/bin/env python3
"""Minimal quiz loop — load a course, show one card, check the answer.

No AI required (static mode). This is the smallest path from lesson → challenge → your UI.

Usage:
    python examples/minimal_quiz.py path/to/course.arborito
    python examples/minimal_quiz.py path/to/course.arborito ES

Requires: pip install -e .  (from the arborito-sdk repo root)
"""

from __future__ import annotations

import sys
from pathlib import Path

from arborito_sdk import Arborito


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python examples/minimal_quiz.py <course.arborito> [LANG]", file=sys.stderr)
        return 1

    path = Path(sys.argv[1])
    lang = (sys.argv[2] if len(sys.argv) > 2 else "EN").upper()

    api = Arborito.from_arborito(path, lang=lang, ai_mode="static")
    entries = api.lesson.list()
    if not entries:
        print("No lessons in archive.")
        return 1

    print(f"Loaded {len(entries)} lessons from {path.name}\n")
    for i, entry in enumerate(entries[:5]):
        print(f"  [{i}] {entry.get('title') or entry.get('id')}")
    if len(entries) > 5:
        print(f"  … and {len(entries) - 5} more")

    lesson = api.lesson.at(0)
    if not lesson:
        print("\nCould not load first lesson.")
        return 1

    challenges = api.challenge.fromLesson(lesson)
    if not challenges:
        print("\nFirst lesson has no @quiz blocks. Export a course with questionnaires.")
        return 0

    from arborito_sdk.quiz_v2 import lesson_answer_pool

    sibling_pool = lesson_answer_pool(challenges)
    challenge = challenges[0]
    playable = api.challenge.modes.playable(challenge)
    if not playable:
        print("\nFirst questionnaire is incomplete (authoring).")
        return 0

    mode = playable[0]
    card = api.challenge.modes.buildCard(
        challenge,
        mode,
        lesson_title=lesson.get("title") or "",
        lang=lang,
        distractor_pool=sibling_pool,
    )
    question = card.get("question") or "(no prompt)"
    correct = str(card.get("correct") or "").strip()
    options = list(card.get("options") or [])

    print(f"\n--- {api.challenge.modes.label(mode, lang)} ---")
    print(question)
    if options:
        for i, option in enumerate(options, 1):
            print(f"  {i}) {option}")
    else:
        print("  (type your answer)")

    try:
        answer = input("\nYour answer: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0

    if not answer:
        print(f"Skipped. Correct: {correct or '(see card)'}")
        return 0

    accept = [correct] if correct else []
    accept.extend(str(o).strip() for o in options if str(o).strip())
    hit = api.quiz.matches_any(answer, accept)
    if hit.get("ok"):
        print("Correct!")
    else:
        print(f"Not quite. Correct: {correct or hit.get('matched') or '(see card)'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

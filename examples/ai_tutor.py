#!/usr/bin/env python3
"""Minimal AI tutor — one SDK call: ask.lesson_action.

Loads the active branch, reuses author questionnaires, and answers in character.
Requires a local llama.cpp server (OpenAI-compatible API).

Usage:
    python examples/ai_tutor.py path/to/course.arborito
    LLAMA_CPP_HOST=http://127.0.0.1:8080 python examples/ai_tutor.py course.arborito ES

Tip: arborito-cli config ai set mode dynamic
"""

from __future__ import annotations

import sys
from pathlib import Path

from arborito_sdk import Arborito
from arborito_sdk.ai_util import detect_llama_host, ping_llama
from arborito_sdk.errors import ArboritoError


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python examples/ai_tutor.py <course.arborito> [LANG]", file=sys.stderr)
        return 1

    path = Path(sys.argv[1])
    lang = (sys.argv[2] if len(sys.argv) > 2 else "EN").upper()

    host = detect_llama_host()
    ping = ping_llama(host)
    if not ping.get("ok"):
        print(
            "No AI server found.\n"
            f"  Tried: {host}\n"
            "  Start llama.cpp (llama-server) or set LLAMA_CPP_HOST.\n"
            "  Static quiz without AI: python examples/minimal_quiz.py …",
            file=sys.stderr,
        )
        return 1

    api = Arborito.from_arborito(path, lang=lang, ai_mode="dynamic", llamacpp_host=host)
    lesson = api.lesson.at(0)
    if not lesson:
        print("No lessons in archive.")
        return 1

    profile = api.lesson.branch_profile(lesson)
    title = lesson.get("title") or lesson.get("id") or "Lesson 1"
    persona = (
        "You are a friendly study tutor. Use facts from the author's questionnaire first. "
        "Keep replies short (under 8 lines)."
    )

    print(f"Tutor ready — {title}")
    print(f"Branch language hint: {profile.get('learnLangLabel') or profile.get('learnLang') or 'auto'}")
    print("Type a question about the lesson (empty line to quit).\n")

    while True:
        try:
            player_said = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not player_said:
            break

        try:
            res = api.ask.lesson_action(
                lesson,
                player_said,
                {"persona": persona, "profile": profile},
            )
        except ArboritoError as err:
            print(f"Tutor: (AI error — {err.code}) {err}")
            continue
        except Exception as err:
            print(f"Tutor: (error) {err}")
            continue

        output = ""
        if isinstance(res, dict):
            output = str(res.get("output") or "").strip()
        if not output:
            output = "(no reply — check the model returned JSON with an output field)"
        print(f"Tutor: {output}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

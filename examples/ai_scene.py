#!/usr/bin/env python3
"""Minimal dynamic scene — fromCourse / speak / reply / check.

Same difficulty as minimal_quiz.py, but for story + course speaking gates.
Requires a local llama.cpp server for speak/reply (check works partly static).

Usage:
    python examples/ai_scene.py path/to/course.arborito
    python examples/ai_scene.py path/to/course.arborito ES
"""

from __future__ import annotations

import sys
from pathlib import Path

from arborito_sdk import Arborito
from arborito_sdk.ai_util import detect_llama_host, ping_llama
from arborito_sdk.errors import ArboritoError


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python examples/ai_scene.py <course.arborito> [LANG]", file=sys.stderr)
        return 1

    path = Path(sys.argv[1])
    lang = (sys.argv[2] if len(sys.argv) > 2 else "EN").upper()
    host = detect_llama_host()
    ping = ping_llama(host)
    dynamic = bool(ping.get("ok"))
    api = Arborito.from_arborito(
        path,
        lang=lang,
        ai_mode="dynamic" if dynamic else "static",
        llamacpp_host=host if dynamic else None,
    )

    print("— speak (authored line) —")
    try:
        line = api.ask.speak(
            "Mike, strict boss",
            "Julius has been missing. Investigate Hotel Pentfive.",
        )["line"]
    except ArboritoError as err:
        print(f"(speak skipped: {err})")
        line = "Julius has been missing. Investigate Hotel Pentfive."
    print(f"Mike: {line}\n")

    print("— reply (player free text) —")
    try:
        said = input("You: ").strip() or "Why me?"
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    try:
        ans = api.ask.reply(
            "Mike. Wants the player to accept the mission.",
            said,
            [
                "Julius disappeared months ago",
                "Last lead is Hotel Pentfive",
                "Player is the only agent left",
            ],
        )["line"]
    except ArboritoError as err:
        ans = f"(reply skipped: {err})"
    print(f"Mike: {ans}\n")

    print("— fromCourse + check (gate from the loaded course) —")
    card = api.ask.fromCourse("greeting")
    if not card:
        print("This course has no greeting material; skip gate.")
        return 0
    print(f"Reception: {card.get('question')}")
    if card.get("example"):
        print(f"  (example: {card['example']})")
    try:
        answer = input("You: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    result = api.ask.check(answer, card)
    print("OK" if result.get("ok") else f"Try again — tip: {result.get('tip') or '…'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

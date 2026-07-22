"""Terminal interactive loop for `quiz` command."""

from __future__ import annotations

from typing import Any, Optional

from .client import Arborito
from .quiz_v2 import answers_match, lesson_answer_pool

# CLI chrome is always English; course content language is separate.
_UI = {
    "pick": "Pick (number, q=quit): ",
    "correct": "Correct!",
    "wrong": "Wrong —",
    "skip_order": "(Chips/steps modes: build your own UI with buildCard.)",
    "skip_enter": "Press Enter to continue, q=quit: ",
    "correct_label": "Correct:",
    "score": "Score:",
}


def _read_line(prompt: str) -> Optional[str]:
    try:
        raw = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if raw.lower() in ("q", "quit", "exit"):
        return None
    return raw


def run_quiz_loop(
    api: Arborito,
    rounds: int,
    mode_only: Optional[str],
    *,
    sess: Any = None,
) -> int:
    """Interactive quiz rounds over lesson @quiz blocks."""
    msg = _UI
    score = 0
    attempted = 0
    lessons = [api.lesson.at(i) for i in range(len(api.lesson.list()))]
    focus_id = ""
    if sess is not None:
        focus_id = str(getattr(sess, "focus", {}).get("lesson_id") or "")
    if focus_id:
        focused = [L for L in lessons if L and str(L.get("id") or "") == focus_id]
        rest = [L for L in lessons if L and str(L.get("id") or "") != focus_id]
        lessons = focused + rest
    for lesson in lessons:
        if attempted >= rounds:
            break
        if not lesson:
            continue
        challenges = list(api.challenge.fromLesson(lesson))
        sibling_pool = lesson_answer_pool(challenges)
        for challenge in challenges:
            if attempted >= rounds:
                break
            playable = api.challenge.modes.playable(challenge)
            if mode_only:
                if mode_only not in playable:
                    continue
                mode = mode_only
            else:
                if not playable:
                    continue
                mode = playable[0]
            card = api.challenge.modes.buildCard(
                challenge,
                mode,
                lesson_title=lesson.get("title") or "",
                lang=api.user.lang,
                distractor_pool=sibling_pool,
            )
            if not card:
                continue
            attempted += 1
            title = (lesson.get("title") or "?")[:50]
            print(f"\n--- {attempted}/{rounds} · {title} [{mode}] ---")
            print(f"Q: {card.get('question')}")
            options = list(card.get("options") or [])
            if mode in ("multiple", "recall", "cloze") and options:
                for i, opt in enumerate(options, 1):
                    print(f"  {i}) {opt}")
                raw = _read_line(msg["pick"])
                if raw is None:
                    break
                if raw.isdigit() and 1 <= int(raw) <= len(options):
                    ok = answers_match(options[int(raw) - 1], str(card.get("correct") or ""))
                    if ok:
                        score += 1
                        print(msg["correct"])
                    else:
                        print(f"{msg['wrong']} {card['correct']}")
            elif mode in ("chips", "steps"):
                chips = list(card.get("chips") or [])
                for i, chip in enumerate(chips, 1):
                    print(f"  {i}) {chip}")
                print(msg["skip_order"])
                raw = _read_line(msg["skip_enter"])
                if raw is None:
                    break
            else:
                print(f"({msg['correct_label']} {card.get('correct')})")
                raw = _read_line(msg["skip_enter"])
                if raw is None:
                    break
    print(f"\n{msg['score']} {score}/{attempted}")
    return 0

"""Lesson-grounded AI prompts for dynamic mode (`ask.lesson_action`)."""

from __future__ import annotations

import re
from typing import Any, Optional

LEARN_LANG_HINTS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\b(german|deutsch|alem[aá]n)\b", re.I), "de", "German"),
    (re.compile(r"\b(french|fran[cç]ais|franc[eé]s)\b", re.I), "fr", "French"),
    (re.compile(r"\b(english|ingl[eé]s)\b", re.I), "en", "English"),
    (re.compile(r"\b(spanish|espa[nñ]ol)\b", re.I), "es", "Spanish"),
    (re.compile(r"\b(italian|italiano)\b", re.I), "it", "Italian"),
    (re.compile(r"\b(portuguese|portugu[eê]s)\b", re.I), "pt", "Portuguese"),
    (re.compile(r"\b(japanese|japon[eé]s|nihongo)\b", re.I), "ja", "Japanese"),
    (re.compile(r"\b(chinese|mandarin|chino)\b", re.I), "zh", "Chinese"),
]


def lesson_context_for_ai(lesson: dict[str, Any]) -> str:
    parts = [f"Lesson: {lesson.get('title') or ''}"]
    body = str(lesson.get("text") or lesson.get("raw") or "")[:4000]
    if body:
        parts.append(body)
    from .quiz_v2 import get_challenges_from_lesson

    for i, ch in enumerate(get_challenges_from_lesson(lesson)[:8], 1):
        bits = []
        for key, label in (
            ("core_concept", "concept"),
            ("short_definition", "definition"),
            ("main_question", "question"),
            ("correct_answer", "answer"),
        ):
            val = str(ch.get(key) or "").strip()
            if val:
                bits.append(f"{label}: {val}")
        if bits:
            parts.append(f"Questionnaire {i}: {' | '.join(bits)}")
    return "\n".join(parts)


def static_facts_block_for_ai(lesson: dict[str, Any], lang: str = "ES") -> str:
    from .quiz_v2 import static_quiz_from_lesson

    items = static_quiz_from_lesson(lesson, 8, lang)
    if not items:
        return ""
    lines = ["Author facts (use these first when they apply):"]
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. [{it.get('topic', '')}] Q: {it.get('q', '')} | Correct: {it.get('correct', '')}")
    return "\n".join(lines)


def resolve_author_line(opts: Optional[dict[str, Any]]) -> str:
    opts = opts or {}
    return str(opts.get("authorLine") or opts.get("author_line") or opts.get("beat") or "").strip()


def learner_lang_name(profile: Optional[dict[str, Any]], fallback_lang: str = "EN") -> str:
    profile = profile or {}
    pl = str(profile.get("playerLang") or fallback_lang or "EN").lower()
    if pl.startswith("es"):
        return "Spanish"
    if pl.startswith("en"):
        return "English"
    return "Spanish" if str(fallback_lang).upper() == "ES" else "English"


def infer_learn_language_from_lessons(
    lessons: list[dict[str, Any]], curriculum_titles: Optional[list[str]] = None
) -> dict[str, str]:
    blob = ""
    for lesson in lessons or []:
        blob += f" {lesson.get('title') or ''} {str(lesson.get('text') or '')[:400]}"
    for title in curriculum_titles or []:
        blob += f" {title or ''}"
    for pattern, code, label in LEARN_LANG_HINTS:
        if pattern.search(blob):
            return {"code": code, "label": label}
    return {"code": "en", "label": "English"}


def profile_lang_block(profile: Optional[dict[str, Any]]) -> str:
    profile = profile or {}
    lines = [f"Player UI language: {profile.get('playerLang') or 'EN'}"]
    learn = profile.get("learnLangLabel") or profile.get("learnLang") or ""
    if learn:
        lines.append(f"Branch study / subject language: {learn}")
    if profile.get("module"):
        lines.append(f"Module: {profile.get('module')}")
    if profile.get("playerName"):
        lines.append(f"Player name: {profile.get('playerName')}")
    return "\n".join(lines)


def branch_context_for_ai(
    client: Any,
    anchor_lesson: Optional[dict[str, Any]],
    profile: Optional[dict[str, Any]],
) -> str:
    from .quiz_v2 import static_quiz_from_lesson

    profile = dict(profile or {})
    playlist = list(getattr(client, "_playlist", None) or [])
    lines = ["=== Active branch playlist ==="]
    for i, lesson in enumerate(playlist[:24], 1):
        lines.append(f"{i}. {lesson.get('title') or lesson.get('id') or ''}")
    lines.append("")
    lines.append(profile_lang_block(profile))
    sample_lessons = playlist[:10]
    if not profile.get("learnLangLabel"):
        inferred = infer_learn_language_from_lessons(
            sample_lessons,
            [str(x.get("title") or "") for x in playlist],
        )
        if inferred.get("label"):
            lines.append(f"Inferred branch subject: {inferred['label']}")
            profile.setdefault("learnLang", inferred["code"])
            profile.setdefault("learnLangLabel", inferred["label"])
    fact_lines: list[str] = []
    lang = str(getattr(getattr(client, "user", None), "lang", None) or "EN")
    for lesson in sample_lessons:
        if len(fact_lines) >= 14:
            break
        for item in static_quiz_from_lesson(lesson, 2, lang) or []:
            if len(fact_lines) >= 14:
                break
            fact_lines.append(
                f"- [{item.get('topic') or lesson.get('title')}] "
                f"{item.get('q')} → {item.get('correct')}"
            )
    if fact_lines:
        lines.extend(
            [
                "",
                "Branch questionnaire samples (adapt narrative and challenges to these facts and vocabulary):",
                *fact_lines,
            ]
        )
    if anchor_lesson:
        lines.extend(["", "=== Current scene lesson ===", lesson_context_for_ai(anchor_lesson)])
    return "\n".join(lines)


def build_dynamic_action_prompt(
    client: Any,
    lesson: dict[str, Any],
    input_text: str,
    opts: Optional[dict[str, Any]] = None,
) -> str:
    opts = opts or {}
    profile = dict(opts.get("profile") or {})
    author_line = resolve_author_line(opts)
    text = str(input_text or "").strip()
    intent = opts.get("intent")
    if not intent:
        if author_line:
            intent = "narrative_adapt" if (not text or text == author_line) else "narrative_reply"
        else:
            intent = "tutor"
    branch_block = branch_context_for_ai(client, lesson, profile)
    persona = str(opts.get("persona") or opts.get("role") or "")
    if not persona:
        persona = getattr(client, "_ai_persona", "") or "an interactive study tutor grounded in the lesson"
    lang = str(getattr(getattr(client, "user", None), "lang", None) or "EN")
    lang_name = learner_lang_name(profile, lang)
    facts = static_facts_block_for_ai(lesson, lang)
    facts_section = f"{facts}\n\n" if facts else ""
    learn_note = (
        f"Branch teaches {profile.get('learnLangLabel')}. Use its vocabulary in examples and challenges.\n"
        if profile.get("learnLangLabel")
        else ""
    )
    if intent == "narrative_adapt":
        return (
            f"{branch_block}\n\n{facts_section}"
            f"Persona / stay in character: {persona}\n"
            f"Player-facing language: {lang_name}\n"
            f"{learn_note}"
            "Task: rewrite the AUTHOR LINE for this branch. Keep the same story moment and speaker intent, "
            "but use vocabulary, examples, and practice hooks from the playlist and questionnaires above.\n"
            "If the branch teaches a language (e.g. German vs English), reflect that in the line. "
            "Do not contradict author facts.\n"
            f"AUTHOR LINE:\n{author_line or text}\n\n"
            "Reply ONLY with JSON:\n"
            '{"output":"text shown to the player","success":true,"matches_lesson":true}\n'
            "Keep output under 12 lines. Plain text in output, no markdown."
        )
    if intent == "narrative_reply":
        author_ctx = f"Author line for context:\n{author_line}\n\n" if author_line else ""
        return (
            f"{branch_block}\n\n{facts_section}"
            f"Persona / stay in character: {persona}\n"
            f"Player-facing language: {lang_name}\n"
            f"{learn_note}"
            f"{author_ctx}"
            "Task: reply in character to what the player said. Ground the answer in this branch (playlist + questionnaires).\n"
            f"Player said: {text}\n\n"
            "Reply ONLY with JSON:\n"
            '{"output":"in-character reply","success":true,"matches_lesson":true}\n'
            "Set matches_lesson false only if clearly unrelated. Keep output under 12 lines."
        )
    student_line = (
        f"The student typed: {text}\n\n"
        if text
        else "The student sent no message — give a short helpful nudge from author questionnaires.\n\n"
    )
    return (
        f"{branch_block}\n\n{facts_section}"
        f"Persona / scene (stay in character): {persona}\n"
        f"Respond in {lang_name} for learner-facing text.\n"
        f"{learn_note}"
        "Rules:\n"
        "- Use author questionnaire facts FIRST when they answer the player.\n"
        "- If questionnaires are incomplete, build from lesson text + branch playlist — do not invent unrelated lore.\n"
        "- Adapt examples to the branch study language.\n"
        "- output field is plain student-facing text only — never JSON or markdown fences.\n"
        f"{student_line}"
        "Reply ONLY with JSON:\n"
        '{"output":"plain multiline text","success":true,"matches_lesson":true}\n'
        "Keep output under 14 lines."
    )


def lesson_action_prompt(
    lesson: dict[str, Any],
    input_text: str,
    lang: str,
    persona: str = "",
    *,
    client: Any = None,
    opts: Optional[dict[str, Any]] = None,
) -> str:
    opts = dict(opts or {})
    if persona and not opts.get("persona"):
        opts["persona"] = persona
    if client is not None:
        return build_dynamic_action_prompt(client, lesson, input_text, opts)
    lang_name = "Spanish" if lang.upper() == "ES" else "English"
    if not persona:
        persona = "an interactive study tutor grounded in the lesson"
    context = lesson_context_for_ai(lesson)
    facts = static_facts_block_for_ai(lesson, lang)
    facts_section = f"{facts}\n\n" if facts else ""
    author_line = resolve_author_line(opts)
    if author_line and (not input_text or str(input_text).strip() == author_line):
        return (
            f"{context}\n\n{facts_section}"
            f"Persona / stay in character: {persona}\n"
            f"Player-facing language: {lang_name}\n"
            "Task: rewrite the AUTHOR LINE for this branch. Keep story intent; adapt vocabulary to the lesson.\n"
            f"AUTHOR LINE:\n{author_line}\n\n"
            "Reply ONLY with JSON:\n"
            '{"output":"text shown to the player","success":true,"matches_lesson":true}'
        )
    return (
        f"{context}\n\n{facts_section}"
        f"Persona / scene (stay in character): {persona}\n"
        f"Respond in {lang_name} for learner-facing text.\n"
        "Rules:\n"
        "- Prefer author facts and questionnaires when they answer the student.\n"
        "- Otherwise ground replies in the lesson text above.\n"
        "- Do not contradict the lesson or invent unrelated lore.\n"
        f"The student typed: {input_text}\n\n"
        "Reply ONLY with JSON:\n"
        '{"output":"plain multiline text to show the student","success":true,"matches_lesson":true}\n'
        "Set matches_lesson to false only if the input is clearly unrelated to this lesson.\n"
        "Keep output under 14 lines. No markdown fences."
    )


def grade_quiz_answer_prompt(
    lesson: dict[str, Any],
    item: dict[str, Any],
    player_text: str,
    lang: str,
) -> str:
    """Grounded grading prompt for `quiz.grade_answer`."""
    lang_name = "Spanish" if lang.upper() == "ES" else "English"
    question = str(item.get("q") or item.get("complaint") or "").strip()
    expected = str(item.get("correct") or "").strip()
    topic = str(item.get("topic") or "").strip()
    context = lesson_context_for_ai(lesson)
    facts = static_facts_block_for_ai(lesson, lang)
    facts_section = f"{facts}\n\n" if facts else ""
    topic_line = f'Topic: "{topic}".\n' if topic else ""
    return (
        f"{context}\n\n{facts_section}"
        f"Grade this quiz answer in {lang_name}.\n"
        f"{topic_line}"
        f'Question: "{question}"\n'
        f'Expected answer: "{expected}"\n'
        f'Student wrote: {player_text!r}\n\n'
        "Prefer author questionnaire facts when they apply. "
        "Accept synonyms and minor spelling errors grounded in the lesson.\n"
        'Output JSON only: {"correct": true|false}'
    )

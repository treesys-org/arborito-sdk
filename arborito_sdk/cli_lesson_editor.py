"""Rich terminal lesson editor (Textual TUI) — structured blocks, not raw @quiz fences."""

from __future__ import annotations

from typing import Any, Optional

from .client import Arborito
from .lesson_document import (
    FencedBlock,
    InfoBlock,
    LessonDocument,
    ProseBlock,
    QuizBlock,
    block_list_labels,
    parse_lesson_document,
)
from .lesson_write import save_lesson_raw
from .quiz_v2 import new_challenge


def _tui_available() -> bool:
    try:
        import textual  # noqa: F401

        return True
    except ImportError:
        return False


def run_lesson_editor_tui(api: Arborito, lesson_id: str, raw_markdown: str) -> None:
    if not _tui_available():
        raise ImportError("textual")
    from .cli_lesson_editor_app import LessonEditorApp

    doc = parse_lesson_document(raw_markdown)
    app = LessonEditorApp(api=api, lesson_id=lesson_id, document=doc)
    app.run()


def run_lesson_editor_fallback(api: Arborito, lesson_id: str, raw_markdown: str) -> None:
    """Minimal block editor without Textual — Click forms for quiz, $EDITOR for prose."""
    import os
    import subprocess
    import tempfile

    import click

    from .lesson_write import save_lesson_raw

    doc = parse_lesson_document(raw_markdown)
    labels = block_list_labels(doc)
    click.echo(
        '✏️  Structured editor (basic mode: install `pip install "arborito-sdk[tui]"` for the full UI)\n'
    )
    for i, label in enumerate(labels, 1):
        click.echo(f"  {i}. {label}")
    click.echo("\nCommands: number = edit block | q = new quiz | s = save | x = exit")

    while True:
        choice = click.prompt("Block", default="", show_default=False).strip().lower()
        if choice in ("x", "exit", "quit", ""):
            break
        if choice == "s":
            new_raw = doc.to_markdown()
            entry = save_lesson_raw(api, lesson_id, new_raw)
            click.echo(f"✅ Saved {entry}")
            break
        if choice == "q":
            doc.blocks.append(QuizBlock(challenge=new_challenge()))
            click.echo("📋 Empty quiz appended.")
            continue
        if not choice.isdigit():
            click.echo("Unrecognized input.")
            continue
        idx = int(choice) - 1
        offset = 1 if doc.info and doc.info.fields else 0
        block_idx = idx - offset
        if block_idx < 0 and doc.info:
            _edit_info_click(doc.info)
            continue
        if block_idx < 0 or block_idx >= len(doc.blocks):
            click.echo("Index out of range.")
            continue
        block = doc.blocks[block_idx]
        if isinstance(block, ProseBlock):
            import shlex

            ed = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
            cmd = shlex.split(ed) if str(ed).strip() else ["nano"]
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", prefix="arborito-prose-", encoding="utf-8", delete=False
            ) as tf:
                tf.write(block.text or "")
                tmp = tf.name
            try:
                subprocess.run([*cmd, tmp], check=False)
                block.text = open(tmp, encoding="utf-8").read().rstrip("\n")
            finally:
                os.unlink(tmp)
        elif isinstance(block, QuizBlock):
            _edit_quiz_click(block)
        elif isinstance(block, FencedBlock):
            _edit_fenced_click(block)


def _edit_info_click(info: InfoBlock) -> None:
    import click

    info.fields["title"] = click.prompt("title", default=str(info.fields.get("title") or ""))
    info.fields["description"] = click.prompt(
        "description", default=str(info.fields.get("description") or ""), show_default=False
    )


def _edit_quiz_click(block: QuizBlock) -> None:
    import click

    from .quiz_v2 import parse_inline_cloze

    c = block.challenge
    c["core_concept"] = click.prompt("Concept", default=str(c.get("core_concept") or ""))
    definition = click.prompt("Definition", default=str(c.get("short_definition") or ""))
    text, idxs = parse_inline_cloze(definition)
    c["short_definition"] = text
    c["cloze_indices"] = idxs
    c["main_question"] = click.prompt("Question", default=str(c.get("main_question") or ""))
    c["correct_answer"] = click.prompt("Answer", default=str(c.get("correct_answer") or ""))
    traps_raw = click.prompt(
        "Traps (one per line, end with an empty line)",
        default="\n".join(c.get("traps") or []),
        show_default=False,
    )
    c["traps"] = [ln.strip() for ln in traps_raw.splitlines() if ln.strip()]


def _edit_fenced_click(block: FencedBlock) -> None:
    import click

    for key in list(block.fields.keys()) or ["title"]:
        block.fields[key] = click.prompt(key, default=str(block.fields.get(key) or ""))

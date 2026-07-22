"""Parse and serialize Arborito lesson markdown as structured blocks for CLI editing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from .quiz_v2 import (
    _INFO_CLOSE_RE,
    _INFO_OPEN_RE,
    _parse_info_line,
    parse_quiz_block,
    serialize_quiz_block,
)

_BLOCK_OPEN = re.compile(r"^@(\w+)\s*$", re.IGNORECASE)
_BLOCK_CLOSE = re.compile(r"^@/(\w+)\s*$", re.IGNORECASE)
_FENCED_BODY_TAGS = frozenset(
    {"section", "subsection", "image", "video", "audio", "game", "math", "quiz"}
)


@dataclass
class InfoBlock:
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProseBlock:
    text: str = ""


@dataclass
class QuizBlock:
    challenge: dict[str, Any] = field(default_factory=dict)


@dataclass
class FencedBlock:
    tag: str
    fields: dict[str, str] = field(default_factory=dict)


BlockKind = Literal["info", "prose", "quiz", "fenced"]


@dataclass
class LessonDocument:
    info: Optional[InfoBlock] = None
    blocks: list[ProseBlock | QuizBlock | FencedBlock] = field(default_factory=list)

    def to_markdown(self) -> str:
        parts: list[str] = []
        if self.info and self.info.fields:
            lines = ["@info"]
            for key in ("title", "icon", "description", "discussion", "tags", "exam"):
                val = self.info.fields.get(key)
                if val is None or val == "" or val == []:
                    continue
                if key == "tags" and isinstance(val, list):
                    lines.append(f"tags: {', '.join(str(t) for t in val if str(t).strip())}")
                elif key == "exam" and val:
                    lines.append("exam: yes")
                else:
                    lines.append(f"{key}: {val}")
            lines.append("@/info")
            parts.append("\n".join(lines))

        body_parts: list[str] = []
        for block in self.blocks:
            if isinstance(block, ProseBlock):
                text = (block.text or "").strip("\n")
                if text.strip():
                    body_parts.append(text)
            elif isinstance(block, QuizBlock):
                body_parts.append(serialize_quiz_block(block.challenge))
            elif isinstance(block, FencedBlock):
                body_parts.append(_serialize_fenced(block.tag, block.fields))
        if body_parts:
            parts.append("\n\n".join(body_parts))

        out = "\n\n".join(p for p in parts if p.strip())
        return (out.rstrip() + "\n") if out.strip() else ""


def _serialize_fenced(tag: str, fields: dict[str, str]) -> str:
    lines = [f"@{tag}"]
    for key, value in fields.items():
        if value is None or str(value).strip() == "":
            continue
        lines.append(f"{key}: {str(value).strip()}")
    lines.append(f"@/{tag}")
    return "\n".join(lines)


def _read_fenced_block(lines: list[str], start: int) -> tuple[str, dict[str, str], int]:
    m = _BLOCK_OPEN.match(lines[start].strip())
    if not m:
        raise ValueError("not a fenced block")
    tag = m.group(1).lower()
    body: list[str] = []
    i = start + 1
    while i < len(lines):
        cm = _BLOCK_CLOSE.match(lines[i].strip())
        if cm and cm.group(1).lower() == tag:
            break
        body.append(lines[i])
        i += 1
    fields: dict[str, str] = {}
    for line in body:
        trimmed = line.strip()
        if not trimmed or ":" not in trimmed:
            continue
        key, _, val = trimmed.partition(":")
        fields[key.strip().lower()] = val.strip()
    return tag, fields, i


def parse_lesson_document(raw: str) -> LessonDocument:
    """Split lesson markdown into info + ordered body blocks."""
    lines = (raw or "").splitlines()
    doc = LessonDocument()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1

    if i < len(lines) and _INFO_OPEN_RE.match(lines[i].strip()):
        info = InfoBlock()
        i += 1
        while i < len(lines) and not _INFO_CLOSE_RE.match(lines[i].strip()):
            pair = _parse_info_line(lines[i])
            if pair is not None:
                info.fields[pair[0]] = pair[1]
            i += 1
        if i < len(lines):
            i += 1
        if info.fields:
            doc.info = info

    prose_buf: list[str] = []

    def flush_prose() -> None:
        if not prose_buf:
            return
        text = "\n".join(prose_buf)
        if text.strip():
            doc.blocks.append(ProseBlock(text=text.rstrip("\n")))
        prose_buf.clear()

    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            prose_buf.append(lines[i])
            i += 1
            continue

        m = _BLOCK_OPEN.match(stripped)
        if m:
            tag = m.group(1).lower()
            if tag == "quiz":
                flush_prose()
                close = -1
                for j in range(i + 1, len(lines)):
                    cm = _BLOCK_CLOSE.match(lines[j].strip())
                    if cm and cm.group(1).lower() == "quiz":
                        close = j
                        break
                    om = _BLOCK_OPEN.match(lines[j].strip())
                    if om and om.group(1).lower() == "quiz":
                        break
                if close >= 0:
                    challenge = parse_quiz_block(lines[i + 1 : close])
                    doc.blocks.append(QuizBlock(challenge=challenge))
                    i = close + 1
                    continue
            if tag in _FENCED_BODY_TAGS - {"quiz"}:
                flush_prose()
                ftag, fields, close_i = _read_fenced_block(lines, i)
                doc.blocks.append(FencedBlock(tag=ftag, fields=fields))
                i = close_i + 1
                continue

        prose_buf.append(lines[i])
        i += 1

    flush_prose()
    return doc


def format_lesson_for_terminal(raw: str, *, title: str = "") -> str:
    """Human-readable terminal view (no raw @quiz fences)."""
    doc = parse_lesson_document(raw)
    out: list[str] = []
    if title:
        out.append(f"# {title}")
        out.append("")
    if doc.info and doc.info.fields:
        out.append("┌─ @info ─────────────────────────────────")
        for key, val in doc.info.fields.items():
            if key == "tags" and isinstance(val, list):
                out.append(f"│ tags: {', '.join(str(t) for t in val)}")
            else:
                out.append(f"│ {key}: {val}")
        out.append("└────────────────────────────────────────")
        out.append("")

    for idx, block in enumerate(doc.blocks, 1):
        if isinstance(block, ProseBlock):
            out.append("── Text ──")
            preview = (block.text or "").strip()
            if preview:
                out.extend(preview.splitlines())
            else:
                out.append("(empty)")
            out.append("")
        elif isinstance(block, QuizBlock):
            c = block.challenge
            items = c.get("items") or []
            if items:
                out.append(f"── Quiz ({len(items)} items) ──")
                for n, item in enumerate(items, 1):
                    out.extend(_format_quiz_fields(item, prefix=f"  [{n}] "))
            else:
                out.append("── Quiz ──")
                out.extend(_format_quiz_fields(c))
            out.append("")
        elif isinstance(block, FencedBlock):
            label = block.tag.upper()
            title_val = block.fields.get("title") or block.fields.get("url") or block.fields.get("label") or ""
            out.append(f"── @{block.tag} ── {title_val}".rstrip())
            for key, val in block.fields.items():
                if key in ("title", "url", "label") and title_val:
                    continue
                out.append(f"  {key}: {val}")
            out.append("")

    return "\n".join(out).rstrip()


def _format_quiz_fields(c: dict[str, Any], *, prefix: str = "  ") -> list[str]:
    lines: list[str] = []
    concept = str(c.get("core_concept") or "").strip()
    question = str(c.get("main_question") or "").strip()
    answer = str(c.get("correct_answer") or "").strip()
    definition = str(c.get("short_definition") or "").strip()
    if concept:
        lines.append(f"{prefix}Concept: {concept}")
    if definition:
        lines.append(f"{prefix}Definition: {definition}")
    if question:
        lines.append(f"{prefix}Question: {question}")
    if answer:
        lines.append(f"{prefix}Answer: {answer}")
    traps = c.get("traps") or []
    if traps:
        lines.append(f"{prefix}Traps: {', '.join(str(t) for t in traps)}")
    steps = c.get("steps") or []
    if steps:
        lines.append(f"{prefix}Steps:")
        for s in steps:
            lines.append(f"{prefix}  • {s}")
    modes = c.get("modes") or []
    if modes:
        lines.append(f"{prefix}Modes: {', '.join(str(m) for m in modes)}")
    return lines


def block_list_labels(doc: LessonDocument) -> list[str]:
    """Short labels for TUI list rows."""
    labels: list[str] = []
    if doc.info and doc.info.fields:
        title = doc.info.fields.get("title") or "metadata"
        labels.append(f"ℹ️  Info · {title}")
    for block in doc.blocks:
        if isinstance(block, ProseBlock):
            first = next((ln.strip() for ln in (block.text or "").splitlines() if ln.strip()), "")
            preview = first[:56] + ("…" if len(first) > 56 else "")
            labels.append(f"📝 Text · {preview or '(empty)'}")
        elif isinstance(block, QuizBlock):
            c = block.challenge
            concept = str(c.get("core_concept") or "Quiz").strip()
            q = str(c.get("main_question") or "").strip()
            tail = f" — {q[:40]}…" if len(q) > 40 else (f" — {q}" if q else "")
            labels.append(f"📋 Quiz · {concept}{tail}")
        elif isinstance(block, FencedBlock):
            icon = {"section": "§", "subsection": "§§", "game": "🎮"}.get(block.tag, "▣")
            val = block.fields.get("title") or block.fields.get("url") or block.fields.get("label") or block.tag
            labels.append(f"{icon} @{block.tag} · {val}")
    return labels

"""Extract structured content from lessons (blocks, frontmatter, code fences)."""

from __future__ import annotations

import re
from typing import Any, Optional

from .quiz_v2 import get_challenges_from_lesson, parse_all_challenges_from_content

_BLOCK_OPEN = re.compile(r"^@(\w+)\s*$")
_BLOCK_CLOSE = re.compile(r"^@/(\w+)\s*$")
_FENCE_RE = re.compile(r"```(?:bash|sh|shell|zsh|console|text)?\n([\s\S]*?)```", re.I)
_FM_DELIM = re.compile(r"^---\s*$")
_TRUTHY = frozenset({"yes", "true", "on", "1"})
_NARRATIVE_TAGS = frozenset({"starship", "narrative", "story", "visual-novel"})


_FENCED_TAGS = ("section", "subsection", "image", "video", "audio", "game", "math", "quiz", "info")


def body(lesson: dict[str, Any]) -> str:
    return str(lesson.get("text") or "")


def raw(lesson: dict[str, Any]) -> str:
    return str(lesson.get("raw") or lesson.get("text") or "")


def challenges(lesson: dict[str, Any]) -> list[dict[str, Any]]:
    return get_challenges_from_lesson(lesson)


def lesson_plain_text(lesson_or_raw: Any) -> str:
    """Prose for NPC / HUD dialogue — same role as browser ``lesson.plainText``.

    Strips fenced author blocks (``@section``, ``@quiz``, …), markdown noise, and
    collapses whitespace. Prefer this over ``lesson["text"]`` when rendering dialogue.
    """
    if lesson_or_raw is None:
        return ""
    if isinstance(lesson_or_raw, dict):
        source = str(lesson_or_raw.get("raw") or lesson_or_raw.get("text") or "")
    else:
        source = str(lesson_or_raw or "")
    text = source
    for tag in _FENCED_TAGS:
        text = re.sub(
            rf"^@{tag}\s*\n.*?^@/{tag}\s*$\n?",
            "\n",
            text,
            flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
        )
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"^\s*#+\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*>\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"\{\{(?:lg|md|sm)\}\}([\s\S]*?)\{\{/(?:lg|md|sm)\}\}", r"\1", text)
    text = re.sub(r"@[A-Za-z_][\w-]*", " ", text)
    text = re.sub(r"@/[A-Za-z_][\w-]*", " ", text)
    text = re.sub(r"^[a-z][a-z0-9_-]*:\s*.+$", " ", text, flags=re.IGNORECASE | re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip()


def _parse_kv_body(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        trimmed = line.strip()
        if not trimmed or ":" not in trimmed:
            continue
        key, _, val = trimmed.partition(":")
        fields[key.strip().lower()] = val.strip()
    return fields


def blocks(lesson: dict[str, Any], tag: str) -> list[str]:
    """Return inner bodies of @tag … @/tag blocks."""
    tag = str(tag or "").strip().lower()
    if not tag:
        return []
    lines = raw(lesson).splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        m = _BLOCK_OPEN.match(lines[i].strip())
        if m and m.group(1).lower() == tag:
            i += 1
            chunk: list[str] = []
            while i < len(lines):
                cm = _BLOCK_CLOSE.match(lines[i].strip())
                if cm and cm.group(1).lower() == tag:
                    break
                chunk.append(lines[i])
                i += 1
            out.append("\n".join(chunk).strip())
        i += 1
    return out


def frontmatter(lesson: dict[str, Any]) -> dict[str, Any]:
    """YAML frontmatter at top of raw lesson (story scenes, NPCs)."""
    text = raw(lesson)
    lines = text.splitlines()
    if not lines or not _FM_DELIM.match(lines[0].strip()):
        return {}
    i = 1
    fm_lines: list[str] = []
    while i < len(lines):
        if _FM_DELIM.match(lines[i].strip()):
            break
        fm_lines.append(lines[i])
        i += 1
    if not fm_lines:
        return {}
    try:
        import yaml  # type: ignore
    except ImportError:
        return _parse_simple_yaml(fm_lines)
    try:
        parsed = yaml.safe_load("\n".join(fm_lines))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return _parse_simple_yaml(fm_lines)


def _parse_simple_yaml(lines: list[str]) -> dict[str, Any]:
    """Minimal key: value parser when PyYAML is absent."""
    out: dict[str, Any] = {}
    for line in lines:
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            out[key] = val
    return out


def code_fences(lesson: dict[str, Any]) -> list[dict[str, str]]:
    """Command/output pairs from shell code fences."""
    return code_replays_from_lesson(lesson)


def code_replays_from_lesson(lesson: dict[str, Any]) -> list[dict[str, str]]:
    raw_text = raw(lesson)
    seen: dict[str, dict[str, str]] = {}
    for m in _FENCE_RE.finditer(raw_text):
        lines = m.group(1).split("\n")
        for li, line in enumerate(lines):
            trimmed = line.strip()
            if not trimmed or trimmed.startswith("#"):
                continue
            no_comment = trimmed.split("#", 1)[0].strip()
            if not no_comment:
                continue
            cmd = re.sub(r"^\$\s*", "", no_comment)
            if not cmd or len(cmd) > 160:
                continue
            key = " ".join(cmd.split()).lower()
            if key in seen:
                continue
            out_lines: list[str] = []
            for lj in range(li + 1, len(lines)):
                nxt = lines[lj].strip()
                if not nxt:
                    break
                if nxt.startswith("#"):
                    continue
                maybe = nxt.split("#", 1)[0].strip().lstrip("$").strip()
                if maybe and re.match(r"^\S+\s", nxt):
                    break
                out_lines.append(lines[lj])
            output = "\n".join(out_lines).strip()
            if output:
                seen[key] = {"cmd": cmd, "output": output}
    return list(seen.values())


def find_code_replay(
    input_text: str,
    replays: Optional[list[dict[str, str]]] = None,
) -> Optional[dict[str, Any]]:
    """Match typed shell input to a code-fence replay (Arcade ``quiz.findCodeReplay``)."""
    from .quiz_v2 import _answer_levenshtein

    key = str(input_text or "").strip()
    key = re.sub(r"^[#$>]+\s*", "", key)
    key = re.sub(r"^\$\s*", "", key)
    key = key.rstrip(";").strip()
    key = re.sub(r"\s+", " ", key).lower()
    if not key:
        return None
    best: Optional[dict[str, str]] = None
    best_score = 0.0
    for rep in replays or []:
        exp = re.sub(r"\s+", " ", str(rep.get("cmd") or "").strip()).lower()
        if not exp:
            continue
        if key == exp:
            return {"replay": rep, "fuzzy": False}
        max_len = max(len(key), len(exp), 1)
        score = 1 - _answer_levenshtein(key, exp) / max_len
        if key.startswith(exp + " "):
            score = max(score, 0.88)
        if score > best_score:
            best_score = score
            best = rep
    if best is not None and best_score >= 0.78:
        return {"replay": best, "fuzzy": best_score < 0.99}
    return None


def info_meta(lesson: dict[str, Any]) -> dict[str, Any]:
    """Parse optional @info block (tags, title, icon, …)."""
    bodies = blocks(lesson, "info")
    if not bodies:
        return {"tags": []}
    fields = _parse_kv_body(bodies[0])
    tags_raw = str(fields.get("tags") or "")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    out = dict(fields)
    out["tags"] = tags
    return out


def game_blocks(lesson: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse @game blocks (Arcade cartridge links — same as Arborito lesson format)."""
    out: list[dict[str, Any]] = []
    for body in blocks(lesson, "game"):
        fields = _parse_kv_body(body)
        topics_raw = str(fields.get("topics") or "")
        topics = [t.strip() for t in topics_raw.split(",") if t.strip()]
        opt_raw = str(fields.get("optional") or "").lower()
        optional = True if opt_raw == "" else opt_raw in _TRUTHY
        out.append(
            {
                "url": str(fields.get("url") or "").strip(),
                "label": str(fields.get("label") or "").strip(),
                "optional": optional,
                "topics": topics,
            }
        )
    return out


def lesson_is_narrative_scene(lesson: dict[str, Any]) -> bool:
    """True when lesson uses YAML frontmatter narrative scenes."""
    fm = frontmatter(lesson)
    if fm.get("scene_id") or fm.get("progress_details") or fm.get("initial_narration"):
        return True
    tags = {t.casefold() for t in info_meta(lesson).get("tags") or []}
    return bool(tags & _NARRATIVE_TAGS)


def module_is_narrative(api: Any, module: dict[str, Any]) -> bool:
    """Detect narrative modules (frontmatter scenes or narrative-tagged lessons)."""
    from .tree_nav import module_playlist

    hits = 0
    for node in module_playlist(module):
        lesson = api.lesson.by_id(str(node.get("id") or ""))
        if lesson and lesson_is_narrative_scene(lesson):
            hits += 1
    return hits > 0


def npc_profile(lesson: dict[str, Any]) -> dict[str, Any]:
    fm = frontmatter(lesson)
    body_text = body(lesson).strip()
    return {
        "id": fm.get("id") or lesson.get("id"),
        "name": fm.get("name") or lesson.get("title"),
        "image": fm.get("image") or "",
        "system_prompt": body_text,
        "frontmatter": fm,
    }


def progress_details(lesson: dict[str, Any]) -> list[dict[str, Any]]:
    fm = frontmatter(lesson)
    pd = fm.get("progress_details")
    return pd if isinstance(pd, list) else []


def parse_challenges_from_raw(text: str) -> list[dict[str, Any]]:
    return parse_all_challenges_from_content(text)

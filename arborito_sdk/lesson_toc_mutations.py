"""Construct-mode TOC outline math (parity with Arborito ``lesson-toc-mutations.js``).

Canonical row is always an ``@section`` fence with ``index:`` + ``title:``.
Nest depth = segments of ``index``. Moves and renumber read and write that field
directly — ``#path} Title`` is only accepted on ingest (old files) and converted.

Cave-man rules:
- Content titles use normal ``##`` / ``###`` without a path (not TOC once the body
  has path markers). Docs without path ids yet: every ATX heading is TOC until
  prepare assigns indexed fences.
- Floor is plain ``##`` (never leave stranded ``# Title`` vs ``##``).
- ``+`` always nests one level deeper (child); at max path depth stays sibling.
- Path ids in ``index:`` are rewritten atomically after every prepare/mutation.
- Move arrows ↔ actions must agree; nested rows (L>2) can always outdent.
- Indent blocked only when any heading in the subtree would exceed max path depth.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Optional

SYNTHETIC_INTRO_ID = "__arborito_synthetic_intro__"
OUTLINE_MAX_PATH_DEPTH = 8
OUTLINE_MAX_LEVEL = OUTLINE_MAX_PATH_DEPTH + 1

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BLANK_HEADING_RE = re.compile(r"^(#{1,6})\s*$")
_SYLLABUS_PATH_LINE = re.compile(r"^#(\d+(?:\.\d+)*)\}\s+(.*)$")
_SECTION_OPEN = re.compile(r"^@section\s*$", re.I)
_SUBSECTION_OPEN = re.compile(r"^@subsection\s*$", re.I)
_FENCE_CLOSE = re.compile(r"^@/(section|subsection)\s*$", re.I)
_QUIZ_OPEN = re.compile(r"^@quiz\b", re.I)
_QUIZ_CLOSE = re.compile(r"^@/quiz\b", re.I)
_BODY_HAS_SYLLABUS = re.compile(r"(?:^|\n)#\d+(?:\.\d+)*\}")
_EMOJI_PREFIX = re.compile(
    r"^([\U0001F300-\U0001FAFF\u2600-\u26FF\u2700-\u27BF\uFE00-\uFE0F\u200D]+)\s+",
    re.UNICODE,
)


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return s or "section"


def parse_syllabus_path_line(line: Optional[str]) -> Optional[dict[str, str]]:
    m = _SYLLABUS_PATH_LINE.match(str(line or "").strip())
    if not m:
        return None
    return {"path": (m.group(1) or "").strip(), "title": (m.group(2) or "").rstrip()}


def format_syllabus_path_line(path_id: str, title_text: str) -> str:
    pid = (path_id or "").strip()
    title = (title_text or "").strip()
    if not pid:
        return f"# {title}" if title else "#"
    return f"#{pid}}} {title}".rstrip()


def strip_outline_path_id(text: Optional[str]) -> str:
    syl = parse_syllabus_path_line(text)
    if syl:
        return syl["title"]
    return str(text or "").strip()


def outline_path_id_from_text(text: Optional[str]) -> Optional[str]:
    syl = parse_syllabus_path_line(text)
    if syl and is_outline_path_id(syl["path"]):
        return syl["path"]
    return None


def is_outline_path_id(oid: Any) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)*", str(oid or "").strip()))


def body_has_outline_path_ids(body: Optional[str]) -> bool:
    s = str(body or "")
    if _BODY_HAS_SYLLABUS.search(s):
        return True
    return bool(re.search(r"(?m)^index:\s*\d+(?:\.\d+)*\s*$", s))


def is_atx_heading_line(trimmed: Optional[str]) -> bool:
    t = str(trimmed or "")
    if not t:
        return False
    if parse_syllabus_path_line(t):
        return True
    return bool(_HEADING_RE.match(t))


def is_outline_heading_line(trimmed: Optional[str], body_text: str = "") -> bool:
    """Syllabus row vs in-lesson content title (parity with Arborito)."""
    t = str(trimmed or "").strip()
    if not t:
        return False
    if _QUIZ_OPEN.match(t) or _QUIZ_CLOSE.match(t):
        return False
    if _SECTION_OPEN.match(t) or _SUBSECTION_OPEN.match(t):
        return True
    if parse_syllabus_path_line(t):
        return True
    if not is_atx_heading_line(t):
        return False
    path = outline_path_id_from_text(t)
    if path and is_outline_path_id(path):
        return True
    if not body_has_outline_path_ids(body_text):
        return True
    return False


def outline_level_from_path_id(path_id: Any) -> int:
    """Path segment count → construct outline level (UI indent = level − 2)."""
    if not is_outline_path_id(path_id):
        return 2
    depth = len(str(path_id).strip().split("."))
    return min(OUTLINE_MAX_LEVEL, max(2, depth + 1))


def path_depth_from_outline_level(level: Any) -> int:
    try:
        L = int(level)
    except (TypeError, ValueError):
        return 1
    return min(OUTLINE_MAX_PATH_DEPTH, max(1, L - 1))


def _clamp_path_depth(depth: Any) -> int:
    try:
        d = int(depth)
    except (TypeError, ValueError):
        d = 1
    return min(OUTLINE_MAX_PATH_DEPTH, max(1, d))


def _temp_path_for_outline_level(outline_level: Any, temp: int) -> str:
    depth = _clamp_path_depth(path_depth_from_outline_level(outline_level))
    root = str(8000 + temp)
    if depth <= 1:
        return root
    return root + ".1" * (depth - 1)


def _serialize_fenced_block(tag: str, fields: dict[str, str]) -> list[str]:
    lines = [f"@{tag}"]
    src = fields or {}
    ordered: list[tuple[str, str]] = []
    if src.get("index", "").strip():
        ordered.append(("index", src["index"].strip()))
    if src.get("title", "").strip():
        ordered.append(("title", src["title"].strip()))
    for key, value in src.items():
        if key in ("index", "title"):
            continue
        if value is None or not str(value).strip():
            continue
        ordered.append((key, str(value).strip()))
    for key, value in ordered:
        lines.append(f"{key}: {value}")
    lines.append(f"@/{tag}")
    return lines


def _syllabus_fence_lines(path_id: Any, title_text: Any) -> list[str]:
    title = str(title_text or "").strip() or "Section"
    return _serialize_fenced_block(
        "section",
        {"index": str(path_id or "").strip(), "title": title},
    )


def _read_fenced_block_at(
    lines: list[str], open_line: int
) -> Optional[dict[str, Any]]:
    if open_line < 0 or open_line >= len(lines):
        return None
    t = str(lines[open_line] or "").strip()
    tag = None
    if _SECTION_OPEN.match(t):
        tag = "section"
    elif _SUBSECTION_OPEN.match(t):
        tag = "subsection"
    if not tag:
        return None
    fields: dict[str, str] = {}
    i = open_line + 1
    while i < len(lines):
        lt = str(lines[i] or "").strip()
        if _FENCE_CLOSE.match(lt) and tag in lt.lower():
            return {"tag": tag, "fields": fields, "endLine": i}
        if lt and ":" in lt:
            key, value = lt.split(":", 1)
            fields[key.strip().lower()] = value.strip()
        i += 1
    return {"tag": tag, "fields": fields, "endLine": open_line}


def _replace_fenced_block_at(
    lines: list[str], open_line: int, tag: str, fields: dict[str, str]
) -> None:
    block = _serialize_fenced_block(tag, fields)
    read = _read_fenced_block_at(lines, open_line)
    close_line = read["endLine"] if read else open_line
    lines[open_line : close_line + 1] = block


def _replace_outline_row_with_fence(
    lines: list[str], heading_line: int, path_id: Any, title_text: Any
) -> int:
    if heading_line < 0 or heading_line >= len(lines):
        return 0
    fence = _syllabus_fence_lines(path_id, title_text)
    raw = str(lines[heading_line] or "").strip()
    span = 1
    if _SECTION_OPEN.match(raw) or _SUBSECTION_OPEN.match(raw):
        block = _read_fenced_block_at(lines, heading_line)
        if block and isinstance(block.get("endLine"), int):
            span = max(1, block["endLine"] - heading_line + 1)
    lines[heading_line : heading_line + span] = fence
    return len(fence) - span


def _index_from_fields(fields: Optional[dict[str, str]]) -> str:
    return str((fields or {}).get("index") or "").strip()


def toc_heading_title_for_edit(heading_raw: Optional[str]) -> str:
    if not heading_raw:
        return ""
    t = heading_raw.strip()
    if re.match(r"^#{1,6}$", t):
        return ""
    syl = parse_syllabus_path_line(t)
    if syl:
        inner = syl["title"]
    else:
        inner = t
        for n in range(6, 0, -1):
            prefix = "#" * n + " "
            if t.startswith(prefix):
                inner = t[len(prefix) :]
                break
        else:
            if t.startswith("@@section@@"):
                inner = t[len("@@section@@") :].strip()
            elif t.startswith("@@subsection@@"):
                inner = t[len("@@subsection@@") :].strip()
        inner = strip_outline_path_id(inner)
    m = _EMOJI_PREFIX.match(inner)
    if m:
        return strip_outline_path_id(inner[m.end() :]).strip()
    return inner.strip()


def _toc_heading_emoji_prefix(heading_raw: Optional[str]) -> str:
    if not heading_raw:
        return ""
    t = heading_raw.strip()
    syl = parse_syllabus_path_line(t)
    if syl:
        inner = syl["title"]
    else:
        inner = t
        for n in range(6, 0, -1):
            prefix = "#" * n + " "
            if t.startswith(prefix):
                inner = t[len(prefix) :]
                break
        else:
            if t.startswith("@@section@@"):
                inner = t[len("@@section@@") :].strip()
            elif t.startswith("@@subsection@@"):
                inner = t[len("@@subsection@@") :].strip()
        inner = strip_outline_path_id(inner)
    m = _EMOJI_PREFIX.match(inner)
    if m:
        return m.group(1)
    if inner and re.match(r"[^\w\s.,;:!?\-]", inner[0]):
        cp = ord(inner[0])
        if cp > 0xFFFF:
            ch = chr(cp)
        else:
            ch = inner[0]
        if inner.startswith(ch + " ") or len(inner) == 1:
            return ch
    return ""


def _heading_kind(heading_raw: Optional[str]) -> tuple[str, int]:
    """Return (kind, level). kind in syllabus|md1..md6|section|subsection|unknown."""
    if not heading_raw:
        return "unknown", 0
    t = heading_raw.strip()
    syl = parse_syllabus_path_line(t)
    if syl and is_outline_path_id(syl["path"]):
        return "syllabus", outline_level_from_path_id(syl["path"])
    if t.startswith("@@section@@") or _SECTION_OPEN.match(t):
        return "section", 2
    if t.startswith("@@subsection@@") or _SUBSECTION_OPEN.match(t):
        return "subsection", 3
    m = _HEADING_RE.match(t)
    if m:
        lv = len(m.group(1))
        return f"md{lv}", lv
    return "unknown", 0


def toc_range_outline_level(r: dict[str, Any]) -> Optional[int]:
    if not r:
        return None
    if r.get("headingLine") is None:
        return 0 if r.get("synthetic") else None
    path = outline_path_id_from_text(r.get("headingRaw"))
    if not path and is_outline_path_id(r.get("id")):
        path = str(r.get("id"))
    if path:
        return outline_level_from_path_id(path)
    kind, lv = _heading_kind(r.get("headingRaw"))
    if kind.startswith("md") or kind in ("section", "subsection"):
        return lv
    return None


def _ensure_in_lesson_lg_title(lines: list[str], heading_index: int, title_text: str) -> bool:
    """Insert ``{{lg}}Title{{/lg}}`` under an outline row if prose has no large title yet."""
    title = (title_text or "").strip()
    if not title or heading_index < 0 or heading_index >= len(lines):
        return False
    i = heading_index + 1
    while i < len(lines) and not str(lines[i] or "").strip():
        i += 1
    nxt = str(lines[i] or "").strip() if i < len(lines) else ""
    if re.search(r"\{\{lg\}\}", nxt, re.I):
        return False
    lines[heading_index + 1 : heading_index + 1] = ["", f"{{{{lg}}}}{title}{{{{/lg}}}}", ""]
    return True


def _collect_atx_outline_hits(lines: list[str]) -> list[dict[str, int]]:
    hits: list[dict[str, int]] = []
    in_code = False
    in_quiz = False
    i = 0
    while i < len(lines):
        raw = lines[i]
        t = str(raw or "").strip()
        if t.startswith("```"):
            in_code = not in_code
            i += 1
            continue
        if in_code:
            i += 1
            continue
        if in_quiz:
            if _QUIZ_CLOSE.match(t):
                in_quiz = False
            i += 1
            continue
        if _QUIZ_OPEN.match(t):
            in_quiz = True
            i += 1
            continue
        if _SECTION_OPEN.match(t) or _SUBSECTION_OPEN.match(t):
            block = _read_fenced_block_at(lines, i)
            if block and isinstance(block.get("endLine"), int):
                i = block["endLine"] + 1
            else:
                i += 1
            continue
        blank = re.match(r"^(#{1,6})$", t)
        if blank:
            hits.append({"hi": i, "level": len(blank.group(1))})
            i += 1
            continue
        kind, level = _heading_kind(raw)
        if kind.startswith("md"):
            hits.append({"hi": i, "level": level})
        i += 1
    return hits


def promote_outline_atx_to_syllabus(body: Optional[str]) -> str:
    """Convert outline ATX rows to temporary indexed ``@section`` fences."""
    text = "" if body is None else str(body)
    lines = text.split("\n")
    hits = _collect_atx_outline_hits(lines)
    if not hits:
        return text
    changed = False
    temp = 0
    for hit in reversed(hits):
        hi = hit["hi"]
        level = hit["level"]
        if hi < 0 or hi >= len(lines):
            continue
        raw = lines[hi]
        em = _toc_heading_emoji_prefix(raw)
        title = toc_heading_title_for_edit(raw)
        combined = f"{em} {title}" if em else title
        temp += 1
        L = max(2, level or 2)
        _replace_outline_row_with_fence(
            lines, hi, _temp_path_for_outline_level(L, temp), combined
        )
        if _ensure_in_lesson_lg_title(lines, hi + 3, title):
            changed = True
        changed = True
    return "\n".join(lines) if changed else text


def flatten_outline_fences_to_atx(body: Optional[str], inject_lg: bool = True) -> str:
    """Ensure every outline row is ``@section`` + ``index`` (+ title)."""
    text = "" if body is None else str(body)
    ranges = get_toc_line_ranges(text)
    lines = text.split("\n")
    changed = False
    temp = 0
    for r in reversed(ranges):
        if not r or r.get("synthetic") or r.get("headingLine") is None:
            continue
        hi = r["headingLine"]
        if hi < 0 or hi >= len(lines):
            continue
        raw = str(lines[hi] or "").strip()
        kind, _lv = _heading_kind(r.get("headingRaw"))
        title = toc_heading_title_for_edit(r.get("headingRaw")).strip() or (
            "Subsection" if kind == "subsection" else "Section"
        )
        if (
            kind in ("section", "subsection")
            or _SECTION_OPEN.match(raw)
            or _SUBSECTION_OPEN.match(raw)
        ):
            block = _read_fenced_block_at(lines, hi)
            from_field = _index_from_fields(block["fields"] if block else None)
            from_id = str(r.get("id") or "")
            temp += 1
            L = toc_range_outline_level(r) or (3 if kind == "subsection" else 2)
            path = (
                from_field
                if is_outline_path_id(from_field)
                else from_id
                if is_outline_path_id(from_id)
                else _temp_path_for_outline_level(L, temp)
            )
            had_index = is_outline_path_id(from_field) or is_outline_path_id(from_id)
            _replace_outline_row_with_fence(lines, hi, path, title)
            if inject_lg and not had_index:
                _ensure_in_lesson_lg_title(lines, hi + 3, title)
            changed = True
            continue
        if kind == "syllabus" or kind.startswith("md"):
            temp += 1
            L = toc_range_outline_level(r) or 2
            path = (
                str(r.get("id") or "")
                if is_outline_path_id(r.get("id"))
                else outline_path_id_from_text(raw)
                or _temp_path_for_outline_level(L, temp)
            )
            _replace_outline_row_with_fence(lines, hi, path, title)
            if inject_lg and kind.startswith("md"):
                _ensure_in_lesson_lg_title(lines, hi + 3, title)
            changed = True
    return "\n".join(lines) if changed else text


def materialize_syllabus_as_section_fences(body: Optional[str]) -> str:
    """Convert leftover ``#path}`` lines to ``@section`` fences (ingest helper)."""
    text = "" if body is None else str(body)
    if not _BODY_HAS_SYLLABUS.search(text):
        return text
    return flatten_outline_fences_to_atx(text, inject_lg=False)


def prepare_construct_outline_math(body: Optional[str], fallback_title: str = "Section") -> str:
    text = "" if body is None else str(body)
    text = normalize_construct_outline_roots(text)
    has_fence = bool(
        re.search(r"(?:^|\n)@section\b", text, re.I)
        or re.search(r"(?:^|\n)@subsection\b", text, re.I)
    )
    has_path = bool(_BODY_HAS_SYLLABUS.search(text))
    has_atx = bool(re.search(r"(?:^|\n)#{1,6}(?: |$)", text, re.M))
    if has_fence or has_path or has_atx:
        if has_atx:
            text = promote_outline_atx_to_syllabus(text)
        text = flatten_outline_fences_to_atx(text)
    text = repair_empty_outline_titles(text, fallback_title)
    if re.search(r"(?:^|\n)#{1,6}(?: |$)", text, re.M):
        text = promote_outline_atx_to_syllabus(text)
        text = flatten_outline_fences_to_atx(text, inject_lg=True)
    text = renumber_outline_paths(text)
    return text


def prepare_construct_outline_body(body: Optional[str], fallback_title: str = "Section") -> str:
    """Alias — human and math share indexed ``@section`` fences."""
    return prepare_construct_outline_math(body, fallback_title)


def _fenced_title_at(lines: list[str], start: int) -> str:
    i = start + 1
    while i < len(lines):
        t = lines[i].strip()
        if _FENCE_CLOSE.match(t):
            break
        if t.lower().startswith("title:"):
            return t.split(":", 1)[1].strip()
        i += 1
    return ""


def _heading_id_from_raw(raw_title: str, slug_counts: dict[str, int]) -> str:
    embedded = outline_path_id_from_text(raw_title)
    if embedded:
        n = slug_counts.get(embedded, 0) + 1
        slug_counts[embedded] = n
        return embedded if n == 1 else f"{embedded}-{n}"
    title = toc_heading_title_for_edit(f"## {strip_outline_path_id(raw_title)}")
    base = _slug(title)
    if base == SYNTHETIC_INTRO_ID:
        base = "section"
    n = slug_counts.get(base, 0) + 1
    slug_counts[base] = n
    return base if n == 1 else f"{base}-{n}"


def _fence_range_id(lines: list[str], open_line: int, slug_counts: dict[str, int]) -> str:
    block = _read_fenced_block_at(lines, open_line)
    index = _index_from_fields(block["fields"] if block else None)
    if is_outline_path_id(index):
        return index
    title = (block or {}).get("fields", {}).get("title") or _fenced_title_at(lines, open_line)
    return _heading_id_from_raw(title, slug_counts)


def get_toc_line_ranges(body: Optional[str]) -> list[dict[str, Any]]:
    text = "" if body is None else str(body)
    lines = text.split("\n")
    headings: list[tuple[int, str, str]] = []  # headingLine, id, headingRaw
    in_code = False
    in_quiz = False
    fenced_tag: Optional[str] = None
    slug_counts: dict[str, int] = {}
    for i, raw in enumerate(lines):
        t = raw.strip()
        if t.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if in_quiz:
            if _QUIZ_CLOSE.match(t):
                in_quiz = False
            continue
        if fenced_tag:
            if _FENCE_CLOSE.match(t) and fenced_tag in t.lower():
                fenced_tag = None
            continue
        if _QUIZ_OPEN.match(t):
            in_quiz = True
            continue
        if _SECTION_OPEN.match(t):
            sid = _fence_range_id(lines, i, slug_counts)
            title = _fenced_title_at(lines, i)
            headings.append((i, sid, f"@@section@@{title}"))
            fenced_tag = "section"
            continue
        if _SUBSECTION_OPEN.match(t):
            sid = _fence_range_id(lines, i, slug_counts)
            title = _fenced_title_at(lines, i)
            headings.append((i, sid, f"@@subsection@@{title}"))
            fenced_tag = "subsection"
            continue
        if not is_outline_heading_line(t, text):
            continue
        syl = parse_syllabus_path_line(t)
        if syl:
            headings.append((i, _heading_id_from_raw(t, slug_counts), raw))
            continue
        m = _HEADING_RE.match(t)
        if not m:
            continue
        title_part = m.group(2)
        headings.append((i, _heading_id_from_raw(title_part, slug_counts), raw))
    if not headings:
        return [
            {
                "id": SYNTHETIC_INTRO_ID,
                "startLine": 0,
                "endLine": len(lines),
                "headingLine": None,
                "headingRaw": None,
                "synthetic": True,
            }
        ]

    heading_lines = [h[0] for h in headings]
    range_starts = list(heading_lines)
    if heading_lines[0] > 0 and any(str(x or "").strip() for x in lines[: heading_lines[0]]):
        range_starts[0] = 0

    out: list[dict[str, Any]] = []
    for idx, (hl, sid, hraw) in enumerate(headings):
        end = heading_lines[idx + 1] if idx + 1 < len(heading_lines) else len(lines)
        out.append(
            {
                "id": sid,
                "startLine": range_starts[idx],
                "endLine": end,
                "headingLine": hl,
                "headingRaw": hraw,
                "synthetic": False,
            }
        )
    return out


def renumber_outline_paths(body: Optional[str]) -> str:
    """Assign human ``index:`` values from syllabus nest depth."""
    text = "" if body is None else str(body)
    ranges = get_toc_line_ranges(text)
    lines = text.split("\n")
    assignments: list[dict[str, Any]] = []
    root_count = 0
    stack: list[dict[str, Any]] = []
    for r in ranges:
        if not r or r.get("synthetic") or r.get("headingLine") is None:
            continue
        L = toc_range_outline_level(r)
        if L is None or L < 2:
            continue
        while stack and stack[-1]["level"] >= L:
            stack.pop()
        if not stack:
            root_count += 1
            path = str(root_count)
        else:
            parent = stack[-1]
            parent["childCount"] += 1
            path = f"{parent['path']}.{parent['childCount']}"
        stack.append({"level": L, "path": path, "childCount": 0})
        em = _toc_heading_emoji_prefix(r.get("headingRaw"))
        title = toc_heading_title_for_edit(r.get("headingRaw"))
        combined = f"{em} {title}" if em else title
        assignments.append({"hi": r["headingLine"], "path": path, "title": combined})
    changed = False
    for a in reversed(assignments):
        hi = a["hi"]
        if hi < 0 or hi >= len(lines):
            continue
        _replace_outline_row_with_fence(lines, hi, a["path"], a["title"])
        changed = True
    return "\n".join(lines) if changed else text


def toc_subtree_exclusive_end(ranges: list[dict[str, Any]], from_idx: int) -> int:
    L = toc_range_outline_level(ranges[from_idx])
    if L is None:
        return from_idx + 1
    k = from_idx + 1
    while k < len(ranges):
        Lk = toc_range_outline_level(ranges[k])
        if Lk is None or Lk <= L:
            break
        k += 1
    return k


def max_outline_level_in_subtree(ranges: list[dict[str, Any]], from_idx: int) -> int:
    if not ranges or from_idx < 0 or from_idx >= len(ranges):
        return 0
    sub_end = toc_subtree_exclusive_end(ranges, from_idx)
    max_l = 0
    for i in range(from_idx, sub_end):
        Li = toc_range_outline_level(ranges[i])
        if Li is not None:
            max_l = max(max_l, Li)
    return max_l


def _outline_depths_for_ranges(ranges: list[dict[str, Any]]) -> list[int]:
    depths: list[int] = []
    for r in ranges:
        if not r or r.get("synthetic"):
            depths.append(1)
            continue
        path = outline_path_id_from_text(r.get("headingRaw"))
        if not path and is_outline_path_id(r.get("id")):
            path = str(r.get("id"))
        if path:
            depths.append(_clamp_path_depth(len(str(path).split("."))))
            continue
        L = toc_range_outline_level(r)
        if L is None or L < 2:
            depths.append(1)
        else:
            depths.append(_clamp_path_depth(L - 1))
    return depths

def rewrite_outline_by_depths(body: Optional[str], depths: list[int]) -> str:
    """Rewrite syllabus rows to ``@section`` + ``index`` + ``title`` using nest depths."""
    text = "" if body is None else str(body)
    ranges = get_toc_line_ranges(text)
    lines = text.split("\n")
    root_count = 0
    stack: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    for i, r in enumerate(ranges):
        if not r or r.get("synthetic") or r.get("headingLine") is None:
            continue
        depth = _clamp_path_depth(depths[i] if i < len(depths) and depths[i] else 1)
        L = depth + 1
        while stack and stack[-1]["level"] >= L:
            stack.pop()
        if not stack:
            root_count += 1
            path = str(root_count)
        else:
            parent = stack[-1]
            parent["childCount"] += 1
            path = f"{parent['path']}.{parent['childCount']}"
        stack.append({"level": L, "path": path, "childCount": 0})
        em = _toc_heading_emoji_prefix(r.get("headingRaw"))
        title = toc_heading_title_for_edit(r.get("headingRaw"))
        combined = f"{em} {title}" if em else title
        assignments.append({"hi": r["headingLine"], "path": path, "title": combined})
    changed = False
    for a in reversed(assignments):
        hi = a["hi"]
        if hi < 0 or hi >= len(lines):
            continue
        _replace_outline_row_with_fence(lines, hi, a["path"], a["title"])
        changed = True
    return "\n".join(lines) if changed else text


def shift_subtree_outline_depths(body: Optional[str], from_idx: int, sub_end: int, delta: int) -> str:
    """Apply nest-depth delta to a syllabus subtree, then rewrite fence ``index:`` rows."""
    if not delta:
        return "" if body is None else str(body)
    text = "" if body is None else str(body)
    ranges = get_toc_line_ranges(text)
    depths = _outline_depths_for_ranges(ranges)
    for i in range(from_idx, sub_end):
        if 0 <= i < len(depths):
            depths[i] = _clamp_path_depth((depths[i] or 1) + delta)
    return rewrite_outline_by_depths(text, depths)


def _rewrite_atx_heading_to_level(heading_raw: str, target_level: int) -> str:
    title = toc_heading_title_for_edit(heading_raw)
    em = _toc_heading_emoji_prefix(heading_raw)
    combined = f"{em} {title}" if em else title
    L = max(1, min(6, int(target_level) if target_level is not None else 2))
    return f"{'#' * L} {combined}".rstrip()


def normalize_construct_outline_roots(body: Optional[str]) -> str:
    text = "" if body is None else str(body)
    ranges = get_toc_line_ranges(text)
    lines = text.split("\n")
    changed = False
    for r in ranges:
        if r.get("headingLine") is None:
            continue
        kind, _ = _heading_kind(r.get("headingRaw"))
        if kind != "md1":
            continue
        hi = r["headingLine"]
        lines[hi] = _rewrite_atx_heading_to_level(lines[hi], 2)
        changed = True
    return "\n".join(lines) if changed else text


def repair_empty_outline_titles(body: Optional[str], fallback_base: str = "Section") -> str:
    text = "" if body is None else str(body)
    lines = text.split("\n")
    changed = False
    used: set[str] = set()
    base = (fallback_base or "Section").strip() or "Section"

    def take_title() -> str:
        n = 1
        nxt = base
        while nxt.lower() in used:
            n += 1
            nxt = f"{base} {n}"
        used.add(nxt.lower())
        return nxt

    for r in get_toc_line_ranges(text):
        if not r or r.get("synthetic"):
            continue
        t = toc_heading_title_for_edit(r.get("headingRaw") or "").strip()
        if t:
            used.add(t.lower())

    in_code = False
    in_quiz = False
    for i, raw in enumerate(lines):
        t = str(raw or "").strip()
        if t.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if in_quiz:
            if _QUIZ_CLOSE.match(t):
                in_quiz = False
            continue
        if _QUIZ_OPEN.match(t):
            in_quiz = True
            continue
        m = _BLANK_HEADING_RE.match(t)
        if not m:
            continue
        lines[i] = f"{m.group(1)} {take_title()}"
        changed = True

    joined = "\n".join(lines)
    for r in get_toc_line_ranges(joined):
        if not r or r.get("headingLine") is None or r.get("synthetic"):
            continue
        raw = str(r.get("headingRaw") or lines[r["headingLine"]] or "")
        if toc_heading_title_for_edit(raw).strip():
            continue
        L = toc_range_outline_level(r) or 2
        em = _toc_heading_emoji_prefix(raw)
        title = take_title()
        lines[r["headingLine"]] = (
            f"{'#' * max(1, min(6, L))} {em + ' ' if em else ''}{title}".rstrip()
        )
        changed = True
    return "\n".join(lines) if changed else text


def child_outline_level_for_parent(parent_level: Any) -> int:
    try:
        p = int(parent_level)
    except (TypeError, ValueError):
        return 3
    if p < 1:
        return 3
    if p >= OUTLINE_MAX_LEVEL:
        return OUTLINE_MAX_LEVEL
    return min(OUTLINE_MAX_LEVEL, p + 1)


def _previous_sibling_at_level(ranges: list[dict[str, Any]], toc_idx: int, L: int) -> int:
    prev = toc_idx - 1
    while prev >= 0:
        Lp = toc_range_outline_level(ranges[prev])
        if Lp is None or Lp < L:
            return -1
        if Lp == L:
            return prev
        prev -= 1
    return -1


def resolve_toc_range_index(
    ranges: list[dict[str, Any]], toc_idx: int, toc: Optional[list[dict[str, Any]]] = None
) -> int:
    idx = toc_idx
    if not isinstance(toc, list) or toc_idx < 0 or toc_idx >= len(toc) or not ranges:
        return idx if isinstance(idx, int) and idx >= 0 else -1
    rid = toc[toc_idx].get("id")
    ord_ = sum(1 for i in range(toc_idx) if toc[i].get("id") == rid)
    seen = 0
    for i, r in enumerate(ranges):
        if r.get("id") != rid:
            continue
        if seen == ord_:
            return i
        seen += 1
    return idx if 0 <= idx < len(ranges) else -1


def toc_section_move_availability(
    body: Optional[str], toc_idx: int, toc: Optional[list[dict[str, Any]]] = None
) -> dict[str, bool]:
    none = {"canUp": False, "canDown": False, "canOutdent": False, "canIndent": False}
    text = prepare_construct_outline_math(body)
    ranges = get_toc_line_ranges(text)
    try:
        idx = int(toc_idx)
    except (TypeError, ValueError):
        return none
    if idx < 0 or idx >= len(ranges):
        return none
    r = ranges[idx]
    if not r or r.get("synthetic"):
        return none
    L = toc_range_outline_level(r)
    if L is None or L < 2:
        return none
    prev_sib = _previous_sibling_at_level(ranges, idx, L)
    can_up = prev_sib >= 0
    sub_end = toc_subtree_exclusive_end(ranges, idx)
    can_down = sub_end < len(ranges) and toc_range_outline_level(ranges[sub_end]) == L
    can_outdent = L > 2
    can_indent = prev_sib >= 0 and max_outline_level_in_subtree(ranges, idx) < OUTLINE_MAX_LEVEL
    return {
        "canUp": can_up,
        "canDown": can_down,
        "canOutdent": can_outdent,
        "canIndent": can_indent,
    }


def set_toc_section_level(
    body: Optional[str],
    toc_index: int,
    target_level: int,
    toc: Optional[list[dict[str, Any]]] = None,
) -> str:
    text = prepare_construct_outline_math(body)
    ranges = get_toc_line_ranges(text)
    try:
        idx = int(toc_index)
    except (TypeError, ValueError):
        return text
    if idx < 0 or idx >= len(ranges):
        return text
    r = ranges[idx]
    if not r or r.get("synthetic"):
        return text
    next_level = max(
        2, min(OUTLINE_MAX_LEVEL, int(target_level) if target_level is not None else 2)
    )
    cur_level = toc_range_outline_level(r)
    if cur_level is None or cur_level < 2 or cur_level == next_level:
        return text
    delta = path_depth_from_outline_level(next_level) - path_depth_from_outline_level(cur_level)
    if (
        delta > 0
        and max_outline_level_in_subtree(ranges, idx) + (next_level - cur_level) > OUTLINE_MAX_LEVEL
    ):
        return text
    sub_end = toc_subtree_exclusive_end(ranges, idx)
    return prepare_construct_outline_math(shift_subtree_outline_depths(text, idx, sub_end, delta))


def reorder_toc_section_range(body: Optional[str], from_idx: int, insert_index: int) -> str:
    text = "" if body is None else str(body)
    ranges = get_toc_line_ranges(text)
    if not ranges or from_idx < 0 or from_idx >= len(ranges):
        return text
    from_r = ranges[from_idx]
    if not from_r or from_r.get("synthetic"):
        return text
    ins = max(0, min(int(insert_index), len(ranges)))
    sub_end = toc_subtree_exclusive_end(ranges, from_idx)
    if from_idx < ins < sub_end:
        return text
    lines = text.split("\n")
    source_start = from_r["startLine"]
    source_end = ranges[sub_end]["startLine"] if sub_end < len(ranges) else len(lines)
    slice_lines = lines[source_start:source_end]
    without = lines[:source_start] + lines[source_end:]
    if ins >= len(ranges):
        insert_line = len(without)
    else:
        anchor = ranges[ins]["startLine"]
        if from_idx < ins:
            anchor -= source_end - source_start
        insert_line = max(0, min(anchor, len(without)))
    out = without[:insert_line] + slice_lines + without[insert_line:]
    return "\n".join(out)


def move_toc_section_by_action(
    body: Optional[str],
    toc_idx: int,
    action: Literal["up", "down", "indent", "outdent"],
    toc: Optional[list[dict[str, Any]]] = None,
) -> str:
    return apply_toc_section_move(body, toc_idx, action)["body"]


def _move_action_allowed(avail: dict[str, bool], action: str) -> bool:
    if action == "up":
        return bool(avail.get("canUp"))
    if action == "down":
        return bool(avail.get("canDown"))
    if action == "indent":
        return bool(avail.get("canIndent"))
    if action == "outdent":
        return bool(avail.get("canOutdent"))
    return False


def toc_selected_index_after_move(
    body: Optional[str], toc_idx: int, action: Literal["up", "down", "indent", "outdent"]
) -> int:
    text = prepare_construct_outline_math(body)
    ranges = get_toc_line_ranges(text)
    try:
        idx = int(toc_idx)
    except (TypeError, ValueError):
        return -1
    if idx < 0 or idx >= len(ranges):
        return -1
    r = ranges[idx]
    if not r or r.get("synthetic"):
        return -1
    L = toc_range_outline_level(r)
    if L is None:
        return -1
    if action == "up":
        prev = _previous_sibling_at_level(ranges, idx, L)
        return prev if prev >= 0 else idx
    if action == "down":
        sub_end = toc_subtree_exclusive_end(ranges, idx)
        if sub_end >= len(ranges) or toc_range_outline_level(ranges[sub_end]) != L:
            return idx
        next_end = toc_subtree_exclusive_end(ranges, sub_end)
        return idx + (next_end - sub_end)
    return idx


def apply_toc_section_move(
    body: Optional[str],
    toc_idx: int,
    action: Literal["up", "down", "indent", "outdent"],
) -> dict[str, Any]:
    """Cave-man outline move: ``ok`` is path geometry only, never body-byte equality."""
    text = prepare_construct_outline_math(body)
    ranges = get_toc_line_ranges(text)
    try:
        idx = int(toc_idx)
    except (TypeError, ValueError):
        return {"ok": False, "body": text, "selectedIndex": 0}
    if idx < 0 or idx >= len(ranges):
        return {"ok": False, "body": text, "selectedIndex": max(0, idx)}
    r = ranges[idx]
    if not r or r.get("synthetic"):
        return {"ok": False, "body": text, "selectedIndex": idx}
    L = toc_range_outline_level(r)
    if L is None:
        return {"ok": False, "body": text, "selectedIndex": idx}
    avail = toc_section_move_availability(text, idx)
    if not _move_action_allowed(avail, action):
        return {"ok": False, "body": text, "selectedIndex": idx}
    selected = toc_selected_index_after_move(text, idx, action)
    next_body = text
    if action == "up":
        prev = _previous_sibling_at_level(ranges, idx, L)
        next_body = prepare_construct_outline_math(reorder_toc_section_range(text, idx, prev))
    elif action == "down":
        sub_end = toc_subtree_exclusive_end(ranges, idx)
        next_end = toc_subtree_exclusive_end(ranges, sub_end)
        next_body = prepare_construct_outline_math(reorder_toc_section_range(text, idx, next_end))
    elif action == "outdent":
        next_body = set_toc_section_level(text, idx, L - 1)
    elif action == "indent":
        next_body = set_toc_section_level(text, idx, L + 1)
    return {"ok": True, "body": next_body, "selectedIndex": selected}

def insert_line_after_toc_subtree(ranges: list[dict[str, Any]], parent_idx: int, line_count: int) -> int:
    if not ranges or parent_idx < 0 or parent_idx >= len(ranges):
        return max(0, int(line_count or 0))
    sub_end = toc_subtree_exclusive_end(ranges, parent_idx)
    if sub_end > parent_idx + 1:
        return ranges[sub_end - 1]["endLine"]
    return ranges[parent_idx]["endLine"]


def _sanitize_prose(prose: str) -> str:
    """Drop outline headings from inserted starter prose."""
    out: list[str] = []
    for ln in str(prose or "").split("\n"):
        t = ln.strip()
        if parse_syllabus_path_line(t) or _HEADING_RE.match(t) or _SECTION_OPEN.match(t) or _SUBSECTION_OPEN.match(t):
            continue
        out.append(ln)
    return "\n".join(out).strip()


def _splice_heading(
    lines: list[str], insert_at: int, heading: str | list[str], prose: str
) -> None:
    p = _sanitize_prose(prose)
    head_lines = heading if isinstance(heading, list) else str(heading).split("\n")
    chunk = ["", *head_lines, *p.split("\n"), ""] if p else ["", *head_lines, "", ""]
    lines[insert_at:insert_at] = chunk


def add_toc_subsection_after(
    body: Optional[str],
    after_toc_index: int,
    title: str = "New subsection",
    starter_prose: str = "",
) -> str:
    safe_title = (title or "").strip() or "New subsection"
    text = prepare_construct_outline_math(body, safe_title)
    ranges = get_toc_line_ranges(text)
    prose = _sanitize_prose(starter_prose)

    if len(ranges) == 1 and ranges[0].get("synthetic"):
        base = text.rstrip()
        root = "## New section\n" + (f"{base}\n" if base else "")
        text = prepare_construct_outline_math(root, "New section")
        ranges = get_toc_line_ranges(text)

    if not ranges or (len(ranges) == 1 and ranges[0].get("synthetic")):
        heading = _syllabus_fence_lines("1", safe_title)
        draft = "\n".join([*heading, prose, ""]) if prose else "\n".join([*heading, ""])
        return prepare_construct_outline_math(draft, safe_title)

    safe_idx = max(0, min(after_toc_index, max(0, len(ranges) - 1)))
    clicked = ranges[safe_idx]
    if not clicked or clicked.get("synthetic"):
        return text
    clicked_level = toc_range_outline_level(clicked)
    if clicked_level is None or clicked_level < 1:
        return text
    lines = text.split("\n")
    insert_at = insert_line_after_toc_subtree(ranges, safe_idx, len(lines))
    parent_depth = _outline_depths_for_ranges(ranges)[safe_idx] or 1
    want_depth = (
        parent_depth
        if clicked_level >= OUTLINE_MAX_LEVEL
        else _clamp_path_depth(parent_depth + 1)
    )
    heading = _syllabus_fence_lines("999", safe_title)
    _splice_heading(lines, insert_at, heading, prose)
    next_body = "\n".join(lines)
    ranges_after = get_toc_line_ranges(next_body)
    depths = _outline_depths_for_ranges(ranges_after)
    new_idx = next(
        (i for i, r in enumerate(ranges_after) if i > safe_idx and str(r.get("id")) == "999"),
        -1,
    )
    if new_idx < 0:
        new_idx = next(
            (
                i
                for i, r in enumerate(ranges_after)
                if toc_heading_title_for_edit(r.get("headingRaw")) == safe_title
                and str(r.get("id")) == "999"
            ),
            -1,
        )
    if new_idx < 0:
        new_idx = min(len(ranges_after) - 1, safe_idx + 1)
    if 0 <= new_idx < len(depths):
        depths[new_idx] = want_depth
    next_body = rewrite_outline_by_depths(next_body, depths)
    return prepare_construct_outline_math(next_body, safe_title)


def add_toc_section_after(
    body: Optional[str],
    after_toc_index: int,
    title: str = "New section",
    starter_prose: str = "",
) -> str:
    safe_title = (title or "").strip() or "New section"
    text = prepare_construct_outline_math(body, safe_title)
    ranges = get_toc_line_ranges(text)
    heading = _syllabus_fence_lines("999", safe_title)
    prose = _sanitize_prose(starter_prose)
    if len(ranges) == 1 and ranges[0].get("synthetic"):
        base = text.rstrip()
        if not base:
            draft = "\n".join([*heading, prose, ""]) if prose else "\n".join([*heading, ""])
            return prepare_construct_outline_math(draft, safe_title)
        combined = "\n\n".join(x for x in (base, prose) if x)
        return prepare_construct_outline_math("\n".join([*heading, combined, ""]), safe_title)
    safe_idx = max(0, min(after_toc_index, len(ranges) - 1))
    insert_at = insert_line_after_toc_subtree(ranges, safe_idx, len(text.split("\n")))
    lines = text.split("\n")
    _splice_heading(lines, insert_at, heading, prose)
    next_body = "\n".join(lines)
    ranges_after = get_toc_line_ranges(next_body)
    depths = _outline_depths_for_ranges(ranges_after)
    new_idx = next(
        (i for i, r in enumerate(ranges_after) if i > safe_idx and str(r.get("id")) == "999"),
        -1,
    )
    if new_idx < 0:
        new_idx = next(
            (
                i
                for i, r in enumerate(ranges_after)
                if toc_heading_title_for_edit(r.get("headingRaw")) == safe_title
                and str(r.get("id")) == "999"
            ),
            -1,
        )
    if new_idx < 0:
        new_idx = len(ranges_after) - 1
    if new_idx >= 0:
        depths[new_idx] = 1
    next_body = rewrite_outline_by_depths(next_body, depths)
    return prepare_construct_outline_math(next_body, safe_title)


def construct_outline_invariants(body: Optional[str]) -> dict[str, Any]:
    errors: list[str] = []
    text = prepare_construct_outline_math(body)
    ranges = get_toc_line_ranges(text)
    actions = [
        ("up", "canUp"),
        ("down", "canDown"),
        ("indent", "canIndent"),
        ("outdent", "canOutdent"),
    ]
    for i, r in enumerate(ranges):
        if not r or r.get("synthetic"):
            continue
        L = toc_range_outline_level(r)
        if L is None:
            errors.append(f"idx {i}: null outline level")
            continue
        if L < 2:
            errors.append(f"idx {i}: level {L} below construct floor ##")
        if L > OUTLINE_MAX_LEVEL:
            errors.append(f"idx {i}: level {L} above max path depth")
        if not toc_heading_title_for_edit(r.get("headingRaw") or "").strip():
            errors.append(f"idx {i}: empty title")
        avail = toc_section_move_availability(text, i)
        if L > 2 and not avail["canOutdent"]:
            errors.append(f"idx {i}: L={L} but canOutdent false")
        for action, flag in actions:
            result = apply_toc_section_move(text, i, action)  # type: ignore[arg-type]
            if bool(avail[flag]) != bool(result["ok"]):
                errors.append(
                    f"idx {i}: {flag}={avail[flag]} but apply.{action}.ok={result['ok']}"
                )
            if not result["ok"]:
                continue
            if action == "up" and result["selectedIndex"] >= i:
                errors.append(
                    f"idx {i}: up ok but selectedIndex {result['selectedIndex']} not before"
                )
            if action == "down" and result["selectedIndex"] <= i:
                errors.append(
                    f"idx {i}: down ok but selectedIndex {result['selectedIndex']} not after"
                )
            if action in ("indent", "outdent") and result["body"] == text:
                errors.append(f"idx {i}: {action} ok but body unchanged")
    return {"ok": not errors, "errors": errors}

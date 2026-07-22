"""Quiz V2 parsing, modality helpers, and static quiz/match-pairs helpers.

Mirrors the canonical schema + modality helpers in
`arborito/src/features/learning/quiz-v2-schema.js`. Keep both files in sync
when the authoring schema or modality contract changes.

Authoring format (single fenced block per quiz):

    @quiz
    concept: GNU/Linux
    definition: Free {operating system} based on the Linux {kernel}
    question: What is GNU/Linux?
    answer: An open-source operating system
    modes: cloze,multiple,recall,chips
    traps:
    - A text editor
    - A relational database
    steps:
    - Step 1
    - Step 2
    @/quiz
"""

from __future__ import annotations

import random
import re
import unicodedata
from typing import Any, Optional


QUIZ_MODE_MULTIPLE = "multiple"
QUIZ_MODE_RECALL = "recall"
QUIZ_MODE_CLOZE = "cloze"
QUIZ_MODE_CHIPS = "chips"
QUIZ_MODE_STEPS = "steps"

ALL_QUIZ_MODES = [
    QUIZ_MODE_MULTIPLE,
    QUIZ_MODE_RECALL,
    QUIZ_MODE_CLOZE,
    QUIZ_MODE_CHIPS,
    QUIZ_MODE_STEPS,
]

_QUIZ_OPEN = re.compile(r"^@quiz\s*$", re.IGNORECASE)
_QUIZ_CLOSE = re.compile(r"^@/quiz\s*$", re.IGNORECASE)
_TRUTHY = {"1", "true", "yes", "si", "sí", "on", "y"}
_QUIZ_TRUTHY = _TRUTHY
_KEY_MAP = {
    "concept": "core_concept",
    "core_concept": "core_concept",
    "definition": "short_definition",
    "short_definition": "short_definition",
    "question": "main_question",
    "main_question": "main_question",
    "answer": "correct_answer",
    "correct_answer": "correct_answer",
}


def new_challenge() -> dict[str, Any]:
    return {
        "core_concept": "",
        "short_definition": "",
        "main_question": "",
        "correct_answer": "",
        "traps": [],
        "cloze_indices": [],
        "steps": [],
        "modes": [],
        "items": [],
        "answer_mode": "chips",
        "skip_multiple": False,
        "skip_ordering": False,
    }


def parse_inline_cloze(raw: str) -> tuple[str, list[int]]:
    """Strip `{phrase}` markers from a definition string."""
    s = raw or ""
    if "{" not in s or "}" not in s:
        return s.strip(), []
    plain_chars: list[str] = []
    masked: list[bool] = []
    inside = False
    for ch in s:
        if ch == "{" and not inside:
            inside = True
            continue
        if ch == "}" and inside:
            inside = False
            continue
        plain_chars.append(ch)
        masked.append(inside)
    if inside:
        return s.strip(), []
    plain = "".join(plain_chars)
    indices: list[int] = []
    for w_idx, m in enumerate(re.finditer(r"\S+", plain)):
        if any(masked[k] for k in range(m.start(), m.end())):
            indices.append(w_idx)
    return re.sub(r"\s+", " ", plain).strip(), indices


def _apply_quiz_kv(c: dict[str, Any], key: str, val: str) -> None:
    k = str(key or "").lower()
    if k == "definition":
        text, indices = parse_inline_cloze(val)
        c["short_definition"] = text
        if indices:
            c["cloze_indices"] = indices
        return
    if k in _KEY_MAP:
        c[_KEY_MAP[k]] = val
        return
    if k == "modes":
        c["modes"] = [m for m in re.split(r"[,|\s]+", val) if m in ALL_QUIZ_MODES]
        return
    if k == "skip_multiple":
        c["skip_multiple"] = val.lower() in _QUIZ_TRUTHY
        return
    if k == "skip_ordering":
        c["skip_ordering"] = val.lower() in _QUIZ_TRUTHY


def parse_quiz_block(body_lines: list[str]) -> dict[str, Any]:
    """Parse the body lines (between @quiz/@/quiz) into a challenge dict."""
    c = new_challenge()
    c["modes"] = []
    list_key: Optional[str] = None
    item_list_key: Optional[str] = None
    current_item: Optional[dict[str, Any]] = None

    def flush_item() -> None:
        nonlocal current_item, item_list_key
        if not current_item:
            return
        c["items"].append(dict(current_item))
        current_item = None
        item_list_key = None

    for raw in body_lines:
        line = raw.rstrip()
        if not line.strip():
            continue

        item_field = re.match(r"^\s{2,}([a-zA-Z_]+)\s*:\s*(.*)$", line)
        if item_field and list_key == "items" and current_item:
            fk = item_field.group(1).lower()
            fval = item_field.group(2).strip()
            if fk in ("traps", "steps"):
                item_list_key = fk
                if fval:
                    current_item[fk].append(fval)
            else:
                item_list_key = None
                _apply_quiz_kv(current_item, item_field.group(1), item_field.group(2))
            continue

        item_list = re.match(r"^\s{4,}-\s+(.*)$", line)
        if item_list and list_key == "items" and current_item and item_list_key:
            v = item_list.group(1).strip()
            if v:
                current_item[item_list_key].append(v)
            continue

        item_start = re.match(r"^  -\s+(.*)$", line)
        if item_start and list_key == "items":
            flush_item()
            current_item = new_challenge()
            current_item["modes"] = []
            rest = item_start.group(1).strip()
            kv_on_same = re.match(r"^\s*([a-zA-Z_]+)\s*:\s*(.*)$", rest)
            if kv_on_same:
                _apply_quiz_kv(current_item, kv_on_same.group(1), kv_on_same.group(2))
            continue

        item_match = re.match(r"^\s*-\s+(.*)$", line)
        if item_match and list_key and list_key != "items":
            v = item_match.group(1).strip()
            if v:
                c[list_key].append(v)
            continue

        kv = re.match(r"^\s*([a-zA-Z_]+)\s*:\s*(.*)$", line)
        if not kv:
            list_key = None
            item_list_key = None
            continue

        key = kv.group(1).lower()
        val = kv.group(2).strip()

        if key in ("traps", "steps", "items"):
            list_key = key
            item_list_key = None
            if key == "items":
                flush_item()
                continue
            if val:
                c[key].append(val)
            continue

        if list_key == "items" and current_item:
            _apply_quiz_kv(current_item, key, val)
        else:
            list_key = None
            item_list_key = None
            if key in ("traps", "steps"):
                list_key = key
                if val:
                    c[key].append(val)
            elif key == "skip_multiple":
                c["skip_multiple"] = val.lower() in _QUIZ_TRUTHY
            elif key == "skip_ordering":
                c["skip_ordering"] = val.lower() in _QUIZ_TRUTHY
            else:
                _apply_quiz_kv(c, key, val)

    flush_item()
    if len(c["steps"]) >= 2:
        c["answer_mode"] = "steps"
    return c


def render_inline_cloze(text: str, indices: list[int]) -> str:
    """Write `{phrase}` markers into a definition string for serialization."""
    words = [w for w in re.split(r"\s+", str(text or "").strip()) if w]
    if not words or not indices:
        return str(text or "")
    blank = {i for i in indices if isinstance(i, int) and 0 <= i < len(words)}
    if not blank:
        return str(text or "")
    out: list[str] = []
    i = 0
    while i < len(words):
        if i not in blank:
            out.append(words[i])
            i += 1
            continue
        j = i
        while j < len(words) and j in blank:
            j += 1
        out.append("{" + " ".join(words[i:j]) + "}")
        i = j
    return " ".join(out)


def serialize_quiz_block(challenge: dict[str, Any]) -> str:
    """Serialize a challenge dict to @quiz … @/quiz markdown."""
    c = _normalize_challenge(challenge)
    lines = ["@quiz"]
    items = c.get("items") or []
    if items:
        lines.append("items:")
        for item in items:
            ni = _normalize_challenge(item)
            lines.append(f"  - concept: {ni.get('core_concept') or ''}".rstrip())
            if ni.get("short_definition"):
                lines.append(
                    f"    definition: {render_inline_cloze(ni['short_definition'], ni.get('cloze_indices') or [])}"
                )
            if ni.get("main_question"):
                lines.append(f"    question: {ni['main_question']}")
            if ni.get("correct_answer"):
                lines.append(f"    answer: {ni['correct_answer']}")
            playable = playable_modes(ni)
            if playable and len(playable) < len(ALL_QUIZ_MODES):
                lines.append(f"    modes: {','.join(playable)}")
            traps = ni.get("traps") or []
            if traps:
                lines.append("    traps:")
                for t in traps:
                    lines.append(f"    - {t}")
            steps = ni.get("steps") or []
            if steps:
                lines.append("    steps:")
                for s in steps:
                    lines.append(f"    - {s}")
            if ni.get("skip_multiple"):
                lines.append("    skip_multiple: yes")
            if ni.get("skip_ordering"):
                lines.append("    skip_ordering: yes")
        lines.append("@/quiz")
        return "\n".join(lines)

    if c.get("core_concept"):
        lines.append(f"concept: {c['core_concept']}")
    if c.get("short_definition"):
        lines.append(
            f"definition: {render_inline_cloze(c['short_definition'], c.get('cloze_indices') or [])}"
        )
    if c.get("main_question"):
        lines.append(f"question: {c['main_question']}")
    if c.get("correct_answer"):
        lines.append(f"answer: {c['correct_answer']}")
    playable = playable_modes(c)
    if playable and len(playable) < len(ALL_QUIZ_MODES):
        lines.append(f"modes: {','.join(playable)}")
    traps = c.get("traps") or []
    if traps:
        lines.append("traps:")
        for t in traps:
            lines.append(f"- {t}")
    steps = c.get("steps") or []
    if steps:
        lines.append("steps:")
        for s in steps:
            lines.append(f"- {s}")
    if c.get("skip_multiple"):
        lines.append("skip_multiple: yes")
    if c.get("skip_ordering"):
        lines.append("skip_ordering: yes")
    lines.append("@/quiz")
    return "\n".join(lines)


def challenge_for_play(challenge: dict[str, Any]) -> dict[str, Any]:
    c = _normalize_challenge(challenge)
    answer = str(c.get("correct_answer") or "").strip()
    definition = str(c.get("short_definition") or "").strip()
    concept = str(c.get("core_concept") or "").strip()
    if not answer and definition and concept:
        merged = dict(c)
        merged["correct_answer"] = definition
        return _normalize_challenge(merged)
    return c


def is_challenge_complete(challenge: dict[str, Any]) -> bool:
    c = _normalize_challenge(challenge)
    items = c.get("items") or []
    if items:
        return all(is_challenge_complete(item) for item in items)
    return len(playable_modes(challenge_for_play(c))) > 0


_ORDER_PREFIX = re.compile(r"^\s*(\d+)\s*-\s*(.+?)\s*$")
_INFO_OPEN_RE = re.compile(r"^@info\s*$")
_INFO_CLOSE_RE = re.compile(r"^@/info\s*$")
_INFO_KEYS = {"title", "icon", "description", "exam", "discussion", "tags", "certifiable"}
_FLAG_KEYS = {"exam", "certifiable"}
_INFO_TRUTHY = {"yes", "true", "on", "1"}


def _strip_order_prefix(name: str) -> tuple[int | None, str]:
    m = _ORDER_PREFIX.match(name or "")
    if m:
        return int(m.group(1)), m.group(2).strip()
    return None, (name or "").strip()


def _slugify(s: str) -> str:
    """Match Arborito archive slugify (NFKD, strip accents, kebab)."""
    t = unicodedata.normalize("NFKD", s or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")
    return t or "node"


def _parse_info_line(line: str) -> tuple[str, Any] | None:
    """Parse a `key: value` line inside an `@info` block."""
    s = line.strip()
    if not s:
        return None
    colon = s.find(":")
    if colon < 0:
        return None
    key = s[:colon].strip().lower()
    raw = s[colon + 1 :].strip()
    if key not in _INFO_KEYS:
        return None
    if key == "tags":
        return key, [t.strip() for t in raw.split(",") if t.strip()]
    if key in _FLAG_KEYS:
        return key, raw.lower() in _INFO_TRUTHY
    return key, raw


def _parse_leaf_header(text: str) -> dict[str, Any]:
    """Parse the optional leading `@info … @/info` block of a leaf .md and
    return the recognised properties as a dict. The block must come first
    (only blank lines may precede it). When the block is absent, an empty
    dict is returned and the whole file is body content."""
    meta: dict[str, Any] = {}
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines) or not _INFO_OPEN_RE.match(lines[i].strip()):
        return meta
    i += 1
    while i < len(lines) and not _INFO_CLOSE_RE.match(lines[i].strip()):
        pair = _parse_info_line(lines[i])
        if pair is not None:
            meta[pair[0]] = pair[1]
        i += 1
    return meta


def _parse_module_readme(text: str) -> tuple[dict[str, Any], str]:
    """Parse optional module README.md — leading @info block + markdown body."""
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    meta: dict[str, Any] = {}
    if i < len(lines) and _INFO_OPEN_RE.match(lines[i].strip()):
        i += 1
        while i < len(lines) and not _INFO_CLOSE_RE.match(lines[i].strip()):
            pair = _parse_info_line(lines[i])
            if pair is not None:
                meta[pair[0]] = pair[1]
            i += 1
        if i < len(lines):
            i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    body = "\n".join(lines[i:]).strip()
    return meta, body


def load_arborito_archive(path: Any) -> dict[str, Any]:
    """Load a `.arborito` ZIP into the same in-memory shape the GUI uses.

    The archive's folder structure IS the tree: ``manifest.json`` holds
    course-level metadata (``titles`` / ``descriptions`` per curriculum
    language, icon, primary ``language``) and the hierarchy is reconstructed
    by walking ``lessons/<LANG>/<NN folder>/…/<NN leaf>.md`` (folders may nest
    to any depth). Lesson titles come from the ``NN - Name`` prefix in
    folder/file names; ``@info`` with ``title:`` only when the name cannot
    carry the full title (e.g. colons). Optional ``README.md`` in a module
    folder, or ``files/README.md`` for the course. Bilingual courses use
    parallel ``lessons/ES/`` and ``lessons/EN/`` trees — same position links
    translations.
    The returned dict has the standard shape ``{ format, meta, tree, files? }``
    with each leaf carrying its body in ``content``.
    """
    import json as _json
    import zipfile as _zipfile
    from pathlib import Path as _Path

    p = _Path(path)
    if p.read_bytes()[:4] != b"PK\x03\x04":
        raise ValueError(f"Not a valid .arborito archive (expected ZIP): {p}")

    with _zipfile.ZipFile(p) as zf:
        manifest = _json.loads(zf.read("manifest.json").decode("utf-8"))
        if manifest.get("format") != "arborito":
            raise ValueError(f'Archive manifest has wrong format in {p} (expected format: "arborito")')
        meta = manifest.get("meta") or {}
        if not isinstance(meta, dict):
            raise ValueError(f"Archive manifest missing meta in {p}")

        entries: dict[str, bytes] = {}
        files: dict[str, str] = {}
        for info in zf.infolist():
            if info.is_dir():
                continue
            if info.filename.startswith("files/"):
                files[info.filename[len("files/"):]] = zf.read(info.filename).decode("utf-8")
            elif info.filename != "manifest.json":
                entries[info.filename] = zf.read(info.filename)

        languages = _reconstruct_languages(entries, meta)
        titles = _titles_map(meta)
        fallback_lang = next(iter(languages.keys()), None) or next(iter(titles.keys()), "")
        universe_name = _title_for_lang(titles, fallback_lang) or next(iter(titles.values()), "") or ""

        result: dict[str, Any] = {
            "format": "arborito",
            "meta": meta,
            "tree": {
                "generatedAt": meta.get("exportedAt", ""),
                "universeId": meta.get("id", "") or "tree",
                "universeName": universe_name,
                "languages": languages,
            },
        }
        if files:
            result["files"] = files
        return result


def _titles_map(meta: dict[str, Any]) -> dict[str, str]:
    raw = meta.get("titles")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        code = str(k or "").strip().upper()
        title = str(v or "").strip()
        if code and title:
            out[code] = title
    return out


def _descriptions_map(meta: dict[str, Any]) -> dict[str, str]:
    raw = meta.get("descriptions")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        code = str(k or "").strip().upper()
        text = str(v or "").strip()
        if code and text:
            out[code] = text
    return out


def _title_for_lang(titles: dict[str, str], lang: str | None) -> str:
    code = str(lang or "").strip().upper()
    if code and titles.get(code):
        return titles[code]
    if titles:
        return next(iter(titles.values()))
    return ""


def _natural_key(s: str) -> tuple[int, str]:
    """Sort by leading numeric prefix first, then case-folded name."""
    m = _ORDER_PREFIX.match(s)
    if m:
        return (int(m.group(1)), m.group(2).casefold())
    return (10**9, (s or "").casefold())


def _reconstruct_languages(
    entries: dict[str, bytes], course_meta: dict[str, Any]
) -> dict[str, Any]:
    """Group ``lessons/<LANG>/...`` entries by language and build each tree."""
    by_lang: dict[str, dict[str, bytes]] = {}
    for path, data in entries.items():
        if not path.startswith("lessons/"):
            continue
        rest = path[len("lessons/"):]
        slash = rest.find("/")
        if slash < 0:
            continue
        lang = rest[:slash]
        relative = rest[slash + 1 :]
        by_lang.setdefault(lang, {})[relative] = data

    out: dict[str, Any] = {}
    for lang, lang_entries in by_lang.items():
        out[lang] = _build_lang_root(lang, lang_entries, course_meta)
    return out


def _build_lang_root(
    lang: str, lang_entries: dict[str, bytes], course_meta: dict[str, Any]
) -> dict[str, Any]:
    universe_id = course_meta.get("id") or "tree"
    titles = _titles_map(course_meta)
    descriptions = _descriptions_map(course_meta)
    lang_key = str(lang or "").strip().upper()
    course_name = _title_for_lang(titles, lang_key) or lang_key or lang
    course_icon = course_meta.get("icon") or "🌳"
    course_description = ""
    if lang_key and descriptions.get(lang_key):
        course_description = descriptions[lang_key]
    elif descriptions:
        course_description = next(iter(descriptions.values()))

    root_meta: dict[str, Any] = {}
    root_md = lang_entries.get("_root.md")
    if root_md:
        root_meta = _parse_leaf_header(root_md.decode("utf-8"))

    root_name = root_meta.get("title") or course_name
    root_id = f"{universe_id}-{lang.lower()}-root"

    children = _collect_children(
        relative_prefix="",
        lang_entries=lang_entries,
        lang=lang,
        parent_id=root_id,
        parent_path=root_name,
    )

    return {
        "id": root_id,
        "name": root_name,
        "type": "root",
        "expanded": True,
        "icon": root_meta.get("icon") or course_icon,
        "description": root_meta.get("description") or course_description,
        "path": root_name,
        "children": children,
    }

def _collect_children(
    *,
    relative_prefix: str,
    lang_entries: dict[str, bytes],
    lang: str,
    parent_id: str,
    parent_path: str,
) -> list[dict[str, Any]]:
    direct: dict[str, dict[str, Any]] = {}
    for rel, _ in lang_entries.items():
        if relative_prefix and not rel.startswith(relative_prefix):
            continue
        tail = rel[len(relative_prefix):]
        if not tail:
            continue
        slash = tail.find("/")
        if slash < 0:
            if tail.lower() == "readme.md" or not tail.lower().endswith(".md"):
                continue
            direct.setdefault(tail, {"kind": "file", "name": tail})
        else:
            dir_name = tail[:slash]
            if dir_name.startswith("_"):
                continue
            direct.setdefault(dir_name, {"kind": "dir", "name": dir_name})

    sorted_children = sorted(direct.values(), key=lambda c: _natural_key(c["name"]))
    out: list[dict[str, Any]] = []
    for child in sorted_children:
        if child["kind"] == "dir":
            out.append(
                _build_branch(
                    relative_prefix=f"{relative_prefix}{child['name']}/",
                    lang_entries=lang_entries,
                    lang=lang,
                    parent_id=parent_id,
                    parent_path=parent_path,
                )
            )
        else:
            out.append(
                _build_leaf(
                    relative_path=f"{relative_prefix}{child['name']}",
                    lang_entries=lang_entries,
                    lang=lang,
                    parent_id=parent_id,
                    parent_path=parent_path,
                )
            )
    return out


def _build_branch(
    *,
    relative_prefix: str,
    lang_entries: dict[str, bytes],
    lang: str,
    parent_id: str,
    parent_path: str,
) -> dict[str, Any]:
    folder = relative_prefix.rstrip("/").rsplit("/", 1)[-1]
    order, fallback_name = _strip_order_prefix(folder)
    branch_meta_bytes = lang_entries.get(f"{relative_prefix}README.md")
    readme_raw = branch_meta_bytes.decode("utf-8") if branch_meta_bytes else ""
    branch_meta, readme_body = _parse_module_readme(readme_raw) if readme_raw else ({}, "")
    name = fallback_name
    branch_id = f"branch-{_slugify(f'{lang}/{relative_prefix}')}"
    branch_path = f"{parent_path} / {name}"

    children = _collect_children(
        relative_prefix=relative_prefix,
        lang_entries=lang_entries,
        lang=lang,
        parent_id=branch_id,
        parent_path=branch_path,
    )

    branch = {
        "id": branch_id,
        "parentId": parent_id,
        "name": name,
        "type": "branch",
        "icon": branch_meta.get("icon") or "📁",
        "path": branch_path,
        "order": str(order) if order is not None else "",
        "description": branch_meta.get("description") or readme_body,
        "expanded": True,
        "children": children,
    }
    if readme_raw:
        branch["content"] = readme_raw
    if "certifiable" in branch_meta:
        branch["isCertifiable"] = bool(branch_meta["certifiable"])
    return branch


def _build_leaf(
    *,
    relative_path: str,
    lang_entries: dict[str, bytes],
    lang: str,
    parent_id: str,
    parent_path: str,
) -> dict[str, Any]:
    raw = lang_entries[relative_path].decode("utf-8")
    file_name = relative_path.rsplit("/", 1)[-1]
    if file_name.lower().endswith(".md"):
        file_name = file_name[:-3]
    order, fallback_name = _strip_order_prefix(file_name)
    meta = _parse_leaf_header(raw)
    name = meta.get("title") or fallback_name
    leaf_type = "exam" if meta.get("exam") else "leaf"
    # Match Arborito: leaf-{slugify(`${lang}/${fullZipPath}`)}
    full_path = f"lessons/{lang}/{relative_path}"

    return {
        "id": f"leaf-{_slugify(f'{lang}/{full_path}')}",
        "parentId": parent_id,
        "name": name,
        "type": leaf_type,
        "icon": meta.get("icon") or ("📝" if leaf_type == "exam" else "📄"),
        "path": f"{parent_path} / {name}",
        "order": str(order) if order is not None else "",
        "description": meta.get("description") or "",
        "content": raw,
        "archive_entry": full_path,
    }


def expand_challenge(challenge: dict[str, Any], base_id: str = "quiz") -> list[dict[str, Any]]:
    c = _normalize_challenge(challenge)
    items = c.get("items") or []
    if items:
        out: list[dict[str, Any]] = []
        for i, item in enumerate(items):
            ni = _normalize_challenge(item)
            ni["id"] = f"{base_id}:{i}"
            out.append(ni)
        return out
    c["id"] = base_id
    return [c]


def parse_all_challenges_from_content(content: str) -> list[dict[str, Any]]:
    """Scan markdown for every complete @quiz block (items expanded).

    A trailing ``@quiz`` without ``@/quiz`` is treated as closed at EOF (common
    authoring slip). A second ``@quiz`` before a closer still skips the opener.
    """
    if not content:
        return []
    lines = content.splitlines()
    out: list[dict[str, Any]] = []
    block_ord = 0
    i = 0
    while i < len(lines):
        if not _QUIZ_OPEN.match(lines[i].strip()):
            i += 1
            continue
        close = -1
        aborted_by_open = False
        for j in range(i + 1, len(lines)):
            if _QUIZ_CLOSE.match(lines[j].strip()):
                close = j
                break
            if _QUIZ_OPEN.match(lines[j].strip()):
                aborted_by_open = True
                break
        if close == -1:
            if aborted_by_open:
                i += 1
                continue
            close = len(lines)
        challenge = parse_quiz_block(lines[i + 1 : close])
        block_ord += 1
        for expanded in expand_challenge(challenge, f"quiz-{block_ord}"):
            if is_challenge_complete(expanded):
                out.append(expanded)
        i = close + 1 if close < len(lines) else len(lines)
    return out


def clean_lesson_text(content: str) -> str:
    """Strip @quiz / @info fences, single-line @-tags and HTML, then collapse whitespace."""
    text = content or ""
    text = re.sub(
        r"^@quiz\s*\n.*?^@/quiz\s*$\n?",
        "",
        text,
        flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    # Trailing unclosed @quiz (EOF)
    text = re.sub(
        r"^@quiz\s*\n.*\Z",
        "",
        text,
        flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    text = re.sub(
        r"^@info\s*\n.*?^@/info\s*$\n?",
        "",
        text,
        flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"@\w+:.*?\n", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def get_challenges_from_lesson(lesson: dict[str, Any]) -> list[dict[str, Any]]:
    if not lesson:
        return []
    raw: list[dict[str, Any]] = []
    if lesson.get("challenges"):
        raw = list(lesson["challenges"])
    elif lesson.get("challenge"):
        raw = [lesson["challenge"]]
    elif lesson.get("raw") or lesson.get("content"):
        return parse_all_challenges_from_content(str(lesson.get("raw") or lesson.get("content") or ""))
    out: list[dict[str, Any]] = []
    for i, ch in enumerate(raw):
        base = str(ch.get("id") or f"quiz-{i + 1}")
        out.extend(expand_challenge(ch, base))
    return out


def _is_junk_option_label(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    return t in {
        ":",
        ": ",
        "—",
        "-",
        "–",
        "…",
        "...",
        "___",
        "______",
        "N/A",
        "Unknown",
    }


def pick_static_wrong(challenge: dict[str, Any]) -> str:
    ca = str(challenge.get("correct_answer") or "").strip()
    sd = str(challenge.get("short_definition") or "").strip()
    effective = (ca or sd).lower()
    for trap in challenge.get("traps") or []:
        t = str(trap or "").strip()
        if t and not _is_junk_option_label(t) and t.lower() != effective:
            return t
    if sd and sd != ca and sd.lower() != effective:
        return sd
    return ""


def static_quiz_from_challenge(
    challenge: dict[str, Any],
    title: str,
    count: int,
    lang: str = "ES",
) -> list[dict[str, str]]:
    c = challenge_for_play(challenge)
    lang_key = lang.upper() if lang.upper() in _PROMPTS else "EN"
    prompts = _PROMPTS[lang_key]
    items: list[dict[str, str]] = []
    if c.get("main_question") and c.get("correct_answer"):
        items.append(
            {
                "topic": str(c.get("core_concept") or title or "Topic")[:40],
                "q": str(c["main_question"]),
                "correct": str(c["correct_answer"]),
                "wrong": pick_static_wrong(c),
                "traps": [str(t) for t in (c.get("traps") or []) if str(t or "").strip()],
            }
        )
    elif c.get("core_concept") and (c.get("short_definition") or c.get("correct_answer")):
        concept = str(c["core_concept"])
        items.append(
            {
                "topic": concept,
                "q": prompts["recall"](concept),
                "correct": str(c.get("correct_answer") or c.get("short_definition")),
                "wrong": pick_static_wrong(c),
                "traps": [str(t) for t in (c.get("traps") or []) if str(t or "").strip()],
            }
        )
    return items[: max(1, count)]


def _fill_wrongs_from_answer_pool(
    items: list[dict[str, str]],
    answer_pool: list[str],
) -> list[dict[str, str]]:
    """Attach a sibling wrong answer from the lesson pool (works even when count=1)."""
    pool = [
        a
        for a in (answer_pool or [])
        if str(a or "").strip() and not _is_junk_option_label(str(a or ""))
    ]
    for it in items:
        wrong = str(it.get("wrong") or "").strip()
        if wrong and not _is_junk_option_label(wrong):
            continue
        self = str(it.get("correct") or "").strip().lower()
        it["wrong"] = next((c for c in pool if c.lower() != self), "")
    return items


def _fill_sibling_wrongs(items: list[dict[str, str]]) -> list[dict[str, str]]:
    corrects = [
        str(it.get("correct") or "").strip()
        for it in items
        if str(it.get("correct") or "").strip() and not _is_junk_option_label(str(it.get("correct") or ""))
    ]
    return _fill_wrongs_from_answer_pool(items, corrects)


def static_quiz_from_lesson(lesson: dict[str, Any], count: int = 3, lang: str = "ES") -> list[dict[str, str]]:
    n = max(1, count)
    title = str(lesson.get("title") or "")
    lesson_lang = str(lesson.get("lang") or lang or "ES")
    challenges = list(get_challenges_from_lesson(lesson))
    answer_pool = lesson_answer_pool(challenges)
    # Shuffle so count=1 does not always pick the first flashcard.
    shuffled = list(challenges)
    random.shuffle(shuffled)
    items: list[dict[str, str]] = []
    for c in shuffled:
        batch = static_quiz_from_challenge(c, title, n - len(items), lesson_lang)
        items.extend(batch)
        if len(items) >= n:
            break
    return _fill_wrongs_from_answer_pool(items[:n], answer_pool)


def quiz_item_key(item: dict[str, Any] | None) -> str:
    if not item:
        return ""
    lesson_id = str(item.get("lessonId") or item.get("topic") or "")
    q = str(item.get("q") or item.get("complaint") or "")
    return f"{lesson_id}::{q}".strip().lower()


def build_quiz_options(
    item: dict[str, Any],
    count: int = 4,
    *,
    lang: str = "EN",
    distractor_pool: list[str] | None = None,
) -> list[str]:
    """Multiple-choice options: always includes the correct answer when present."""
    option_count = max(2, min(int(count or 4), 6))
    max_wrong = max(1, option_count - 1)
    lang_key = "ES" if str(lang or "EN").upper() == "ES" else "EN"
    correct = str(item.get("correct") or "").strip()
    seen: set[str] = {correct.lower()} if correct else set()
    raw: list[Any] = [item.get("wrong")]
    raw.extend(item.get("options") or [])
    raw.extend(item.get("traps") or [])
    if distractor_pool:
        raw.extend(distractor_pool)
    wrongs: list[str] = []
    for opt in raw:
        label = str(opt or "").strip()
        if _is_junk_option_label(label):
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        wrongs.append(label)
    pad_n = 1
    while len(wrongs) < max_wrong and pad_n <= 12:
        label = f"Incorrecto {pad_n}" if lang_key == "ES" else f"Wrong {pad_n}"
        pad_n += 1
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        wrongs.append(label)
    random.shuffle(wrongs)
    wrongs = wrongs[:max_wrong]
    if not correct:
        return wrongs[:option_count]
    out = [correct, *wrongs]
    random.shuffle(out)
    return out


def normalize_quiz_pool_item(item: dict[str, Any], lesson: dict[str, Any] | None) -> dict[str, Any]:
    challenge = (lesson or {}).get("challenge") or {}
    traps = list(item.get("traps") or challenge.get("traps") or [])
    return {
        "topic": item.get("topic") or (lesson or {}).get("title") or "?",
        "q": item.get("q"),
        "correct": item.get("correct"),
        "wrong": item.get("wrong"),
        "traps": traps,
        "options": traps,
        "lessonId": (lesson or {}).get("id"),
    }


def quiz_pool_from_curriculum(
    arborito: Any,
    *,
    count: int = 6,
    unique_lessons: bool = True,
    unique_questions: bool = True,
    max_attempts: int | None = None,
) -> list[dict[str, Any]]:
    """Walk lesson.next(), build a deduped quiz pool from the curriculum."""
    round_count = max(1, int(count))
    attempts = max_attempts if max_attempts and max_attempts >= round_count else max(round_count * 4, 36)
    pool: list[dict[str, Any]] = []
    seen_lessons: set[str] = set()
    seen_questions: set[str] = set()
    for _ in range(attempts):
        if len(pool) >= round_count:
            break
        lesson = arborito.lesson.next()
        if not lesson:
            break
        lid = str(lesson.get("id") or "")
        if unique_lessons and lid in seen_lessons:
            continue
        if unique_lessons:
            seen_lessons.add(lid)
        try:
            batch = arborito.quiz(lesson, {"count": 1})
        except Exception:
            continue
        if not batch or not batch[0]:
            continue
        enriched = normalize_quiz_pool_item(batch[0], lesson)
        if unique_questions:
            q_key = quiz_item_key(enriched)
            if q_key in seen_questions:
                continue
            seen_questions.add(q_key)
        pool.append(enriched)
    return pool


def pick_unused_quiz(
    pool: list[dict[str, Any]],
    session: set[str] | dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Pick from pool without repeating until exhausted (then resets)."""
    if not pool:
        return None
    used: set[str]
    if isinstance(session, set):
        used = session
    elif isinstance(session, dict):
        raw = session.get("used")
        if isinstance(raw, set):
            used = raw
        else:
            used = set()
            session["used"] = used
    else:
        used = set()
    fresh = [item for item in pool if quiz_item_key(item) not in used]
    source = fresh if fresh else pool
    if not fresh:
        used.clear()
    pick = random.choice(source)
    used.add(quiz_item_key(pick))
    return pick


def static_match_pairs_from_challenge(challenge: dict[str, Any], max_pairs: int) -> list[dict[str, str]]:
    concept = str(challenge.get("core_concept") or "").strip()
    defn = str(challenge.get("short_definition") or "").strip()
    correct = str(challenge.get("correct_answer") or "").strip()
    topic_def = defn or correct
    out: list[dict[str, str]] = []
    if concept and topic_def:
        out.append({"t": concept[:48], "d": topic_def[:72]})
    steps = challenge.get("steps") or []
    for i in range(len(steps) - 1):
        out.append({"t": str(steps[i])[:48], "d": str(steps[i + 1])[:72]})
    if defn and challenge.get("cloze_indices"):
        words = defn.split()
        for idx in challenge["cloze_indices"]:
            if isinstance(idx, int) and 0 <= idx < len(words) and concept:
                w = words[idx]
                if w:
                    out.append({"t": w[:48], "d": concept[:72]})
    return out[: max(1, min(max_pairs, 8))]


def static_match_pairs_from_lessons(lessons: list[dict[str, Any]], count: int) -> list[dict[str, str]]:
    n = max(1, min(count, 8))
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for lesson in lessons:
        for c in get_challenges_from_lesson(lesson):
            for pair in static_match_pairs_from_challenge(c, n):
                kt = pair["t"].lower()
                kd = pair["d"].lower()
                if kt in seen or kd in seen or kt == kd:
                    continue
                seen.add(kt)
                seen.add(kd)
                out.append(pair)
                if len(out) >= n:
                    return out
    return out


# ---------------------------------------------------------------------------
# Quiz V2 modalities — multiple / recall / cloze / chips / steps
# ---------------------------------------------------------------------------
#
# Five student-facing modalities share the same Quiz V2 challenge. The helpers
# below detect which ones are playable, pick one deterministically, and build a
# UI-neutral card the caller can render. Equivalent to the JS helpers in
# `arborito/src/features/learning/quiz-v2-schema.js`.


def tokenize_quiz_answer_chips(text: str) -> list[str]:
    s = str(text or "").replace("\u00a0", " ").strip()
    if not s:
        return []
    tokens: list[str] = []
    i = 0
    while i < len(s):
        while i < len(s) and s[i].isspace():
            i += 1
        if i >= len(s):
            break
        if s[i] == "(":
            depth = 0
            j = i
            while j < len(s):
                if s[j] == "(":
                    depth += 1
                elif s[j] == ")":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            chunk = s[i:j].strip()
            if chunk:
                tokens.append(chunk)
            i = j
            continue
        j = i
        while j < len(s) and not s[j].isspace():
            j += 1
        chunk = s[i:j].strip()
        if chunk:
            tokens.append(chunk)
        i = j
    return tokens


def _normalize_challenge(raw: dict[str, Any] | None) -> dict[str, Any]:
    c = new_challenge()
    if not raw or not isinstance(raw, dict):
        return c
    c["core_concept"] = str(raw.get("core_concept") or "").strip()
    c["short_definition"] = str(raw.get("short_definition") or "").strip()
    c["main_question"] = str(raw.get("main_question") or "").strip()
    c["correct_answer"] = str(raw.get("correct_answer") or "").strip()
    c["traps"] = [
        str(t or "").strip() for t in (raw.get("traps") or []) if str(t or "").strip()
    ]
    c["cloze_indices"] = []
    for n in raw.get("cloze_indices") or []:
        try:
            c["cloze_indices"].append(int(n))
        except (TypeError, ValueError):
            continue
    c["answer_mode"] = "steps" if raw.get("answer_mode") == "steps" else "chips"
    c["steps"] = [
        str(s or "").strip() for s in (raw.get("steps") or []) if str(s or "").strip()
    ]
    c["skip_multiple"] = bool(raw.get("skip_multiple"))
    c["skip_ordering"] = bool(raw.get("skip_ordering"))
    modes = raw.get("modes")
    if isinstance(modes, list) and modes:
        c["modes"] = [m for m in modes if m in ALL_QUIZ_MODES]
    else:
        c["modes"] = list(ALL_QUIZ_MODES)
    if isinstance(raw.get("items"), list) and raw["items"]:
        c["items"] = [_normalize_challenge(item) for item in raw["items"]]
    if raw.get("id"):
        c["id"] = str(raw["id"])
    return c


def mode_is_playable(challenge: dict[str, Any], mode: str) -> bool:
    c = challenge_for_play(challenge)
    if mode == QUIZ_MODE_CLOZE:
        return bool(
            c["short_definition"]
            and c["cloze_indices"]
            and not str(c.get("main_question") or "").strip()
        )
    if mode == QUIZ_MODE_MULTIPLE:
        if not (c["main_question"] and c["correct_answer"] and c["traps"] and not c["skip_multiple"]):
            return False
        usable = [
            t
            for t in c["traps"]
            if str(t or "").strip()
            and not _is_junk_option_label(str(t or ""))
            and str(t).strip().lower() != str(c["correct_answer"]).strip().lower()
        ]
        return bool(usable)
    if mode == QUIZ_MODE_RECALL:
        return bool(c["core_concept"] and c["correct_answer"])
    if mode == QUIZ_MODE_CHIPS:
        wc = len(tokenize_quiz_answer_chips(str(c.get("correct_answer") or "")))
        return bool(2 <= wc <= 6)
    if mode == QUIZ_MODE_STEPS:
        return bool(len(c["steps"]) >= 2 and not c["skip_ordering"])
    return False


def playable_modes(challenge: dict[str, Any]) -> list[str]:
    c = challenge_for_play(challenge)
    derived = [m for m in ALL_QUIZ_MODES if mode_is_playable(c, m)]
    authored = c.get("modes") or []
    if authored:
        return [m for m in derived if m in authored]
    return derived


def _stable_hash(s: str) -> int:
    h = 0
    for ch in s:
        h = (h * 31 + ord(ch)) & 0x7FFFFFFF
    return h


def pick_study_mode(challenge: dict[str, Any], block_id: str, salt: str = "") -> str:
    c = _normalize_challenge(challenge)
    playable = playable_modes(c)
    if not playable:
        return QUIZ_MODE_MULTIPLE
    authored = c.get("modes") or []
    if 0 < len(authored) < len(ALL_QUIZ_MODES) and len(authored) == 1 and authored[0] in playable:
        return authored[0]
    attempt = 0
    try:
        attempt = int(salt) if str(salt).strip().isdigit() else 0
    except (TypeError, ValueError):
        attempt = 0
    return playable[_stable_hash(f"{block_id}:study:{attempt}") % len(playable)]


_PROMPTS = {
    "ES": {
        "recall": lambda concept: f"¿Qué es «{concept}»?",
        "chips": lambda concept: f"Ordena las palabras para «{concept}».",
        "steps": lambda _concept: "Ordena los pasos correctamente.",
    },
    "EN": {
        "recall": lambda concept: f"What is «{concept}»?",
        "chips": lambda concept: f"Order the words for «{concept}».",
        "steps": lambda _concept: "Order the steps correctly.",
    },
}

_MODE_LABELS = {
    "ES": {
        "multiple": "Opción múltiple",
        "recall": "Recuerda",
        "cloze": "Hueco",
        "chips": "Ordena palabras",
        "steps": "Ordena pasos",
    },
    "EN": {
        "multiple": "Multiple choice",
        "recall": "Recall",
        "cloze": "Fill blank",
        "chips": "Word order",
        "steps": "Step order",
    },
}


def mode_label(mode: str, lang: str = "ES") -> str:
    key = lang.upper() if lang.upper() in _MODE_LABELS else "EN"
    return _MODE_LABELS[key].get(str(mode or ""), str(mode or ""))


def _build_options(
    correct: str,
    wrong_pool: list[str],
    count: int,
    *,
    lang: str = "EN",
) -> list[str]:
    generic = {
        "ninguna de las anteriores",
        "todas las anteriores",
        "none of the above",
        "all of the above",
        "—",
        "-",
        ": ",
        "…",
        "...",
        "___",
        "______",
        "n/a",
        "unknown",
    }
    lang_key = "ES" if str(lang or "EN").upper() == "ES" else "EN"
    seen: set[str] = set()
    out: list[str] = []
    c = (correct or "").strip()
    if c and not _is_junk_option_label(c):
        out.append(c)
        seen.add(c.lower())
    for w in wrong_pool or []:
        t = (w or "").strip()
        if not t or t.lower() in generic or _is_junk_option_label(t) or len(out) >= count:
            continue
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    pad_n = 1
    while len(out) < min(2, count) and c and pad_n <= 12:
        label = f"Incorrecto {pad_n}" if lang_key == "ES" else f"Wrong {pad_n}"
        pad_n += 1
        k = label.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(label)
    random.shuffle(out)
    return out


def _build_cloze_view(c: dict[str, Any]) -> dict[str, Any]:
    words = (c.get("short_definition") or "").split()
    idxs = c.get("cloze_indices") or []
    blank_set = {i for i in idxs if isinstance(i, int) and 0 <= i < len(words)}
    blank_idx = idxs[0] if idxs else -1
    blank_word = (
        words[blank_idx] if 0 <= blank_idx < len(words) else str(c.get("correct_answer") or "")
    )
    display = " ".join("______" if i in blank_set else w for i, w in enumerate(words))
    return {"display": display, "blank_word": blank_word}


def _distractor_words_except(text: str, exclude: str, limit: int = 3) -> list[str]:
    ex = (exclude or "").lower()
    out: list[str] = []
    for w in (text or "").split():
        clean = re.sub(r"[.,;:!?]+$", "", w)
        if clean and clean.lower() != ex and len(clean) > 1:
            out.append(clean)
        if len(out) >= limit:
            break
    return out


def _question_with_main_prompt(main_question: str, body: str) -> str:
    mq = (main_question or "").strip()
    body_text = (body or "").strip()
    if not mq:
        return body_text
    if not body_text or body_text == mq:
        return mq
    return f"{mq}\n\n{body_text}"


def _ordering_question(main_question: str, kind: str, lang: str, concept: str) -> str:
    mq = (main_question or "").strip()
    lang_key = lang.upper() if lang.upper() in _PROMPTS else "EN"
    prompts = _PROMPTS[lang_key]
    if not mq:
        return prompts[kind](concept)
    if kind == "chips":
        if lang_key == "EN":
            return f"Order the words to answer: {mq}"
        return f"Ordena las palabras para responder: {mq}"
    if lang_key == "EN":
        return f"Order the steps to answer: {mq}"
    return f"Ordena los pasos para responder: {mq}"

def build_mode_card(
    challenge: dict[str, Any],
    mode: str,
    *,
    lesson_title: str = "",
    lang: str = "ES",
    option_count: int = 4,
    distractor_pool: list[str] | None = None,
) -> Optional[dict[str, Any]]:
    """Build a UI-neutral card for one Quiz V2 modality.

    Returns None when ``mode`` is not playable on ``challenge``.
    """
    c = challenge_for_play(challenge)
    if not mode_is_playable(c, mode):
        return None
    lang_key = lang.upper() if lang.upper() in _PROMPTS else "EN"
    prompts = _PROMPTS[lang_key]
    option_count = max(2, min(option_count, 6))
    concept = c["core_concept"] or lesson_title or "Concept"
    extra = [str(x).strip() for x in (distractor_pool or []) if str(x or "").strip()]

    if mode == QUIZ_MODE_MULTIPLE:
        wrong = list(c["traps"])
        if c["short_definition"] and c["short_definition"] != c["correct_answer"]:
            wrong.append(c["short_definition"])
        wrong.extend(extra)
        return {
            "mode": mode,
            "concept": concept,
            "question": c["main_question"],
            "correct": c["correct_answer"],
            "options": _build_options(c["correct_answer"], wrong, option_count, lang=lang_key),
        }
    if mode == QUIZ_MODE_RECALL:
        wrong = list(c["traps"])
        if c["short_definition"] and c["short_definition"] != c["correct_answer"]:
            wrong.append(c["short_definition"])
        wrong.extend(extra)
        return {
            "mode": mode,
            "concept": concept,
            "question": prompts["recall"](concept),
            "correct": c["correct_answer"],
            "options": _build_options(c["correct_answer"], wrong, option_count, lang=lang_key),
        }
    if mode == QUIZ_MODE_CLOZE:
        view = _build_cloze_view(c)
        wrong = list(c["traps"])
        wrong.extend(_distractor_words_except(c["short_definition"], view["blank_word"]))
        wrong.extend(extra)
        return {
            "mode": mode,
            "concept": concept,
            "question": _question_with_main_prompt(c["main_question"], view["display"]),
            "correct": view["blank_word"],
            "options": _build_options(view["blank_word"], wrong, option_count, lang=lang_key),
            "cloze_display": view["display"],
            "blank_word": view["blank_word"],
        }
    if mode == QUIZ_MODE_CHIPS:
        words = tokenize_quiz_answer_chips(str(c.get("correct_answer") or ""))
        shuffled = list(words)
        random.shuffle(shuffled)
        return {
            "mode": mode,
            "concept": concept,
            "question": _ordering_question(c["main_question"], "chips", lang, concept),
            "correct": " ".join(words),
            "sequence": words,
            "chips": shuffled,
        }
    if mode == QUIZ_MODE_STEPS:
        steps = list(c["steps"])
        shuffled = list(steps)
        random.shuffle(shuffled)
        return {
            "mode": mode,
            "concept": concept,
            "question": _ordering_question(c["main_question"], "steps", lang, concept),
            "correct": " → ".join(steps),
            "sequence": steps,
            "chips": shuffled,
        }
    return None


def build_study_card(
    challenge: dict[str, Any],
    block_id: str,
    *,
    lesson_title: str = "",
    lang: str = "ES",
    salt: str = "",
    distractor_pool: list[str] | None = None,
) -> Optional[dict[str, Any]]:
    """Convenience: pick a playable mode then build the card in one call."""
    playable = playable_modes(challenge)
    if not playable:
        return None
    mode = pick_study_mode(challenge, block_id, salt)
    if mode not in playable:
        mode = playable[0]
    return build_mode_card(
        challenge,
        mode,
        lesson_title=lesson_title,
        lang=lang,
        distractor_pool=distractor_pool,
    )


def normalize_answer_text(s: str) -> str:
    import re

    t = str(s or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    for old, new in (
        ("\u201c", '"'),
        ("\u201d", '"'),
        ("\u00ab", '"'),
        ("\u00bb", '"'),
        ("\u2018", "'"),
        ("\u2019", "'"),
        ("\u0060", "'"),
        ("\u00b4", "'"),
    ):
        t = t.replace(old, new)
    t = re.sub(r"[.,;:!?]+$", "", t)
    return t


def _answer_levenshtein(a: str, b: str) -> int:
    """Edit distance for fuzzy quiz matching (same rules as browser SDK)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev = row[0]
        row[0] = i
        for j, cb in enumerate(b, 1):
            tmp = row[j]
            cost = 0 if ca == cb else 1
            row[j] = min(row[j] + 1, row[j - 1] + 1, prev + cost)
            prev = tmp
    return row[len(b)]


def answers_match(player: str, expected: str) -> bool:
    a = normalize_answer_text(player)
    b = normalize_answer_text(expected)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    ta = set(a.split())
    tb = set(b.split())
    if ta and tb:
        inter = len(ta & tb)
        union = len(ta | tb)
        if union and inter / union >= 0.82:
            return True
    max_len = max(len(a), len(b), 1)
    limit = max(1, int(max_len * 0.18 + 0.999))
    return _answer_levenshtein(a, b) <= limit


def matches_any_answer(player: str, expected_list: list[str]) -> tuple[bool, str]:
    for exp in expected_list or []:
        if exp and answers_match(player, exp):
            return True, str(exp)
    return False, ""


def _accept_from_card(card: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for val in [card.get("correct"), card.get("blank_word"), *(card.get("sequence") or [])]:
        s = str(val or "").strip()
        if not s:
            continue
        k = normalize_answer_text(s)
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out


def lesson_answer_pool(challenges: list[dict[str, Any]]) -> list[str]:
    """Unique correct answers from a lesson — used as MC distractors for siblings."""
    pool: list[str] = []
    seen: set[str] = set()
    for ch in challenges or []:
        play = challenge_for_play(ch)
        ans = str(play.get("correct_answer") or play.get("short_definition") or "").strip()
        if not ans or _is_junk_option_label(ans):
            continue
        key = ans.lower()
        if key in seen:
            continue
        seen.add(key)
        pool.append(ans)
    return pool


def tasks_from_lesson(
    lesson: dict[str, Any],
    *,
    lang: str = "ES",
    max_tasks: int = 10,
    modes: Optional[list[str]] = None,
    include_code_replays: bool = True,
) -> list[dict[str, Any]]:
    """Practice tasks from Quiz V2 modes (same shape as challenge.tasksFromLesson in Arcade)."""
    lang_key = lang.upper() if lang.upper() in ("EN", "ES") else "EN"
    step_lbl = "Paso {i}/{total}" if lang_key == "ES" else "Step {i}/{total}"
    tasks: list[dict[str, Any]] = []
    title = str(lesson.get("title") or "")
    challenges = get_challenges_from_lesson(lesson)
    distractor_pool = lesson_answer_pool(challenges)
    for ch in challenges:
        if not is_challenge_complete(ch):
            continue
        for mode in playable_modes(ch):
            if modes and mode not in modes:
                continue
            card = build_mode_card(
                ch,
                mode,
                lesson_title=title,
                lang=lang_key,
                distractor_pool=distractor_pool,
            )
            if not card:
                continue
            if mode == QUIZ_MODE_STEPS and len(card.get("sequence") or []) >= 2:
                seq = card["sequence"]
                for idx, step in enumerate(seq):
                    tasks.append(
                        {
                            "kind": "quiz",
                            "mode": mode,
                            "label": step_lbl.format(i=idx + 1, total=len(seq)),
                            "prompt": str(card.get("question") or "")[:56],
                            "question": str(card.get("question") or ""),
                            "accept": [step],
                            "output": step,
                            "topic": card.get("concept") or title,
                            "options": list(card.get("options") or []),
                            "chips": list(card.get("chips") or []),
                            "sequence": list(seq),
                            "stepIndex": idx,
                            "stepTotal": len(seq),
                        }
                    )
                continue
            tasks.append(
                {
                    "kind": "quiz",
                    "mode": mode,
                    "label": str(card.get("question") or "")[:72],
                    "prompt": str(card.get("question") or "")[:72],
                    "question": str(card.get("question") or ""),
                    "accept": _accept_from_card(card),
                    "output": card.get("correct") or card.get("blank_word") or "",
                    "topic": card.get("concept") or title,
                    "options": list(card.get("options") or []),
                    "chips": list(card.get("chips") or []),
                    "sequence": list(card.get("sequence") or []),
                    "clozeDisplay": card.get("cloze_display") or card.get("clozeDisplay") or "",
                }
            )
    if include_code_replays:
        # Lazy import: content.py imports quiz helpers from this module.
        from .content import code_replays_from_lesson

        seen = {normalize_answer_text(str(t.get("label") or "")) for t in tasks}
        for rep in code_replays_from_lesson(lesson):
            cmd = str(rep.get("cmd") or "")
            key = normalize_answer_text(cmd)
            if not cmd or key in seen:
                continue
            seen.add(key)
            tasks.append(
                {
                    "kind": "code",
                    "mode": "code",
                    "label": cmd,
                    "prompt": cmd,
                    "accept": [cmd],
                    "output": rep.get("output") or "",
                    "topic": cmd,
                }
            )
    return tasks[:max_tasks]

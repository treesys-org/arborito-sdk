"""Write / plant local ``.arborito`` branch archives."""

from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any, Optional

from .archive_import import analyze_arborito_import


def _default_lesson_md() -> str:
    return """# New lesson

Write the lesson content here.

@quiz
core_concept: Concept
short_definition: Short definition
main_question: Question?
correct_answer: Answer
traps:
  - Distractor
@/quiz
"""


def plant_branch(
    name: str,
    out_path: str | Path,
    *,
    lang: str = "ES",
) -> Path:
    """Create a minimal writable branch archive (like Arborito plant flow)."""
    p = Path(out_path).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    lang_key = str(lang or "ES").strip().upper() or "ES"
    title = str(name or "").strip() or "New branch"
    manifest = {
        "format": "arborito",
        "contentKind": "branch",
        "meta": {
            "titles": {lang_key: title},
            "icon": "🌳",
        },
    }
    lesson_path = f"lessons/{lang_key}/01 - Start/01 - New lesson.md"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        zf.writestr(lesson_path, _default_lesson_md())
    return p


def copy_archive(src: str | Path, dest: str | Path) -> Path:
    src_p = Path(src).resolve()
    dest_p = Path(dest).resolve()
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_p, dest_p)
    return dest_p


def export_branch_file(source_path: str | Path, dest: str | Path) -> Path:
    src = Path(source_path)
    if not src.is_file():
        raise FileNotFoundError(f"Not a file: {source_path}")
    return copy_archive(src, dest)


def branch_storage_dir() -> Path:
    from .cli_session import sdk_home

    d = sdk_home() / "branches"
    d.mkdir(parents=True, exist_ok=True)
    return d


def tree_storage_dir() -> Path:
    from .cli_session import sdk_home

    d = sdk_home() / "trees"
    d.mkdir(parents=True, exist_ok=True)
    return d


def unique_copy_path(kind: str, base_name: str) -> Path:
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in base_name).strip() or "copy"
    root = branch_storage_dir() if kind == "branch" else tree_storage_dir()
    stem = f"{safe}-{uuid.uuid4().hex[:8]}"
    return root / f"{stem}.arborito"

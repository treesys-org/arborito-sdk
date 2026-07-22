"""Shared test helpers (mini .arborito fixtures)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path


def _make_mini_arborito(path: Path) -> Path:
    manifest = {
        "format": "arborito",
        "meta": {
            "titles": {"ES": "Test Course"},
            "icon": "🧪",
        },
    }
    lesson_a = """# Lesson A

Hello from module one.

@quiz
concept: Concept A
definition: Definition A
question: What is A?
answer: Alpha
traps:
  - Beta
@/quiz
"""
    lesson_b = """---
scene_id: intro
initial_narration:
  - "Welcome."
progress_details:
  - item_id: 1
    title: "Continue"
    action: narration
    description: "The story begins."
npc: narrator
---
Scene body.
"""
    npc = """---
id: narrator
name: Narrator
---
You are the narrator.
"""
    out = path / "mini.arborito"
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("lessons/ES/01 - Module/01 - Lesson A.md", lesson_a)
        zf.writestr("lessons/ES/02 - Story/01 - intro.md", lesson_b)
        zf.writestr("lessons/ES/02 - Story/npcs/narrator.md", npc)
    return out

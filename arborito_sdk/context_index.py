"""Keyword context index for ask.with_context (offline Sage-like brief)."""

from __future__ import annotations

import re
from typing import Any, Optional

from .content import body, blocks
from .quiz_v2 import get_challenges_from_lesson
from .tree_nav import module_playlist, top_modules, walk_tree

_TOKEN = re.compile(r"[a-z0-9áéíóúüñ]{3,}", re.I)


def _tokens(text: str) -> set[str]:
    return {m.group(0).casefold() for m in _TOKEN.finditer(text or "")}


class ContextIndex:
    def __init__(self, api: Any) -> None:
        self._api = api
        self._entries: list[dict[str, Any]] = []
        self._build()

    def _build(self) -> None:
        root = getattr(self._api, "_tree_root", None)
        if not root:
            for i, meta in enumerate(self._api.lesson.list()):
                lesson = self._api.lesson.at(i)
                if lesson:
                    self._add_lesson(lesson, module_name="")
            return

        for mod in top_modules(root):
            readme = ""
            if hasattr(self._api, "module"):
                try:
                    rd = self._api.module.readme(mod)
                    readme = str(rd.get("body") or "")
                except Exception:
                    pass
            for node in module_playlist(mod):
                lesson = self._api.lesson.by_id(str(node.get("id") or ""))
                if lesson:
                    self._add_lesson(
                        lesson,
                        module_name=str(mod.get("name") or ""),
                        module_readme=readme,
                    )

        for node in walk_tree(root, type_filter={"leaf", "exam"}):
            lid = str(node.get("id") or "")
            if not any(e.get("lesson_id") == lid for e in self._entries):
                lesson = self._api.lesson.by_id(lid)
                if lesson:
                    self._add_lesson(lesson, module_name=str(node.get("path") or "").split("/")[0])

    def _add_lesson(
        self,
        lesson: dict[str, Any],
        *,
        module_name: str,
        module_readme: str = "",
    ) -> None:
        title = str(lesson.get("title") or "")
        text = body(lesson)[:1200]
        bits = [title, module_name, module_readme, text]
        for ch in get_challenges_from_lesson(lesson)[:6]:
            for k in ("core_concept", "short_definition", "main_question", "correct_answer"):
                v = str(ch.get(k) or "").strip()
                if v:
                    bits.append(v)
        for info in blocks(lesson, "info"):
            bits.append(info[:400])
        blob = "\n".join(bits)
        self._entries.append(
            {
                "lesson_id": lesson.get("id"),
                "title": title,
                "module": module_name,
                "text": blob,
                "tokens": _tokens(blob),
                "snippet": text[:280].strip(),
            }
        )

    def search(
        self,
        query: str,
        *,
        module: str = "",
        lesson_id: str = "",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        qtok = _tokens(query)
        if not qtok and not module and not lesson_id:
            return []
        scored: list[tuple[float, dict[str, Any]]] = []
        mod_fold = module.casefold() if module else ""
        for e in self._entries:
            if lesson_id and e.get("lesson_id") != lesson_id:
                continue
            if mod_fold and mod_fold not in str(e.get("module") or "").casefold():
                continue
            overlap = len(qtok & e["tokens"]) if qtok else 0
            if mod_fold and mod_fold in str(e.get("module") or "").casefold():
                overlap += 2
            if overlap > 0 or (not qtok and (mod_fold or lesson_id)):
                scored.append((float(overlap), e))
        scored.sort(key=lambda x: (-x[0], x[1].get("title") or ""))
        return [e for _, e in scored[:limit]]

    def brief_for_query(
        self,
        query: str,
        *,
        module: str = "",
        lesson_id: str = "",
    ) -> str:
        hits = self.search(query, module=module, lesson_id=lesson_id, limit=6)
        if not hits:
            return ""
        lines = ["Context brief (from course index):"]
        for i, h in enumerate(hits, 1):
            mod = h.get("module") or "course"
            lines.append(f"{i}. [{mod}] {h.get('title')}: {h.get('snippet') or ''}")
        return "\n".join(lines)


def resolve_scope(api: Any, session_focus: Optional[dict[str, str]] = None) -> dict[str, str]:
    scope: dict[str, str] = {}
    if session_focus:
        if session_focus.get("module_name"):
            scope["module"] = session_focus["module_name"]
        if session_focus.get("lesson_id"):
            scope["lesson_id"] = session_focus["lesson_id"]
    return scope

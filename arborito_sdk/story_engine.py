"""Narrative engine — lesson frontmatter scenes (visual-novel style).

No separate @story tag: Arborito uses YAML frontmatter on lessons (scene_id,
progress_details, initial_narration) and optional @info tags like `narrative` or `story`.
Arcade HTML games use @game blocks + window.arborito.challenge instead.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Optional

from .content import frontmatter, lesson_is_narrative_scene, npc_profile, progress_details
from .tree_nav import module_playlist, walk_tree


def _find_npc(api: Any, npc_id: str, module_node: dict[str, Any]) -> dict[str, Any]:
    if not npc_id:
        return {}
    for node in walk_tree(module_node):
        if str(node.get("name") or "").casefold() == str(npc_id).casefold():
            lesson = api.lesson.by_id(str(node.get("id") or ""))
            if lesson:
                return npc_profile(lesson)
        lid = str(node.get("id") or "")
        lesson = api.lesson.by_id(lid)
        if lesson:
            fm = frontmatter(lesson)
            if str(fm.get("id") or "").casefold() == str(npc_id).casefold():
                return npc_profile(lesson)
    return {"id": npc_id, "name": npc_id, "image": "", "system_prompt": ""}


def _scene_lessons(api: Any, module_node: dict[str, Any]) -> list[dict[str, Any]]:
    scenes: list[dict[str, Any]] = []
    for node in module_playlist(module_node):
        lesson = api.lesson.by_id(str(node.get("id") or ""))
        if not lesson:
            continue
        if lesson_is_narrative_scene(lesson):
            scenes.append(lesson)
    if scenes:
        return scenes
    return [
        api.lesson.by_id(str(n.get("id") or ""))
        for n in module_playlist(module_node)
        if api.lesson.by_id(str(n.get("id") or ""))
    ]


def _scene_by_id(scenes: list[dict[str, Any]], scene_id: str) -> Optional[dict[str, Any]]:
    sid = str(scene_id or "").casefold()
    for s in scenes:
        fm = frontmatter(s)
        if str(fm.get("scene_id") or s.get("id") or "").casefold() == sid:
            return s
        if str(s.get("title") or "").casefold() == sid:
            return s
    return None


class StoryEngine:
    def __init__(self, api: Any) -> None:
        self._api = api
        self._ask_npc: Optional[Callable[..., str]] = None

    def set_ask_npc(self, fn: Callable[..., str]) -> None:
        self._ask_npc = fn

    def start(
        self,
        module: str,
        *,
        player_name: str = "Player",
        player_lang: str = "es",
        learn_lang: str = "en",
    ) -> dict[str, Any]:
        mod = self._api.module.find(module)
        if not mod:
            raise ValueError(f"Module not found: {module}")
        scenes = _scene_lessons(self._api, mod)
        if not scenes:
            raise ValueError(f"No scenes in module: {module}")
        first = scenes[0]
        fm = frontmatter(first)
        scene_id = str(fm.get("scene_id") or first.get("id") or "")
        profile: dict[str, Any] = {
            "playerName": player_name,
            "playerLang": player_lang,
            "learnLang": learn_lang,
            "module": str(mod.get("name") or module),
            "module_id": mod.get("id"),
            "sceneId": scene_id,
            "sceneLessonId": first.get("id"),
            "step_index": 0,
            "flags": {},
            "inventory": [],
        }
        return self.advance(profile, player_input=None, module_node=mod, scenes=scenes)

    def advance(
        self,
        profile: dict[str, Any],
        player_input: Optional[str] = None,
        *,
        module_node: Optional[dict[str, Any]] = None,
        scenes: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        profile = deepcopy(profile)
        mod_name = profile.get("module") or ""
        if not module_node:
            module_node = self._api.module.find(str(mod_name))
        if not module_node:
            return _err_packet(profile, "Module missing from profile.")
        if scenes is None:
            scenes = _scene_lessons(self._api, module_node)

        while True:
            lesson = _scene_by_id(scenes, str(profile.get("sceneId") or ""))
            if not lesson:
                lesson = self._api.lesson.by_id(str(profile.get("sceneLessonId") or ""))
            if not lesson:
                return _err_packet(profile, "Scene not found.")

            fm = frontmatter(lesson)
            steps = progress_details(lesson)
            scene_id = str(fm.get("scene_id") or lesson.get("id") or "")
            scene_npc = fm.get("npc")
            step_index = int(profile.get("step_index") or 0)

            narration_flag = f"shown_initial_{scene_id}"
            if step_index == 0 and not profile.get("flags", {}).get(narration_flag) and not player_input:
                initial = fm.get("initial_narration")
                if initial and isinstance(initial, list):
                    profile.setdefault("flags", {})[narration_flag] = True
                    text = "\n".join(str(x) for x in initial)
                    return _packet(
                        "NARRATION",
                        {"text": text},
                        profile,
                        lesson,
                        _find_npc(self._api, str(scene_npc or ""), module_node),
                    )

            if step_index >= len(steps):
                return _packet(
                    "END_OF_SCENE",
                    {},
                    profile,
                    lesson,
                    _find_npc(self._api, str(scene_npc or ""), module_node),
                )

            step = steps[step_index]
            if step.get("children"):
                return self._handle_choice(step, profile, lesson, module_node, scene_npc, player_input)

            action = step.get("action")
            if step.get("description") and not action:
                return self._handle_dialogue(step, profile, lesson, module_node, scene_npc, player_input)

            if action == "narration":
                profile["step_index"] = step_index + 1
                text = step.get("description") or step.get("title") or ""
                return _packet(
                    "NARRATION",
                    {"text": text},
                    profile,
                    lesson,
                    _find_npc(self._api, str(scene_npc or ""), module_node),
                )

            if action == "transition_to_leaf":
                target = step.get("target")
                profile["sceneId"] = target
                profile["sceneLessonId"] = None
                profile["step_index"] = 0
                player_input = None
                continue

            if action == "set_player_flag":
                target = step.get("target")
                if target and "=" in str(target):
                    flag, val = str(target).split("=", 1)
                    profile.setdefault("flags", {})[flag.strip()] = val.strip()
                elif target:
                    profile.setdefault("flags", {})[str(target)] = True
                profile["step_index"] = step_index + 1
                player_input = None
                continue

            if action == "end_chapter":
                return _packet(
                    "END_CHAPTER",
                    {"chapter": step.get("target") or profile.get("module")},
                    profile,
                    lesson,
                    _find_npc(self._api, str(scene_npc or ""), module_node),
                )

            profile["step_index"] = step_index + 1
            player_input = None

    def _handle_choice(
        self,
        step: dict[str, Any],
        profile: dict[str, Any],
        lesson: dict[str, Any],
        module_node: dict[str, Any],
        scene_npc: Any,
        player_input: Optional[str],
    ) -> dict[str, Any]:
        children = step.get("children") or []
        if player_input:
            for opt in children:
                if str(opt.get("item_id")) == str(player_input).strip():
                    profile["step_index"] = int(profile.get("step_index") or 0) + 1
                    act = opt.get("action")
                    target = opt.get("target")
                    if act == "transition_to_leaf" and target:
                        profile["sceneId"] = target
                        profile["sceneLessonId"] = None
                        profile["step_index"] = 0
                    return self.advance(profile, player_input=None, module_node=module_node)

        choices = [{"id": str(c.get("item_id")), "text": c.get("title")} for c in children]
        return _packet(
            "CHOICE",
            {"prompt": step.get("title") or "Choose:"},
            profile,
            lesson,
            _find_npc(self._api, str(scene_npc or ""), module_node),
            choices=choices,
        )

    def _handle_dialogue(
        self,
        step: dict[str, Any],
        profile: dict[str, Any],
        lesson: dict[str, Any],
        module_node: dict[str, Any],
        scene_npc: Any,
        player_input: Optional[str],
    ) -> dict[str, Any]:
        speaker_id = step.get("speaker") or scene_npc
        npc = _find_npc(self._api, str(speaker_id or ""), module_node)
        prompt = str(step.get("description") or "...")
        prompt = (
            prompt.replace("{player_lang}", str(profile.get("playerLang") or "es"))
            .replace("{learn_lang}", str(profile.get("learnLang") or "en"))
        )
        text = prompt
        if self._ask_npc and self._api.getAIMode() == "dynamic":
            try:
                if player_input:
                    text = self._ask_npc(
                        npc, player_input, lesson, beat=prompt, mode="reply"
                    )
                else:
                    text = self._ask_npc(npc, prompt, lesson, beat=prompt, mode="adapt")
            except Exception:
                text = prompt
        profile["step_index"] = int(profile.get("step_index") or 0) + 1
        return _packet(
            "DIALOGUE",
            {"text": text},
            profile,
            lesson,
            npc,
            scene_info={"speaker_name": npc.get("name") or speaker_id or "Narrator"},
        )


def _packet(
    display_type: str,
    content: dict[str, Any],
    profile: dict[str, Any],
    lesson: dict[str, Any],
    npc_data: dict[str, Any],
    *,
    choices: Optional[list[dict[str, str]]] = None,
    scene_info: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "display_type": display_type,
        "content": content,
        "updated_profile": profile,
        "npc_data": npc_data,
        "scene_data": frontmatter(lesson),
    }
    if choices is not None:
        out["choices"] = choices
    if scene_info:
        out["scene_info"] = scene_info
    return out


def _err_packet(profile: dict[str, Any], msg: str) -> dict[str, Any]:
    return {
        "display_type": "ERROR",
        "content": {"text": msg},
        "updated_profile": profile,
        "npc_data": {},
    }

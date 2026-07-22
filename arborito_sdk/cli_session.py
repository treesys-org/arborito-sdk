"""Persistent CLI session (~/.arborito-sdk/) — focus, active course, preferences."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

_DEFAULT: dict[str, Any] = {
    "version": 1,
    "lang": "ES",
    "focus": {
        "source": "",
        "tree_name": "",
        "module_id": "",
        "module_name": "",
        "lesson_id": "",
        "lesson_name": "",
    },
    "user": {
        "username": "",
        "pub": "",
        "avatar": "🌳",
        "logged_in": False,
        "credential_kind": "",
    },
    "branches": [],
    "trees": [],
    "favorites": [],
    "memory": {},
    "relays": [],
}


def sdk_home() -> Path:
    env = os.environ.get("ARBORITO_SDK_HOME", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".arborito-sdk"


def config_path() -> Path:
    return sdk_home() / "config.json"


def session_path() -> Path:
    return sdk_home() / "session.json"


def trees_cache_dir() -> Path:
    return sdk_home() / "trees"


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return dict(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default)
    if not isinstance(data, dict):
        return dict(default)
    out = dict(default)
    out.update(data)
    return out


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class CliConfig:
    def __init__(self) -> None:
        self._data = load_json(
            config_path(),
            {
                "cli.show_emojis": True,
                "cli.truncate_paths": True,
                "llama.host": "",
                "llama.model": "",
            },
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        save_json(config_path(), self._data)

    @property
    def show_emojis(self) -> bool:
        return bool(self.get("cli.show_emojis", True))

    @property
    def truncate_paths(self) -> bool:
        return bool(self.get("cli.truncate_paths", True))


class CliSession:
    def __init__(self) -> None:
        self._data = load_json(session_path(), _DEFAULT)
        if "care" in self._data and "memory" not in self._data:
            self._data["memory"] = self._data.pop("care")
        self._migrate_library()
        self.config = CliConfig()
        self.repl_mode: bool = False

    def _migrate_library(self) -> None:
        if "branches" not in self._data:
            self._data["branches"] = []
        if "trees" not in self._data:
            self._data["trees"] = []
        self._data.pop("forest", None)

    def save(self) -> None:
        save_json(session_path(), self._data)

    @property
    def lang(self) -> str:
        return str(self._data.get("lang") or "ES").upper()

    @lang.setter
    def lang(self, value: str) -> None:
        self._data["lang"] = str(value or "ES").upper()

    @property
    def focus(self) -> dict[str, str]:
        f = self._data.setdefault("focus", {})
        if not isinstance(f, dict):
            f = {}
            self._data["focus"] = f
        return f  # type: ignore[return-value]

    @property
    def user(self) -> dict[str, Any]:
        u = self._data.setdefault("user", {})
        if not isinstance(u, dict):
            u = {}
            self._data["user"] = u
        return u

    def set_nostr_ref(self, pub: str, universe_id: str) -> None:
        f = self.focus
        f["nostr_ref"] = {
            "pub": str(pub or "").lower(),
            "universe_id": str(universe_id or ""),
        }
        self.save()

    def get_nostr_ref(self) -> Optional[dict[str, str]]:
        raw = self.focus.get("nostr_ref")
        if isinstance(raw, dict) and raw.get("pub") and raw.get("universe_id"):
            return {
                "pub": str(raw["pub"]).lower(),
                "universe_id": str(raw["universe_id"]),
            }
        return None

    def set_focus(
        self,
        *,
        source: str | None = None,
        tree_name: str | None = None,
        module_id: str | None = None,
        module_name: str | None = None,
        lesson_id: str | None = None,
        lesson_name: str | None = None,
    ) -> None:
        """Update focus fields. ``None`` leaves a field unchanged; ``""`` clears it."""
        f = self.focus
        if source is not None:
            f["source"] = source
            if not str(source).startswith("nostr:"):
                f.pop("nostr_ref", None)
        if tree_name is not None:
            f["tree_name"] = tree_name
        if module_id is not None:
            f["module_id"] = module_id
        if module_name is not None:
            f["module_name"] = module_name
        if lesson_id is not None:
            f["lesson_id"] = lesson_id
        if lesson_name is not None:
            f["lesson_name"] = lesson_name
        self.save()

    def focus_footer(self) -> str:
        from .tree_nav import format_focus_path

        f = self.focus
        return format_focus_path(
            tree_name=f.get("tree_name") or "",
            module_name=f.get("module_name") or "",
            lesson_name=f.get("lesson_name") or "",
            truncate=self.config.truncate_paths,
        )

    def register_branch(
        self,
        *,
        branch_id: str,
        name: str,
        source: str,
        share_code: str = "",
        nostr_ref: Optional[dict[str, str]] = None,
    ) -> None:
        self._register_library_entry(
            "branches",
            entry_id=branch_id,
            name=name,
            source=source,
            share_code=share_code,
            nostr_ref=nostr_ref,
        )

    def register_tree(
        self,
        *,
        tree_id: str,
        name: str,
        source: str,
        share_code: str = "",
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        self._register_library_entry(
            "trees",
            entry_id=tree_id,
            name=name,
            source=source,
            share_code=share_code,
            extra=extra,
        )

    def _register_library_entry(
        self,
        key: str,
        *,
        entry_id: str,
        name: str,
        source: str,
        share_code: str = "",
        nostr_ref: Optional[dict[str, str]] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        rows = self._data.setdefault(key, [])
        if not isinstance(rows, list):
            rows = []
            self._data[key] = rows
        entry: dict[str, Any] = {"id": entry_id, "name": name, "source": source}
        if share_code:
            entry["share_code"] = share_code
        if nostr_ref and nostr_ref.get("pub") and nostr_ref.get("universe_id"):
            entry["nostr_ref"] = {
                "pub": str(nostr_ref["pub"]).lower(),
                "universe_id": str(nostr_ref["universe_id"]),
            }
        if extra:
            entry.update(extra)
        rows[:] = [e for e in rows if isinstance(e, dict) and e.get("id") != entry_id]
        rows.append(entry)
        self.save()

    def list_branches(self) -> list[dict[str, Any]]:
        rows = self._data.get("branches") or []
        return [e for e in rows if isinstance(e, dict)]

    def list_trees(self) -> list[dict[str, Any]]:
        rows = self._data.get("trees") or []
        return [e for e in rows if isinstance(e, dict)]

    def active_library_entry(self) -> Optional[dict[str, Any]]:
        src = self.focus.get("source") or ""
        if not src:
            return None
        for e in self.list_branches() + self.list_trees():
            if e.get("source") == src:
                return e
        return None

    def add_favorite(self, node_id: str, name: str, path: str = "") -> None:
        favs = self._data.setdefault("favorites", [])
        if not isinstance(favs, list):
            favs = []
            self._data["favorites"] = favs
        favs[:] = [f for f in favs if isinstance(f, dict) and f.get("id") != node_id]
        favs.append({"id": node_id, "name": name, "path": path})
        self.save()

    def list_favorites(self) -> list[dict[str, Any]]:
        favs = self._data.get("favorites") or []
        return [f for f in favs if isinstance(f, dict)]

    def get_relays(self) -> list[str]:
        from .nostr_relays import normalize_nostr_relay_urls

        raw = self._data.get("relays")
        if not isinstance(raw, list):
            return []
        return normalize_nostr_relay_urls(raw)

    def set_relays(self, urls: list[str]) -> None:
        from .nostr_relays import normalize_nostr_relay_urls

        self._data["relays"] = normalize_nostr_relay_urls(urls)
        self.save()

    def clear_relays(self) -> None:
        self._data.pop("relays", None)
        self.save()

    def remove_favorite(self, ref: str) -> bool:
        favs = self.list_favorites()
        ref_fold = ref.casefold()
        kept = [
            f
            for f in favs
            if str(f.get("id") or "").casefold() != ref_fold
            and str(f.get("name") or "").casefold() != ref_fold
        ]
        if len(kept) == len(favs):
            return False
        self._data["favorites"] = kept
        self.save()
        return True

"""Arborito API mirror: lessons from arborito-library or .arborito + ask.json via a local llama.cpp server."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .archive import load_arborito_archive, load_arborito_course
from .cli_emoji import DEFAULT_AVATAR
from .ai_util import detect_llama_host
from .errors import (
    AI_EMPTY_RESPONSE,
    AI_NETWORK,
    AI_PARSE_ERROR,
    AI_SAGE_ERROR,
    ArboritoError,
    ERROR_CODES,
)
from .json_extract import parse_json_from_model_output
from .play_session import (
    branch_context_for_ai,
    build_dynamic_action_prompt,
    lesson_action_prompt,
)
from .quiz_v2 import (
    ALL_QUIZ_MODES,
    QUIZ_MODE_CHIPS,
    QUIZ_MODE_CLOZE,
    QUIZ_MODE_MULTIPLE,
    QUIZ_MODE_RECALL,
    QUIZ_MODE_STEPS,
    build_mode_card,
    build_quiz_options,
    build_study_card,
    clean_lesson_text,
    get_challenges_from_lesson,
    is_challenge_complete,
    mode_is_playable,
    new_challenge,
    parse_all_challenges_from_content,
    pick_study_mode,
    pick_unused_quiz,
    playable_modes,
    mode_label,
    quiz_item_key,
    quiz_pool_from_curriculum,
    static_match_pairs_from_lessons,
    static_quiz_from_lesson,
    answers_match,
    matches_any_answer,
    tasks_from_lesson,
)


@dataclass
class User:
    username: str
    lang: str
    avatar: str = DEFAULT_AVATAR


def _parse_challenge_from_content(content: str) -> Optional[dict[str, Any]]:
    """First complete Quiz V2 block in lesson body."""
    blocks = parse_all_challenges_from_content(content)
    return blocks[0] if blocks else None


def _collect_leaves(library_root: Path, lang: str) -> list[dict[str, Any]]:
    lang_key = lang.lower()
    nodes_dir = library_root / "data" / "nodes" / lang_key
    if not nodes_dir.is_dir():
        raise FileNotFoundError(
            f"Missing {nodes_dir}. Run builder_script.py in arborito-library or clone data/."
        )
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for path in sorted(nodes_dir.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, list):
            continue
        for node in data:
            if not isinstance(node, dict) or node.get("type") not in ("leaf", "exam"):
                continue
            nid = node.get("id")
            if not isinstance(nid, str) or nid in seen:
                continue
            cp = node.get("contentPath")
            if not isinstance(cp, str):
                continue
            content_file = library_root / "data" / "content" / cp
            if not content_file.is_file():
                continue
            try:
                payload = json.loads(content_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            text = payload.get("content") or ""
            challenges = parse_all_challenges_from_content(text)
            seen.add(nid)
            lesson: dict[str, Any] = {
                "id": nid,
                "title": node.get("title") or node.get("name") or nid,
                "text": clean_lesson_text(text),
                "raw": text,
            }
            if challenges:
                lesson["challenge"] = challenges[0]
                lesson["challenges"] = challenges
            out.append(lesson)
    return out


def _llamacpp_chat(host: str, model: Optional[str], user_text: str, timeout: float) -> str:
    """Call a local `llama-server` (llama.cpp) using the OpenAI-compatible endpoint.

    Prefers Arborito desktop on :8765 when live; falls back to :8080.
    Retries once after re-detecting the host if the first connection is refused.
    """
    from .ai_util import detect_llama_host, host_reachable

    def _once(h: str) -> str:
        url = h.rstrip("/") + "/v1/chat/completions"
        payload: dict[str, Any] = {
            "messages": [{"role": "user", "content": user_text}],
            "stream": False,
            "temperature": 0.2,
        }
        if model:
            payload["model"] = model
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        choices = data.get("choices") or []
        if not choices:
            return ""
        msg = (choices[0] or {}).get("message") or {}
        return (msg.get("content") or "").strip()

    hosts_try = []
    first = (host or "").strip() or detect_llama_host(rescan=True)
    hosts_try.append(first)
    alt = detect_llama_host(rescan=True)
    if alt not in hosts_try:
        hosts_try.append(alt)

    last_err: Exception | None = None
    for i, h in enumerate(hosts_try):
        if i > 0 and not host_reachable(h):
            continue
        try:
            return _once(h)
        except urllib.error.HTTPError as e:
            raise ArboritoError(AI_NETWORK, f"llama.cpp HTTP {e.code}: {e.reason}") from e
        except OSError as e:
            last_err = e
            continue
    raise ArboritoError(AI_NETWORK, str(last_err or "llama.cpp unreachable")) from last_err
def _tree_root_from_nostr_meta(
    meta: dict[str, Any],
    lessons: list[dict[str, Any]],
    lang: str,
    name: str,
) -> dict[str, Any]:
    from .nostr_loader import _pick_language_root

    bundle = meta.get("bundle") or {}
    root = _pick_language_root(bundle, lang)
    if isinstance(root, dict) and root.get("type"):
        return root
    return _synthetic_tree(lessons, name)


def _synthetic_tree(lessons: list[dict[str, Any]], name: str = "Course") -> dict[str, Any]:
    children = [
        {
            "id": L["id"],
            "name": L.get("title") or L["id"],
            "type": "leaf",
            "path": L.get("title") or L["id"],
            "children": [],
        }
        for L in lessons
    ]
    return {
        "id": "synthetic-root",
        "name": name,
        "type": "root",
        "path": name,
        "children": children,
    }


class Arborito:
    """
    Python SDK for Arborito courses: user, lesson, ask, quiz, matchPairs, challenge, memory.

    ``memory.*`` is in-process SM-2 (same algorithm as the app). On a Nostr-backed
    tree, ``login`` + ``memory.pull`` / ``push`` / ``sync`` share Care with Arborito.
    ``xp`` / ``save`` / ``load`` are host shims (real only inside Arcade cartridges).
    Use ai_mode='static' to read Quiz V2 from lessons without an AI server.

    Dynamic AI is served by a local **llama.cpp** server (`llama-server` from the
    llama.cpp project) exposing the OpenAI-compatible `/v1/chat/completions`
    endpoint. Configure via constructor args or env vars:

        LLAMA_CPP_HOST   Arborito desktop :8765 (Sage loaded) or llama-server :8080
        LLAMA_CPP_MODEL  optional; only needed when the server hosts >1 model

    To start a compatible server locally:

        llama-server -m path/to/model.gguf --port 8080
    """

    ERROR_CODES = ERROR_CODES

    def __init__(
        self,
        lessons: list[dict[str, Any]],
        user: User,
        *,
        ai_mode: str = "dynamic",
        llamacpp_host: Optional[str] = None,
        llamacpp_model: Optional[str] = None,
        ask_timeout: float = 120.0,
        max_json_attempts: int = 3,
        tree_root: Optional[dict[str, Any]] = None,
        lesson_by_id: Optional[dict[str, dict[str, Any]]] = None,
        course_meta: Optional[dict[str, Any]] = None,
        files: Optional[dict[str, str]] = None,
        source_label: str = "",
    ):
        self._playlist = list(lessons)
        self._cursor = 0
        self.user = user
        self._ai_mode = "static" if str(ai_mode).lower() == "static" else "dynamic"
        self._llamacpp_host = detect_llama_host(
            llamacpp_host or os.environ.get("LLAMA_CPP_HOST") or ""
        )
        self._llamacpp_model = llamacpp_model or os.environ.get("LLAMA_CPP_MODEL") or ""
        self._ask_timeout = ask_timeout
        self._max_json_attempts = max_json_attempts
        self._tree_root = tree_root
        by_id = lesson_by_id or {L["id"]: L for L in lessons if L.get("id")}
        self._lesson_by_id = by_id
        self._lesson_catalog = dict(by_id)
        self._all_lessons = list(lessons)
        self._course_meta = course_meta or {}
        self._files = files or {}
        self._source_label = source_label
        self._playlist_meta: dict[str, Any] = {}
        self._nostr_ref: Optional[dict[str, Any]] = None
        self._nostr_client: Any = None
        self._nostr_meta: dict[str, Any] = {}
        self._nostr_callbacks: list[Callable[[Arborito], None]] = []
        self._story_engine: Any = None
        self._memory_store: dict[str, dict[str, Any]] = {}
        self._network_pair: Optional[dict[str, str]] = None
        attach_helpers(self)

    def bind_network_identity(self, pair: dict[str, str]) -> None:
        """Attach the Care/progress NIP-44 keypair (``{pub, priv}``)."""
        pub = str(pair.get("pub") or "").strip().lower()
        priv = str(pair.get("priv") or "").strip().lower()
        if not pub or not priv:
            raise ValueError("Network identity needs pub and priv.")
        self._network_pair = {"pub": pub, "priv": priv}

    def login(
        self,
        username: str,
        secret: str,
        *,
        relays: Optional[list[str]] = None,
    ) -> dict[str, str]:
        """Verify sync-login, restore/create network identity escrow, bind it.

        Returns the network identity pair used for Care ``memory.pull`` / ``push``.
        """
        from .account_crypto import derive_account_signing_pair
        from .identity_store import save_network_pair
        from .nostr_client import NostrClient
        from .nostr_relays import default_nostr_relays
        from .progress_sync import restore_or_create_network_identity
        from .session_nostr import login_with_secret

        client = self._nostr_client or NostrClient(relays or default_nostr_relays())
        self._nostr_client = client
        ok, msg, user = login_with_secret(client, username, secret)
        if not ok or not user:
            raise RuntimeError(msg or "Login failed.")
        kind = str(user.get("credential_kind") or "")
        signer = derive_account_signing_pair(username, secret, credential_kind=kind)
        if not signer:
            raise RuntimeError("Could not derive account signing pair.")
        pair = restore_or_create_network_identity(
            client,
            username=str(user["username"]),
            sync_secret=secret,
            account_signer=signer,
        )
        save_network_pair(str(user["username"]), pair)
        self.bind_network_identity(pair)
        self.user.username = str(user.get("username") or self.user.username)
        return pair

    def _reindex_lessons(
        self,
        lessons: list[dict[str, Any]],
        *,
        lesson_by_id: Optional[dict[str, dict[str, Any]]] = None,
    ) -> None:
        """Replace the full course lesson index (catalog never shrinks via set_playlist)."""
        self._playlist = list(lessons)
        self._all_lessons = list(lessons)
        by_id = lesson_by_id or {L["id"]: L for L in lessons if L.get("id")}
        self._lesson_by_id = by_id
        self._lesson_catalog = dict(by_id)
        self._cursor = 0

    @classmethod
    def from_static_data(
        cls,
        library_root: str | Path,
        lang: str = "EN",
        **kwargs: Any,
    ) -> Arborito:
        """Alias for ``from_library`` (static JSON tree under ``data/nodes/<lang>/``)."""
        return cls.from_library(library_root, lang, **kwargs)

    @classmethod
    def from_library(
        cls,
        library_root: str | Path,
        lang: str = "EN",
        *,
        username: str = "developer",
        avatar: str = DEFAULT_AVATAR,
        ai_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> Arborito:
        root = Path(library_root).resolve()
        leaves = _collect_leaves(root, lang)
        user = User(username=username, lang=lang.upper(), avatar=avatar)
        mode = ai_mode or os.environ.get("ARBORITO_AI_MODE", "dynamic")
        return cls(leaves, user, ai_mode=mode, **kwargs)

    @classmethod
    def from_arborito(
        cls,
        archive_path: str | Path,
        lang: str = "ES",
        *,
        username: str = "developer",
        avatar: str = DEFAULT_AVATAR,
        ai_mode: str = "static",
        **kwargs: Any,
    ) -> Arborito:
        """Load an exported ``.arborito`` archive. Defaults to static mode."""
        course = load_arborito_course(archive_path, lang=lang)
        user = User(username=username, lang=lang.upper(), avatar=avatar)
        api = cls(
            course["lessons"],
            user,
            ai_mode=ai_mode,
            tree_root=course["tree_root"],
            lesson_by_id=course["lesson_by_id"],
            course_meta=course["meta"],
            files=course.get("files"),
            source_label=course["source_label"],
            **kwargs,
        )
        api._source_path = course.get("source_path")
        return api

    @classmethod
    def from_nostr(
        cls,
        pub: str,
        universe_id: str,
        lang: str = "ES",
        *,
        relays: Optional[list[str]] = None,
        username: str = "developer",
        avatar: str = DEFAULT_AVATAR,
        ai_mode: str = "static",
        **kwargs: Any,
    ) -> Arborito:
        """Load a published tree from Nostr (``nostr://<pub>/<universeId>``)."""
        from .nostr_client import NostrClient, merge_client_relays
        from .nostr_loader import load_nostr_course

        client = NostrClient(relays, hints_only=bool(relays))
        lessons, meta = load_nostr_course(client, str(pub).lower(), str(universe_id), lang)
        user = User(username=username, lang=lang.upper(), avatar=avatar)
        api = cls(lessons, user, ai_mode=ai_mode, **kwargs)
        api._finish_nostr_load(meta, client, universe_id=str(universe_id), pub=str(pub).lower())
        return api

    @classmethod
    def from_share_code(
        cls,
        code: str,
        lang: str = "ES",
        *,
        relays: Optional[list[str]] = None,
        username: str = "developer",
        avatar: str = DEFAULT_AVATAR,
        ai_mode: str = "static",
        **kwargs: Any,
    ) -> Arborito:
        """Resolve a public share code (``XXXX-XXXX``) and load the tree from Nostr."""
        from .errors import NOSTR_NOT_FOUND
        from .nostr_client import NostrClient, merge_client_relays
        from .nostr_loader import load_nostr_course

        client = NostrClient(relays)
        ref = client.resolve_share_code(code)
        if not ref:
            raise ArboritoError(NOSTR_NOT_FOUND, f"Share code could not be resolved: {code}")
        client = merge_client_relays(client, ref.get("recommended_relays"))
        lessons, meta = load_nostr_course(client, ref["pub"], ref["universe_id"], lang)
        if ref.get("share_code") and not meta.get("share_code"):
            meta["share_code"] = ref["share_code"]
        user = User(username=username, lang=lang.upper(), avatar=avatar)
        api = cls(lessons, user, ai_mode=ai_mode, **kwargs)
        api._finish_nostr_load(meta, client, universe_id=ref["universe_id"], pub=ref["pub"])
        return api

    def _finish_nostr_load(
        self,
        meta: dict[str, Any],
        client: Any,
        *,
        universe_id: str,
        pub: str,
    ) -> None:
        name = str(meta.get("universe_name") or meta.get("name") or universe_id)
        lang = str(getattr(self.user, "lang", None) or "ES")
        self._tree_root = _tree_root_from_nostr_meta(meta, self._playlist, lang, name)
        self._reindex_lessons(self._playlist)
        self._course_meta = meta
        self._source_label = f"nostr:{pub[:12]}…/{universe_id}"
        self._nostr_ref = {"pub": meta.get("pub") or pub, "universe_id": meta.get("universe_id") or universe_id}
        self._nostr_meta = meta
        self._nostr_client = client
        self._playlist_meta = {"source": "nostr", **meta}

    def refresh(self) -> bool:
        """Reload the Nostr bundle if this instance was loaded from the network."""
        if not self._nostr_ref or not self._nostr_client:
            return False

        pub = self._nostr_ref["pub"]
        uid = self._nostr_ref["universe_id"]
        prev = str(self._nostr_meta.get("updated_at") or "")
        hdr = self._nostr_client.get_bundle_header(pub, uid)
        if hdr:
            try:
                meta_hdr = json.loads(hdr.get("content") or "null")
                new = str(meta_hdr.get("updatedAt") or "") if isinstance(meta_hdr, dict) else ""
            except json.JSONDecodeError:
                new = ""
            if prev and new and prev == new:
                return False

        from .nostr_loader import load_nostr_course

        lessons, meta = load_nostr_course(self._nostr_client, pub, uid, self.user.lang)
        new = str(meta.get("updated_at") or "")
        self._reindex_lessons(lessons)
        self._nostr_meta = meta
        name = str(meta.get("universe_name") or meta.get("name") or uid)
        lang = str(getattr(self.user, "lang", None) or "ES")
        self._tree_root = _tree_root_from_nostr_meta(meta, lessons, lang, name)
        return bool(new and new != prev)

    def subscribe(self, on_update: Callable[["Arborito"], None]) -> None:
        if on_update not in self._nostr_callbacks:
            self._nostr_callbacks.append(on_update)

    def unsubscribe(self, on_update: Optional[Callable[["Arborito"], None]] = None) -> None:
        if on_update is None:
            self._nostr_callbacks.clear()
            return
        if on_update in self._nostr_callbacks:
            self._nostr_callbacks.remove(on_update)

    def notify_nostr_update(self) -> bool:
        """Call after ``refresh()`` to fan out subscribed callbacks."""
        changed = self.refresh()
        if changed:
            for cb in list(self._nostr_callbacks):
                try:
                    cb(self)
                except Exception:
                    pass
        return changed

    def getAIMode(self) -> str:
        """'static' (Quiz V2 only) or 'dynamic' (local llama.cpp server for ask.json / AI helpers)."""
        return self._ai_mode

    def refresh_llama_host(self) -> str:
        """Re-probe Arborito :8765 / llama :8080 (Sage may start after the client was created)."""
        self._llamacpp_host = detect_llama_host(self._llamacpp_host or "", rescan=True)
        return self._llamacpp_host

    @property
    def lesson(self) -> _LessonNS:
        return _LessonNS(self)

    @property
    def ask(self) -> _AskNS:
        return _AskNS(self)

    @property
    def challenge(self) -> _ChallengeNS:
        return _ChallengeNS()

    @property
    def meta(self) -> _MetaNS:
        return _MetaNS()

    def xp(self, _n: int) -> None:
        """No-op offline (browser sends XP to the host)."""
        return

    def save(self, _key: str, _value: Any) -> bool:
        return False

    def load(self, _key: str) -> Any:
        return None

    def exit(self) -> None:
        """No-op offline (browser closes the game modal)."""
        return

    @property
    def memory(self) -> _MemoryNS:
        return _MemoryNS(self)

    @property
    def tree(self) -> "_TreeNS":
        return _TreeNS(self)

    @property
    def module(self) -> "_ModuleNS":
        return _ModuleNS(self)

    @property
    def content(self) -> "_ContentNS":
        return _ContentNS()

    def _narrative_engine(self) -> Any:
        if self._story_engine is None:
            from .story_engine import StoryEngine

            engine = StoryEngine(self)

            def _ask_npc(
                npc: dict[str, Any],
                text: str,
                lesson: dict[str, Any],
                *,
                beat: str = "",
                mode: str = "adapt",
            ) -> str:
                author_line = str(beat or "").strip()
                player_said = str(text or "").strip()
                opts: dict[str, Any] = {
                    "persona": str(npc.get("system_prompt") or npc.get("name") or "NPC"),
                }
                if author_line:
                    opts["authorLine"] = author_line
                if mode == "adapt" and author_line:
                    player_said = author_line
                try:
                    out = self.ask.lesson_action(lesson, player_said, opts)
                    if isinstance(out, dict) and out.get("output"):
                        return str(out["output"])
                except Exception:
                    pass
                return author_line or player_said or str(npc.get("name") or "…")

            engine.set_ask_npc(_ask_npc)
            self._story_engine = engine
        return self._story_engine


class _ContentNS:
    def body(self, lesson: dict[str, Any]) -> str:
        from .content import body

        return body(lesson)

    def raw(self, lesson: dict[str, Any]) -> str:
        from .content import raw

        return raw(lesson)

    def blocks(self, lesson: dict[str, Any], tag: str) -> list[str]:
        from .content import blocks

        return blocks(lesson, tag)

    def frontmatter(self, lesson: dict[str, Any]) -> dict[str, Any]:
        from .content import frontmatter

        return frontmatter(lesson)

    def code_fences(self, lesson: dict[str, Any]) -> list[dict[str, str]]:
        from .content import code_fences

        return code_fences(lesson)

    def games(self, lesson: dict[str, Any]) -> list[dict[str, Any]]:
        from .content import game_blocks

        return game_blocks(lesson)

    def info(self, lesson: dict[str, Any]) -> dict[str, Any]:
        from .content import info_meta

        return info_meta(lesson)


class _TreeNS:
    def __init__(self, client: Arborito) -> None:
        self._c = client

    def info(self) -> dict[str, Any]:
        meta = self._c._course_meta or {}
        root = self._c._tree_root or {}
        titles = meta.get("titles") if isinstance(meta.get("titles"), dict) else {}
        lang = str(self._c.user.lang or "").strip().upper()
        title = ""
        if lang and titles.get(lang):
            title = str(titles[lang]).strip()
        elif titles:
            title = str(next(iter(titles.values())) or "").strip()
        return {
            "name": title or root.get("name") or self._c._source_label,
            "lang": self._c.user.lang,
            "source": self._c._source_label,
            "lessons": len(self._c._playlist),
        }

    def root(self) -> Optional[dict[str, Any]]:
        return self._c._tree_root

    def find(self, identifier: str, *, partial: bool = False) -> list[dict[str, Any]]:
        from .tree_nav import find_node

        root = self._c._tree_root
        if not root:
            return []
        return find_node(root, identifier, partial=partial)

    def modules(self) -> list[dict[str, Any]]:
        from .tree_nav import node_summary, top_modules

        root = self._c._tree_root
        if not root:
            return []
        return [node_summary(m) for m in top_modules(root)]


class _ModuleNS:
    def __init__(self, client: Arborito) -> None:
        self._c = client

    def find(self, identifier: str, *, partial: bool = False) -> Optional[dict[str, Any]]:
        hits = self._c.tree.find(identifier, partial=partial)
        for h in hits:
            if str(h.get("type") or "") == "branch":
                return h
        return hits[0] if hits else None

    def playlist(self, module: dict[str, Any]) -> list[dict[str, Any]]:
        from .tree_nav import module_playlist

        nodes = module_playlist(module)
        out: list[dict[str, Any]] = []
        for n in nodes:
            lesson = self._c.lesson.by_id(str(n.get("id") or ""))
            if lesson:
                out.append(lesson)
        return out

    def readme(self, module: dict[str, Any]) -> dict[str, Any]:
        from .quiz_v2 import _parse_module_readme

        path = str(module.get("path") or module.get("name") or "")
        files = self._c._files or {}
        for key, text in files.items():
            if key.lower().endswith("readme.md") and path.casefold() in key.casefold():
                meta, body = _parse_module_readme(text)
                return {"meta": meta, "body": body}
        return {"meta": {}, "body": ""}


class _MemoryNS:
    """In-process SM-2 memory (parity with browser ``arborito.memory``).

    With a network identity + Nostr tree ref, ``pull`` / ``push`` / ``sync``
    exchange Care schedules with the same KIND_USER_PROGRESS envelopes as the app.
    """

    def __init__(self, client: Arborito):
        self._c = client

    def due(self) -> list[str]:
        from .progress_sync import memory_status

        out: list[str] = []
        for nid, row in self._c._memory_store.items():
            if memory_status(row).get("isDue"):
                out.append(str(nid))
        return out

    def getStatus(self, node_id: str) -> dict[str, Any]:
        from .progress_sync import memory_status

        return memory_status(self._c._memory_store.get(str(node_id or "")))

    def isDue(self, node_id: str) -> bool:
        return bool(self.getStatus(node_id).get("isDue"))

    def report(self, node_id: str, quality: int) -> dict[str, Any]:
        from .progress_sync import report_memory_sm2

        nid = str(node_id or "").strip()
        if not nid:
            return {}
        prev = self._c._memory_store.get(nid)
        item = report_memory_sm2(prev, quality)
        self._c._memory_store[nid] = item
        return item

    def _require_tree_and_pair(self) -> tuple[dict[str, str], dict[str, str], Any]:
        pair = getattr(self._c, "_network_pair", None)
        if not isinstance(pair, dict) or not pair.get("priv") or not pair.get("pub"):
            raise RuntimeError(
                "Network identity required. Call api.login(username, secret) "
                "or api.bind_network_identity(pair) first."
            )
        ref = getattr(self._c, "_nostr_ref", None)
        if not isinstance(ref, dict) or not ref.get("pub") or not ref.get("universe_id"):
            raise RuntimeError(
                "Care sync needs a Nostr-backed tree "
                "(Arborito.from_share_code / from_nostr)."
            )
        client = getattr(self._c, "_nostr_client", None)
        if client is None:
            from .nostr_client import NostrClient
            from .nostr_relays import default_nostr_relays

            client = NostrClient(default_nostr_relays())
            self._c._nostr_client = client
        return pair, ref, client

    def pull(self) -> bool:
        """Merge remote Care memory for this tree into the in-process store."""
        from .progress_sync import ProgressUndecryptableError, merge_memory_maps, pull_encrypted_progress

        pair, ref, client = self._require_tree_and_pair()
        try:
            data = pull_encrypted_progress(
                client,
                owner_pub=str(ref["pub"]),
                universe_id=str(ref["universe_id"]),
                pair=pair,
            )
        except ProgressUndecryptableError:
            return False
        if not data or not isinstance(data.get("memory"), dict):
            return False
        self._c._memory_store = merge_memory_maps(self._c._memory_store, data["memory"])
        return True

    def push(self) -> bool:
        """Publish in-process memory as packed KIND_USER_PROGRESS for this tree."""
        from .progress_sync import (
            build_progress_payload,
            is_progress_payload_empty,
            push_encrypted_progress,
        )

        pair, ref, client = self._require_tree_and_pair()
        payload = build_progress_payload(self._c._memory_store)
        if is_progress_payload_empty(payload):
            return False
        return push_encrypted_progress(
            client,
            owner_pub=str(ref["pub"]),
            universe_id=str(ref["universe_id"]),
            pair=pair,
            data=payload,
        )

    def sync(self) -> bool:
        """Rsync-style Care sync: pull → merge → publish only if content differs."""
        from .progress_sync import (
            ProgressUndecryptableError,
            build_progress_payload,
            merge_memory_maps,
            pull_encrypted_progress,
            push_encrypted_progress,
            should_publish_merged_progress,
        )

        pair, ref, client = self._require_tree_and_pair()
        try:
            remote = pull_encrypted_progress(
                client,
                owner_pub=str(ref["pub"]),
                universe_id=str(ref["universe_id"]),
                pair=pair,
            )
        except ProgressUndecryptableError:
            return False
        if remote and isinstance(remote.get("memory"), dict):
            self._c._memory_store = merge_memory_maps(self._c._memory_store, remote["memory"])
        merged = build_progress_payload(self._c._memory_store)
        if not should_publish_merged_progress(remote=remote, merged=merged):
            return True
        return push_encrypted_progress(
            client,
            owner_pub=str(ref["pub"]),
            universe_id=str(ref["universe_id"]),
            pair=pair,
            data=merged,
        )


class _MetaNS:
    def read(self, lesson: dict[str, Any]) -> dict[str, Any]:
        return _LessonNS.read_meta(lesson)


class _ChallengeModesNS:
    """Quiz V2 modalities: multiple, recall, cloze, chips, steps.

    Mirrors `window.arborito.challenge.modes` in the browser cartridge SDK.
    """

    ALL = list(ALL_QUIZ_MODES)
    MULTIPLE = QUIZ_MODE_MULTIPLE
    RECALL = QUIZ_MODE_RECALL
    CLOZE = QUIZ_MODE_CLOZE
    CHIPS = QUIZ_MODE_CHIPS
    STEPS = QUIZ_MODE_STEPS

    def isPlayable(self, challenge: dict[str, Any], mode: str) -> bool:
        return mode_is_playable(challenge, mode)

    def playable(self, challenge: dict[str, Any]) -> list[str]:
        return playable_modes(challenge)

    def pick(self, challenge: dict[str, Any], block_id: str, salt: str = "") -> str:
        return pick_study_mode(challenge, block_id, salt)

    def buildCard(
        self,
        challenge: dict[str, Any],
        mode: str,
        *,
        lesson_title: str = "",
        lang: str = "ES",
        option_count: int = 4,
        distractor_pool: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> Optional[dict[str, Any]]:
        # Accept camelCase from Arcade-style opts dicts.
        if distractor_pool is None and "distractorPool" in kwargs:
            distractor_pool = kwargs.get("distractorPool")  # type: ignore[assignment]
        if "optionCount" in kwargs and option_count == 4:
            try:
                option_count = int(kwargs["optionCount"])
            except (TypeError, ValueError):
                pass
        if "lessonTitle" in kwargs and not lesson_title:
            lesson_title = str(kwargs.get("lessonTitle") or "")
        return build_mode_card(
            challenge,
            mode,
            lesson_title=lesson_title,
            lang=lang,
            option_count=option_count,
            distractor_pool=distractor_pool,
        )

    def buildStudyCard(
        self,
        challenge: dict[str, Any],
        block_id: str,
        *,
        lesson_title: str = "",
        lang: str = "ES",
        salt: str = "",
        distractor_pool: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> Optional[dict[str, Any]]:
        if distractor_pool is None and "distractorPool" in kwargs:
            distractor_pool = kwargs.get("distractorPool")  # type: ignore[assignment]
        return build_study_card(
            challenge,
            block_id,
            lesson_title=lesson_title,
            lang=lang,
            salt=salt,
            distractor_pool=distractor_pool,
        )

    def label(self, mode: str, lang: str = "ES") -> str:
        return mode_label(mode, lang)


class _ChallengeNS:
    modes = _ChallengeModesNS()

    def isComplete(self, challenge: dict[str, Any]) -> bool:
        return is_challenge_complete(challenge)

    def getCompleteness(self, challenge: dict[str, Any]) -> dict[str, Any]:
        if not challenge:
            return {"complete": False, "score": 0, "total": 5}
        items = challenge.get("items") or []
        if items:
            parts = [self.getCompleteness(item) for item in items]
            return {
                "complete": all(p["complete"] for p in parts),
                "score": sum(p["score"] for p in parts),
                "total": sum(p["total"] for p in parts) or 5,
            }
        if is_challenge_complete(challenge):
            return {"complete": True, "score": 5, "total": 5}
        fields = ["core_concept", "short_definition", "main_question", "correct_answer"]
        score = sum(1 for f in fields if str(challenge.get(f) or "").strip())
        if challenge.get("traps"):
            score += 1
        return {"complete": False, "score": score, "total": 5}

    def fromLesson(self, lesson: dict[str, Any]) -> list[dict[str, Any]]:
        return get_challenges_from_lesson(lesson)

    def tasksFromLesson(
        self,
        lesson: dict[str, Any],
        opts: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Practice tasks from Quiz V2 (+ optional code replays). Same shape as Arcade."""
        o = opts or {}
        lang = str(o.get("lang") or "ES")
        max_tasks = max(1, int(o.get("max") or o.get("max_tasks") or 10))
        modes = o.get("modes")
        include_code = o.get("includeCodeReplays", o.get("include_code_replays", True))
        return tasks_from_lesson(
            lesson,
            lang=lang,
            max_tasks=max_tasks,
            modes=list(modes) if modes else None,
            include_code_replays=include_code is not False,
        )

    def template(self) -> dict[str, Any]:
        return new_challenge()

    def buildDuelDeck(self, lesson: dict[str, Any]) -> Optional[list[dict[str, Any]]]:
        c = lesson.get("challenge") if lesson else None
        if not c or not c.get("main_question") or not c.get("correct_answer"):
            return None
        traps = [t for t in (c.get("traps") or []) if t]
        wrong_pool = traps[:]
        sd = str(c.get("short_definition") or "").strip()
        ca = str(c.get("correct_answer") or "").strip()
        if sd and sd != ca:
            wrong_pool.append(sd)
        options = [ca] + wrong_pool[:3]
        return [
            {
                "id": "core",
                "name": c.get("core_concept") or lesson.get("title") or "Lesson",
                "effect": sd,
                "question": c.get("main_question"),
                "correct": ca,
                "options": options,
                "power": 100,
            }
        ]


class _LessonNS:
    def __init__(self, client: Arborito):
        self._c = client

    @staticmethod
    def read_meta(lesson: dict[str, Any]) -> dict[str, Any]:
        """Lesson `@info` block as a plain dict: just `tags` for now.

        Spaced-repetition status is decided by Arborito's own SRS engine
        (`memory.due()` / `memory.getStatus(lessonId)`); it is **not** an
        authoring flag, so it is intentionally not surfaced here.
        """
        meta = (lesson or {}).get("meta") or {}
        return {"tags": list(meta.get("tags") or [])}

    readMeta = read_meta  # Arcade camelCase alias

    @staticmethod
    def plainText(lesson_or_raw: Any) -> str:
        """NPC / HUD prose — same role as browser ``lesson.plainText``."""
        from .content import lesson_plain_text

        return lesson_plain_text(lesson_or_raw)

    plain_text = plainText  # snake_case alias

    def list(self) -> list[dict[str, str]]:
        return [{"id": x["id"], "title": x["title"]} for x in self._c._playlist]

    def by_id(self, lesson_id: str) -> Optional[dict[str, Any]]:
        lid = str(lesson_id or "").strip()
        if not lid:
            return None
        hit = self._c._lesson_catalog.get(lid) or self._c._lesson_by_id.get(lid)
        return dict(hit) if hit else None

    byId = by_id  # Arcade camelCase alias

    @staticmethod
    def context_for_ai(lesson: dict[str, Any]) -> str:
        from .play_session import lesson_context_for_ai

        return lesson_context_for_ai(lesson)

    contextForAi = context_for_ai  # Arcade camelCase alias

    def branch_context_for_ai(
        self,
        anchor_lesson: Optional[dict[str, Any]] = None,
        profile: Optional[dict[str, Any]] = None,
    ) -> str:
        return branch_context_for_ai(self._c, anchor_lesson, profile)

    branchContextForAi = branch_context_for_ai  # Arcade camelCase alias

    def branch_profile(
        self,
        anchor_lesson: Optional[dict[str, Any]] = None,
        opts: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        profile = {
            "playerName": self._c.user.username,
            "playerLang": self._c.user.lang,
        }
        if opts:
            profile.update(opts)
        branch_context_for_ai(self._c, anchor_lesson, profile)
        return profile

    branchProfile = branch_profile  # Arcade camelCase alias

    def set_playlist(self, lessons: list[dict[str, Any]]) -> None:
        """Set the active study playlist without shrinking the course catalog."""
        self._c._playlist = list(lessons)
        for row in self._c._playlist:
            lid = str(row.get("id") or "")
            if lid:
                self._c._lesson_catalog[lid] = row
                self._c._lesson_by_id[lid] = row
        self._c._cursor = 0

    def set_playlist_module(self, module: dict[str, Any]) -> list[dict[str, Any]]:
        pl = self._c.module.playlist(module)
        self.set_playlist(pl)
        return pl

    def restore_full_playlist(self) -> None:
        """Restore the course-wide playlist (after focusing the tree root)."""
        full = getattr(self._c, "_all_lessons", None) or list(self._c._lesson_catalog.values())
        self.set_playlist(list(full))

    def next(self) -> Optional[dict[str, Any]]:
        if not self._c._playlist:
            return None
        if self._c._cursor >= len(self._c._playlist):
            self._c._cursor = 0
        lesson = self._c._playlist[self._c._cursor]
        self._c._cursor += 1
        return dict(lesson)

    def at(self, idx: int) -> Optional[dict[str, Any]]:
        if idx < 0 or idx >= len(self._c._playlist):
            return None
        return dict(self._c._playlist[idx])


class _AskNS:
    def __init__(self, client: Arborito):
        self._c = client

    def json(
        self,
        prompt: str,
        on_complete: Optional[Callable[[Any], None]] = None,
        *,
        timeout_ms: Optional[int] = None,
        max_attempts: Optional[int] = None,
    ) -> Any:
        """Same role as window.arborito.ask.json (Python is synchronous here)."""
        if self._c.getAIMode() == "static":
            raise ArboritoError(
                AI_SAGE_ERROR,
                "AI not available in static mode. Use quiz()/matchPairs() or set ai_mode='dynamic'.",
            )
        augmented = prompt + "\n\nIMPORTANT: Return ONLY valid JSON. Do not include markdown code blocks."
        timeout = (timeout_ms / 1000.0) if timeout_ms else self._c._ask_timeout
        attempts = max_attempts if max_attempts is not None else self._c._max_json_attempts
        last_err: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                raw = _llamacpp_chat(
                    self._c._llamacpp_host,
                    self._c._llamacpp_model,
                    augmented,
                    timeout,
                )
                try:
                    out = parse_json_from_model_output(raw)
                except json.JSONDecodeError as e:
                    last_err = ArboritoError(AI_PARSE_ERROR, str(e))
                    if attempt < attempts - 1:
                        continue
                    raise last_err from e
                except ValueError as e:
                    msg = str(e)
                    if msg == "SAGE_ERROR_MARKER":
                        raise ArboritoError(AI_SAGE_ERROR, (raw or "")[:2000]) from e
                    if msg == "EMPTY":
                        raise ArboritoError(AI_EMPTY_RESPONSE, "Model returned no JSON.") from e
                    raise
                if on_complete:
                    on_complete(out)
                return out
            except ArboritoError as e:
                if e.code in (AI_SAGE_ERROR, AI_EMPTY_RESPONSE):
                    raise
                last_err = e
                if attempt < attempts - 1:
                    continue
                raise
        if last_err:
            raise last_err
        raise ArboritoError(AI_PARSE_ERROR, "Exhausted retries.")

    def lesson_action(
        self,
        lesson: dict[str, Any],
        input_text: str,
        opts: Optional[dict[str, Any]] = None,
    ) -> Any:
        opts = dict(opts or {})
        persona = str(opts.get("persona") or opts.get("role") or "")
        if not persona and hasattr(self._c, "_ai_persona"):
            persona = self._c._ai_persona
        if persona:
            opts["persona"] = persona
        prompt = build_dynamic_action_prompt(
            self._c, lesson, str(input_text or ""), opts
        )
        return self.json(prompt)

    lessonAction = lesson_action  # Arcade camelCase alias

    def with_context(
        self,
        query: str,
        *,
        module: str = "",
        lesson_id: str = "",
        scope: Optional[dict[str, str]] = None,
    ) -> str:
        from .context_index import ContextIndex

        sc = dict(scope or {})
        if module:
            sc["module"] = module
        if lesson_id:
            sc["lesson_id"] = lesson_id
        idx = ContextIndex(self._c)
        brief = idx.brief_for_query(
            query,
            module=sc.get("module") or "",
            lesson_id=sc.get("lesson_id") or "",
        )
        if self._c.getAIMode() == "static":
            return brief or "No indexed context for that query."
        lang_name = "Spanish" if self._c.user.lang.upper() == "ES" else "English"
        prompt = (
            f"{brief}\n\n"
            f"Answer in {lang_name}, grounded in the context above.\n"
            f"Question: {query}\n"
            "Reply in plain text (no markdown fences)."
        )
        return _llamacpp_chat(
            self._c._llamacpp_host,
            self._c._llamacpp_model,
            prompt,
            self._c._ask_timeout,
        )

    def npc(
        self,
        npc: dict[str, Any],
        player_input: str,
        *,
        scene_hint: str = "",
        beat: str = "",
        mode: str = "reply",
        lesson: Optional[dict[str, Any]] = None,
    ) -> str:
        """Narrative reply helper. Prefer ask.lesson_action with authorLine for new code."""
        persona = str(npc.get("system_prompt") or npc.get("name") or "NPC")
        name = str(npc.get("name") or "NPC")
        author_line = str(beat or "").strip()
        player_said = str(player_input or "").strip()
        if scene_hint:
            persona = f"{persona}\nScene: {scene_hint}".strip()
        if self._c.getAIMode() == "static":
            return f"[{name}] {(author_line or player_said or persona)[:400]}"
        anchor = lesson or (self._c.lesson.at(0) if self._c._playlist else None)
        if not anchor:
            raise ArboritoError(AI_EMPTY_RESPONSE, "No lesson loaded for ask.npc.")
        opts: dict[str, Any] = {"persona": persona}
        if author_line:
            opts["authorLine"] = author_line
        # adapt: rewrite author beat; reply: answer the player (beat = context)
        said = "" if (mode == "adapt" and author_line and not player_said) else player_said
        try:
            out = self.lesson_action(anchor, said, opts)
        except ArboritoError:
            raise
        except Exception as e:
            raise ArboritoError(AI_NETWORK, str(e)) from e
        if isinstance(out, dict) and out.get("output"):
            return str(out["output"])
        raise ArboritoError(AI_EMPTY_RESPONSE, "ask.npc: model returned no output field.")

    def chat(self, messages: list[dict[str, str]], _ctx: Any = None) -> dict[str, Any]:
        if self._c.getAIMode() == "static":
            raise ArboritoError(AI_SAGE_ERROR, "AI not available in static mode.")
        text = ""
        for m in reversed(messages):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                text = m["content"]
                break
        raw = _llamacpp_chat(
            self._c._llamacpp_host,
            self._c._llamacpp_model,
            text,
            self._c._ask_timeout,
        )
        return {"rawText": raw, "text": raw}


def quiz_prompt(lesson: dict[str, Any], count: int, lang: str) -> str:
    lang_name = "Spanish" if lang.upper() == "ES" else "English"
    txt = (lesson.get("text") or "")[:800]
    return (
        f'Context: "{txt}".\n'
        f"The user language is {lang_name}.\n"
        f"Generate {count} distinct topics based on the context. For each topic, create a short question, "
        f"a CORRECT answer (max 3 words), and a PLAUSIBLE WRONG answer (max 3 words).\n"
        f"ALL output (topics, questions, answers) MUST be in {lang_name}.\n"
        "Return ONLY a valid JSON array matching this schema:\n"
        '[\n    { "topic": "Short Topic Name", "q": "Question text", "correct": "Correct Answer", "wrong": "Wrong Answer" }\n]'
    )


def match_pairs_prompt(lesson: dict[str, Any], n: int, lang: str) -> str:
    lang_name = "Spanish" if lang.upper() == "ES" else "English"
    txt = (lesson.get("text") or "")[:1000]
    return (
        f'Context: "{txt}".\n'
        f"Task: Create content for a Memory-style card matching game in {lang_name}.\n"
        f"Goal: Generate {n} pairs of concepts where the player must match a Term with its Definition.\n"
        f"Rules: Terms 1-3 words; definitions max 6 words; all in {lang_name}; pairs unique and logically connected.\n"
        'Output: ONLY a valid JSON array: [{"t": "Term", "d": "Definition"}, ...]'
    )


def attach_helpers(arborito: Arborito) -> None:
    """Add quiz() and matchPairs() like the browser SDK."""

    def quiz(lesson: dict[str, Any], opts: Optional[dict[str, Any]] = None) -> Any:
        opts = opts or {}
        count = int(opts.get("count", 3))
        if arborito.getAIMode() == "static":
            items = static_quiz_from_lesson(lesson, count, arborito.user.lang)
            if not items:
                raise ArboritoError(
                    AI_SAGE_ERROR,
                    "STATIC_QUIZ: Fill the lesson questionnaire (Quiz V2) to play in static mode.",
                )
            return items
        return arborito.ask.json(quiz_prompt(lesson, count, arborito.user.lang))

    quiz.item_key = quiz_item_key  # type: ignore[attr-defined]

    def _build_options(item: dict[str, Any], count: int = 4, **kwargs: Any) -> list[str]:
        lang = str(kwargs.get("lang") or arborito.user.lang or "EN")
        pool = kwargs.get("distractor_pool")
        if pool is None:
            pool = kwargs.get("distractorPool")
        return build_quiz_options(
            item,
            count,
            lang=lang,
            distractor_pool=list(pool) if pool else None,
        )

    quiz.build_options = _build_options  # type: ignore[attr-defined]
    quiz.buildOptions = _build_options  # type: ignore[attr-defined]

    def _quiz_pool(opts: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        o = opts or {}
        max_att = o.get("max_attempts")
        return quiz_pool_from_curriculum(
            arborito,
            count=int(o.get("count", 6)),
            unique_lessons=o.get("unique_lessons", True) is not False,
            unique_questions=o.get("unique_questions", True) is not False,
            max_attempts=int(max_att) if max_att is not None else None,
        )

    quiz.pool = _quiz_pool  # type: ignore[attr-defined]
    quiz.pick = pick_unused_quiz  # type: ignore[attr-defined]
    quiz.answers_match = answers_match  # type: ignore[attr-defined]

    def _matches_any(player: str, expected: list[str]) -> dict[str, Any]:
        ok, matched = matches_any_answer(player, expected)
        return {"ok": ok, "matched": matched or None}

    quiz.matches_any = _matches_any  # type: ignore[attr-defined]
    quiz.matchesAny = _matches_any  # type: ignore[attr-defined]

    def _find_code_replay(
        input_text: str,
        replays: Optional[list[dict[str, str]]] = None,
        lesson: Optional[dict[str, Any]] = None,
    ) -> Any:
        from .content import code_replays_from_lesson, find_code_replay

        pool = replays
        if pool is None and lesson is not None:
            pool = code_replays_from_lesson(lesson)
        return find_code_replay(input_text, pool)

    quiz.find_code_replay = _find_code_replay  # type: ignore[attr-defined]
    quiz.findCodeReplay = _find_code_replay  # type: ignore[attr-defined]

    def _grade_answer(
        lesson: dict[str, Any],
        item: dict[str, Any],
        player_text: str,
        opts: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Local match first, then grounded LLM in dynamic mode."""
        from .play_session import grade_quiz_answer_prompt

        text = str(player_text or "").strip()
        if not text:
            return False
        if answers_match(text, str(item.get("correct") or "")):
            return True
        if arborito.getAIMode() == "static" or not lesson:
            return False
        o = opts or {}
        prompt = grade_quiz_answer_prompt(lesson, item, text, arborito.user.lang)
        try:
            res = arborito.ask.json(
                prompt,
                timeout_ms=o.get("timeout_ms"),
                max_attempts=o.get("max_attempts"),
            )
            return bool(isinstance(res, dict) and res.get("correct"))
        except Exception:
            return answers_match(text, str(item.get("correct") or ""))

    quiz.grade_answer = _grade_answer  # type: ignore[attr-defined]
    quiz.gradeAnswer = _grade_answer  # type: ignore[attr-defined]

    def match_pairs(lesson: dict[str, Any], opts: Optional[dict[str, Any]] = None) -> Any:
        opts = opts or {}
        n = int(opts.get("count", 6))
        fill = opts.get("fillFromCurriculum", True)

        if arborito.getAIMode() == "static" or get_challenges_from_lesson(lesson):
            lessons = [lesson] if lesson else []
            pairs = static_match_pairs_from_lessons(lessons, n)
            if fill and len(pairs) < n and lesson and lesson.get("id"):
                start = -1
                for i, L in enumerate(arborito._playlist):
                    if L.get("id") == lesson.get("id"):
                        start = i
                        break
                if start >= 0:
                    for follow in arborito._playlist[start + 1 :]:
                        lessons.append(follow)
                        pairs = static_match_pairs_from_lessons(lessons, n)
                        if len(pairs) >= n:
                            break
            if pairs:
                return pairs[:n]
            if arborito.getAIMode() == "static":
                raise ArboritoError(
                    AI_SAGE_ERROR,
                    "STATIC_PAIRS: Fill the lesson questionnaire (Quiz V2) to play in static mode.",
                )

        return arborito.ask.json(match_pairs_prompt(lesson, n, arborito.user.lang))

    setattr(arborito, "quiz", quiz)
    setattr(arborito, "matchPairs", match_pairs)
    arborito._ai_persona = ""  # type: ignore[attr-defined]

    class _NarrativeNS:
        def __init__(self, arb: Arborito) -> None:
            self._arb = arb

        def start(self, module: str, **kwargs: Any) -> dict[str, Any]:
            """Start a frontmatter narrative module."""
            return self._arb._narrative_engine().start(module, **kwargs)

        def advance(
            self, profile: dict[str, Any], player_input: Optional[str] = None
        ) -> dict[str, Any]:
            return self._arb._narrative_engine().advance(profile, player_input)

    class _AiNS:
        def __init__(self, arb: Arborito) -> None:
            self._arb = arb

        @property
        def persona(self) -> str:
            return str(getattr(self._arb, "_ai_persona", "") or "")

        @persona.setter
        def persona(self, value: str) -> None:
            self._arb._ai_persona = str(value or "")

        @property
        def arborito(self) -> str:
            return self.persona

        @arborito.setter
        def arborito(self, value: str) -> None:
            self.persona = value

    setattr(arborito, "narrative", _NarrativeNS(arborito))
    setattr(arborito, "ai", _AiNS(arborito))

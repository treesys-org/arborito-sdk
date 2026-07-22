"""Default Nostr relay list — same suggested bundle as Arborito onboarding."""

from __future__ import annotations

import json
import os
import re
from typing import Iterable

# Mirrors `SUGGESTED_NOSTR_RELAYS` in arborito/src/features/nostr/api/nostr-relays-runtime.js
DEFAULT_NOSTR_RELAYS: tuple[str, ...] = (
    "wss://relay.tchncs.de",
    "wss://nostr.einundzwanzig.space",
    "wss://purplepag.es",
    "wss://nos.lol",
    "wss://relay.primal.net",
)


def normalize_nostr_relay_urls(values: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or ():
        s = str(raw or "").strip()
        if not s:
            continue
        if not re.match(r"^wss?://", s, re.I):
            try:
                s = "wss://" + s.removeprefix("//")
            except Exception:
                continue
        if not s.lower().startswith("wss://"):
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def merge_nostr_relay_urls(*lists: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for lst in lists:
        for url in normalize_nostr_relay_urls(lst):
            if url in seen:
                continue
            seen.add(url)
            out.append(url)
    return out


def default_nostr_relays(*, extra: Iterable[str] | None = None) -> list[str]:
    """Relays for SDK network loads.

    Order: explicit ``extra`` → ``ARBORITO_NOSTR_RELAYS`` env (JSON array or comma list)
    → ``DEFAULT_NOSTR_RELAYS`` (Arborito suggested bundle).
    """
    env_raw = os.environ.get("ARBORITO_NOSTR_RELAYS", "").strip()
    env_relays: list[str] = []
    if env_raw:
        if env_raw.startswith("["):
            try:
                parsed = json.loads(env_raw)
                if isinstance(parsed, list):
                    env_relays = normalize_nostr_relay_urls(parsed)
            except json.JSONDecodeError:
                pass
        if not env_relays:
            env_relays = normalize_nostr_relay_urls(
                p.strip() for p in re.split(r"[\s,]+", env_raw) if p.strip()
            )
    return merge_nostr_relay_urls(extra, env_relays, DEFAULT_NOSTR_RELAYS)

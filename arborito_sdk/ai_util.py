"""LLM host detection and ai doctor."""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from typing import Any, Optional
from urllib.parse import urlparse

# Arborito desktop (Electron) spawns llama-server here after Sage loads a model.
ARBORITO_DESKTOP_LLAMA = "http://127.0.0.1:8765"
# Standalone llama.cpp default.
GENERIC_LLAMA = "http://127.0.0.1:8080"


def normalize_host(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if not u:
        return ARBORITO_DESKTOP_LLAMA
    if not u.startswith("http"):
        u = "http://" + u
    return u


def _host_port(url: str) -> tuple[str, int]:
    parsed = urlparse(normalize_host(url))
    host = parsed.hostname or "127.0.0.1"
    if parsed.port:
        return host, int(parsed.port)
    return host, 443 if parsed.scheme == "https" else 80


def _port_open(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def host_reachable(url: str, timeout: float = 0.35) -> bool:
    h, p = _host_port(url)
    return _port_open(h, p, timeout=timeout)


def detect_llama_host(preferred: str = "", *, rescan: bool = True) -> str:
    """Pick a live OpenAI-compatible llama host.

    Order: preferred (if open) → LLAMA_CPP_HOST (if open) → Arborito :8765 → :8080.
    If nothing listens, return preferred/env or Arborito desktop URL (for clearer errors).

    Note: preferred used to short-circuit without a port check, which froze the SDK on
    dead :8080 even after Arborito later started Sage on :8765.
    """
    env = os.environ.get("LLAMA_CPP_HOST", "").strip()
    candidates: list[str] = []
    if preferred:
        candidates.append(normalize_host(preferred))
    if env:
        candidates.append(normalize_host(env))
    candidates.extend([ARBORITO_DESKTOP_LLAMA, GENERIC_LLAMA])

    seen: set[str] = set()
    ordered: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            ordered.append(c)

    if rescan:
        for host in ordered:
            if host_reachable(host):
                return host

    # Nothing listening: prefer env override, else Arborito desktop port in error text
    # (opening the app is the usual path; :8080 alone is misleading).
    if env:
        return normalize_host(env)
    return ARBORITO_DESKTOP_LLAMA


def ping_llama(host: str, model: str = "", timeout: float = 3.0) -> dict[str, Any]:
    host = normalize_host(host)
    url = f"{host}/v1/models"
    t0 = __import__("time").time()
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        elapsed = int((__import__("time").time() - t0) * 1000)
        models: list[str] = []
        try:
            data = json.loads(raw)
            for m in data.get("data") or []:
                mid = m.get("id") if isinstance(m, dict) else None
                if mid:
                    models.append(str(mid))
        except json.JSONDecodeError:
            pass
        return {
            "ok": True,
            "host": host,
            "latency_ms": elapsed,
            "models": models,
            "model": model or (models[0] if models else ""),
        }
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"ok": False, "host": host, "error": str(e), "models": []}


def doctor_report(*, host: str = "", model: str = "", ai_mode: str = "dynamic") -> dict[str, Any]:
    # Always rescan live ports; do not trust a stale preferred host.
    resolved = detect_llama_host(host, rescan=True)
    ping = ping_llama(resolved, model=model)
    if not ping.get("ok"):
        # Prefer 8765 in the status line when Arborito is the intended companion.
        alt = detect_llama_host("", rescan=True)
        if alt != resolved:
            ping2 = ping_llama(alt, model=model)
            if ping2.get("ok"):
                resolved, ping = alt, ping2
    hint = None
    if not ping.get("ok"):
        hint = (
            "Arborito alone is not enough: open Sage and load a model "
            "(llama-server on 127.0.0.1:8765), or start llama-server on :8080."
        )
    return {
        "ai_mode": ai_mode,
        "llama_host": resolved,
        "llama_model": model or ping.get("model") or os.environ.get("LLAMA_CPP_MODEL") or "",
        "llama_ok": ping.get("ok"),
        "latency_ms": ping.get("latency_ms"),
        "models": ping.get("models") or [],
        "error": ping.get("error"),
        "hint": hint,
    }

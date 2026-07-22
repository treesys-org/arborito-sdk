"""Read-only Nostr client for Arborito public trees (bundle v2 + share codes)."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .errors import ArboritoError
from .nostr_protocol import (
    KIND_BUNDLE_CHUNK_JSON,
    KIND_BUNDLE_HEADER,
    KIND_TREE_CODE,
    KIND_UNIVERSE_REVOKE,
    bundle_header_d_tag,
    bundle_main_chunk_d_tag,
    forum_pack_chunk_d_tag,
    forum_pack_d_tag,
    has_arb_root,
    lesson_chunk_d_tag,
    normalize_tree_share_code,
    revoke_d_tag,
    search_pack_chunk_d_tag,
    search_pack_d_tag,
    tag_value,
    tree_code_d_tag,
)
from .nostr_relays import default_nostr_relays, merge_nostr_relay_urls, normalize_nostr_relay_urls

_WEBSOCKET_INSTALL_HINT = (
    "websocket-client is required for Nostr loads.\n"
    "Fix: pip install 'websocket-client>=1.7.0'\n"
    "Or reinstall the SDK so pip pulls dependencies:\n"
    "  pip install --force-reinstall -e /path/to/arborito-sdk"
)


def require_websocket_client():
    """Raise ArboritoError when the Nostr WebSocket dependency is missing."""
    global websocket
    try:
        import websocket as ws

        websocket = ws
        return ws
    except ImportError as exc:
        raise ArboritoError(
            "NOSTR_UNAVAILABLE",
            f"{_WEBSOCKET_INSTALL_HINT}\nDetail: {exc}",
        ) from exc


try:
    import websocket
except ImportError:  # pragma: no cover
    websocket = None  # type: ignore[assignment]

DEFAULT_QUERY_TIMEOUT = 4.0
FAST_RELAY_TIMEOUT = 2.5
CONNECT_TIMEOUT = 0.8
PROBE_CONNECT_TIMEOUT = 0.6
MAX_LOAD_WALL_SEC = 22.0
RELAY_COOLDOWN_SEC = [4.0, 15.0, 60.0, 180.0]


def _references_event_root(event: dict[str, Any], root_id: str) -> bool:
    rid = str(root_id or "")
    if not rid:
        return False
    for row in event.get("tags") or []:
        if isinstance(row, list) and len(row) >= 2 and row[0] == "e" and str(row[1]) == rid:
            return True
    return False


class NostrClient:
    def __init__(
        self,
        relays: list[str] | None = None,
        *,
        query_timeout: float = DEFAULT_QUERY_TIMEOUT,
        hints_only: bool = False,
    ):
        if websocket is None:
            require_websocket_client()
        extra_norm = normalize_nostr_relay_urls(relays)
        if hints_only and extra_norm:
            self.relays = extra_norm
            self._preferred_relays = list(extra_norm)
        else:
            self.relays = default_nostr_relays(extra=relays)
            self._preferred_relays = extra_norm if extra_norm else []
        if not self.relays:
            raise ArboritoError("NOSTR_RELAYS_REQUIRED", "No Nostr relays configured.")
        self.query_timeout = query_timeout
        self.last_bundle_diag: dict[str, Any] = {}
        self._bundle_cache: dict[str, dict[str, Any]] = {}
        self._relay_health: dict[str, dict[str, float | int]] = {}

    def _relay_live(self, relay: str) -> bool:
        h = self._relay_health.get(relay)
        if not h:
            return True
        return time.time() >= float(h.get("until", 0))

    def _filter_live_relays(self, relays: list[str]) -> list[str]:
        return [r for r in relays if r and self._relay_live(r)]

    def _pick_primary_relay(self, relays: list[str] | None) -> list[str]:
        live = self._filter_live_relays(list(relays or []))
        return live[:1]

    def _note_relay_fail(self, relay: str) -> None:
        prev = self._relay_health.get(relay, {"fails": 0, "until": 0.0})
        fails = int(prev.get("fails", 0)) + 1
        idx = min(fails - 1, len(RELAY_COOLDOWN_SEC) - 1)
        self._relay_health[relay] = {"fails": fails, "until": time.time() + RELAY_COOLDOWN_SEC[idx]}

    def _note_relay_ok(self, relay: str) -> None:
        self._relay_health.pop(relay, None)

    def _cache_key(self, pub: str, universe_id: str) -> str:
        return f"{pub.lower()}:{universe_id}"

    def _primary_relay(self) -> str | None:
        return self._preferred_relays[0] if self._preferred_relays else None

    def _relay_tiers(self, relays: list[str] | None = None) -> list[list[str]]:
        base = list(relays or self.relays)
        tiers: list[list[str]] = []
        seen: set[str] = set()

        def add_tier(urls: list[str]) -> None:
            row = [u for u in urls if u and u not in seen]
            if not row:
                return
            for u in row:
                seen.add(u)
            tiers.append(row)

        primary = self._primary_relay()
        if primary:
            add_tier([primary])
            add_tier(self._preferred_relays[1:4])
        add_tier(base[:2])
        add_tier(base)
        return tiers

    def relay_health_snapshot(self) -> dict[str, Any]:
        """Diagnostics: relays currently in cooldown after connect/query failures."""
        now = time.time()
        cooling = {
            relay: max(0.0, float(h.get("until", 0)) - now)
            for relay, h in self._relay_health.items()
            if float(h.get("until", 0)) > now
        }
        return {"cooling": cooling, "count": len(cooling)}

    def _probe_relays(self, relays: list[str] | None = None) -> None:
        """Fast connect probe so dead relays enter cooldown before bundle queries."""
        targets = self._filter_live_relays(list(relays or self.relays))
        for relay in targets[:4]:
            if not self._relay_live(relay):
                continue
            try:
                ws = websocket.create_connection(relay, timeout=PROBE_CONNECT_TIMEOUT)
            except Exception:
                self._note_relay_fail(relay)
            else:
                try:
                    ws.close()
                except Exception:
                    pass
                self._note_relay_ok(relay)

    def get_bundle_header(self, pub: str, universe_id: str) -> dict[str, Any] | None:
        pub = str(pub).lower()
        return self.get(
            {
                "kinds": [KIND_BUNDLE_HEADER],
                "authors": [pub],
                "#d": [bundle_header_d_tag(pub, universe_id)],
                "limit": 1,
            },
            timeout=min(self.query_timeout, FAST_RELAY_TIMEOUT),
            relays=self._hint_relays(),
        )

    def _req_once(self, relay: str, filters: list[dict[str, Any]], timeout: float) -> list[dict[str, Any]]:
        if not self._relay_live(relay):
            return []
        sub = f"arb-{int(time.time() * 1000)}"
        events: list[dict[str, Any]] = []
        connect_t = min(CONNECT_TIMEOUT, timeout)
        try:
            ws = websocket.create_connection(relay, timeout=connect_t)
        except Exception:
            self._note_relay_fail(relay)
            return []
        try:
            ws.settimeout(timeout)
            ws.send(json.dumps(["REQ", sub, *filters]))
            deadline = time.time() + timeout
            while time.time() < deadline:
                remaining = max(0.35, deadline - time.time())
                ws.settimeout(remaining)
                try:
                    raw = ws.recv()
                except Exception:
                    break
                if not raw:
                    break
                msg = json.loads(raw)
                if not isinstance(msg, list) or len(msg) < 2:
                    continue
                if msg[0] == "EVENT" and msg[1] == sub and isinstance(msg[2], dict):
                    events.append(msg[2])
                elif msg[0] == "EOSE" and msg[1] == sub:
                    break
            self._note_relay_ok(relay)
        except Exception:
            self._note_relay_fail(relay)
        finally:
            try:
                ws.close()
            except Exception:
                pass
        return events

    def _run_pool_queries(
        self,
        jobs: list[tuple[str, list[dict[str, Any]], float]],
    ) -> list[list[dict[str, Any]]]:
        if not jobs:
            return []
        workers = max(1, min(len(jobs), 8))
        pool = ThreadPoolExecutor(max_workers=workers)
        futs = [pool.submit(self._req_once, relay, filters, t) for relay, filters, t in jobs]
        max_wait = max(t for _, _, t in jobs) + 1.0
        out: list[list[dict[str, Any]]] = []
        try:
            for fut in as_completed(futs, timeout=max_wait):
                try:
                    out.append(fut.result())
                except Exception:
                    continue
        except TimeoutError:
            pass
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return out

    def get(
        self,
        filter_obj: dict[str, Any],
        *,
        timeout: float | None = None,
        relays: list[str] | None = None,
    ) -> dict[str, Any] | None:
        t = timeout if timeout is not None else self.query_timeout
        tiers = self._relay_tiers(relays)
        if not tiers:
            return None
        for tier_idx, tier in enumerate(tiers):
            live = self._filter_live_relays(tier)
            if not live:
                continue
            use_t = min(t, FAST_RELAY_TIMEOUT) if tier_idx == 0 else t
            if len(live) == 1:
                batches = [self._req_once(live[0], [filter_obj], use_t)]
            else:
                jobs = [(relay, [filter_obj], use_t) for relay in live]
                batches = self._run_pool_queries(jobs)
            for batch in batches:
                if batch:
                    return max(batch, key=lambda e: int(e.get("created_at") or 0))
        return None

    def query(
        self,
        filters: list[dict[str, Any]],
        *,
        timeout: float | None = None,
        relays: list[str] | None = None,
        tiered: bool = True,
    ) -> list[dict[str, Any]]:
        t = timeout if timeout is not None else self.query_timeout
        if not tiered:
            targets = relays or self.relays
            if not targets:
                return []
            jobs = [(relay, filters, t) for relay in targets]
            merged: dict[str, dict[str, Any]] = {}
            for batch in self._run_pool_queries(jobs):
                for ev in batch:
                    eid = str(ev.get("id") or "")
                    if eid:
                        merged[eid] = ev
            return sorted(merged.values(), key=lambda e: int(e.get("created_at") or 0), reverse=True)

        for tier_idx, tier in enumerate(self._relay_tiers(relays)):
            live = self._filter_live_relays(tier)
            if not live:
                continue
            use_t = min(t, FAST_RELAY_TIMEOUT) if tier_idx == 0 else t
            merged: dict[str, dict[str, Any]] = {}
            jobs = [(relay, filters, use_t) for relay in live]
            for batch in self._run_pool_queries(jobs):
                for ev in batch:
                    eid = str(ev.get("id") or "")
                    if eid:
                        merged[eid] = ev
            if merged:
                return sorted(merged.values(), key=lambda e: int(e.get("created_at") or 0), reverse=True)
        return []

    def resolve_share_code(self, code: str) -> dict[str, Any] | None:
        """Resolve a share code with first-author-wins semantics (match Arborito)."""
        norm = normalize_tree_share_code(code)
        if not norm:
            return None
        evs = self.query(
            [{"kinds": [KIND_TREE_CODE], "#d": [tree_code_d_tag(norm)], "limit": 40}],
            timeout=8.0,
        )
        newest_by_author: dict[str, dict[str, Any]] = {}
        first_author: str | None = None
        first_at = float("inf")
        for ev in evs or []:
            pk = str(ev.get("pubkey") or "").lower()
            if not pk:
                continue
            prev = newest_by_author.get(pk)
            if not prev or int(ev.get("created_at") or 0) > int(prev.get("created_at") or 0):
                newest_by_author[pk] = ev
            try:
                body = json.loads(ev.get("content") or "null")
            except json.JSONDecodeError:
                continue
            if not isinstance(body, dict):
                continue
            if str(body.get("kind") or "") != "tree_code":
                continue
            if str(body.get("ownerPub") or "").lower() != pk:
                continue
            body_norm = normalize_tree_share_code(str(body.get("code") or ""))
            if body_norm != norm and str(body.get("code") or "") != str(code):
                continue
            at = int(ev.get("created_at") or 0)
            if at < first_at:
                first_at = at
                first_author = pk
        if not first_author:
            return None
        ev = newest_by_author.get(first_author)
        if not ev:
            return None
        try:
            body = json.loads(ev.get("content") or "null")
        except json.JSONDecodeError:
            return None
        if not isinstance(body, dict) or body.get("revoked"):
            return None
        owner = str(body.get("ownerPub") or ev.get("pubkey") or "").lower()
        if owner != str(ev.get("pubkey") or "").lower():
            return None
        uid = str(body.get("universeId") or "").strip()
        if not owner or not uid:
            return None
        if self.is_universe_revoked(owner, uid):
            return None
        relays = body.get("recommendedRelays")
        extra = relays if isinstance(relays, list) else None
        return {
            "pub": owner,
            "universe_id": uid,
            "share_code": norm,
            "recommended_relays": extra or [],
        }

    def is_universe_revoked(self, pub: str, universe_id: str) -> bool:
        ev = self.get(
            {
                "kinds": [KIND_UNIVERSE_REVOKE],
                "authors": [pub],
                "#d": [revoke_d_tag(pub, universe_id)],
                "limit": 1,
            },
            timeout=3.0,
        )
        if not ev or str(ev.get("pubkey") or "").lower() != pub.lower():
            return False
        try:
            body = json.loads(ev.get("content") or "null")
        except json.JSONDecodeError:
            return False
        return (
            isinstance(body, dict)
            and str(body.get("kind") or "") == "revoke_universe"
            and str(body.get("universeId") or "") == universe_id
            and str(body.get("ownerPub") or "").lower() == pub.lower()
        )

    def _hint_relays(self) -> list[str]:
        if self._preferred_relays:
            return self._preferred_relays[: max(1, min(4, len(self._preferred_relays)))]
        return self.relays[: max(1, min(2, len(self.relays)))]

    def _chunk_query_relays(self, relays: list[str] | None) -> list[str]:
        if relays:
            return relays
        if self._preferred_relays:
            return merge_nostr_relay_urls(self._preferred_relays, self.relays)[
                : max(1, min(6, len(self.relays) + len(self._preferred_relays)))
            ]
        return self.relays

    def _fetch_chunks_by_d_parallel(
        self,
        *,
        pub: str,
        universe_id: str,
        chunk_count: int,
        timeout: float,
        relays: list[str],
        since: int | None,
        missing: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        indices = list(missing if missing is not None else range(chunk_count))
        live = self._filter_live_relays(list(relays or []))
        if not indices or not live:
            return []
        since_val = max(0, int(since or 0))
        base_since: dict[str, Any] = {"since": since_val} if since_val else {}
        use_t = min(timeout, FAST_RELAY_TIMEOUT)

        def fetch_idx(idx: int) -> dict[str, Any] | None:
            filt: dict[str, Any] = {
                "kinds": [KIND_BUNDLE_CHUNK_JSON],
                "authors": [pub],
                "#d": [bundle_main_chunk_d_tag(pub, universe_id, idx)],
                "limit": 1,
                **base_since,
            }
            if len(live) == 1:
                batch = self._req_once(live[0], [filt], use_t)
                return batch[0] if batch else None
            jobs = [(relay, [filt], use_t) for relay in live[:3]]
            for batch in self._run_pool_queries(jobs):
                if batch:
                    return batch[0]
            return None

        workers = max(1, min(len(indices), 8))
        pool = ThreadPoolExecutor(max_workers=workers)
        out: list[dict[str, Any]] = []
        try:
            futs = [pool.submit(fetch_idx, idx) for idx in indices]
            pool_wait = use_t + min(2.0, 0.8 + 0.35 * len(indices))
            for fut in as_completed(futs, timeout=pool_wait):
                try:
                    ev = fut.result()
                except Exception:
                    continue
                if ev:
                    out.append(ev)
        except TimeoutError:
            pass
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return out

    def _fetch_main_chunk_events(
        self,
        *,
        pub: str,
        universe_id: str,
        header_id: str,
        chunk_count: int,
        timeout: float,
        relays: list[str] | None,
        since: int | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        targets = self._filter_live_relays(self._chunk_query_relays(relays))
        if not targets:
            return [], "none"

        d_events = self._fetch_chunks_by_d_parallel(
            pub=pub,
            universe_id=universe_id,
            chunk_count=chunk_count,
            timeout=timeout,
            relays=targets,
            since=since,
        )
        if len(d_events) >= chunk_count:
            return d_events, "#d"

        since_val = max(0, int(since or 0))
        base_since: dict[str, Any] = {"since": since_val} if since_val else {}
        primary = self._pick_primary_relay(targets) or targets[:1]

        filt_e: dict[str, Any] = {
            "kinds": [KIND_BUNDLE_CHUNK_JSON],
            "authors": [pub],
            "#e": [header_id],
            "limit": min(8000, chunk_count + 50),
            **base_since,
        }
        events = self.query(filt_e, timeout=timeout, relays=targets)
        if events:
            return events, "#e"

        have_ids = {str(ev.get("id") or "") for ev in d_events}
        parts, _ = self._parts_from_chunk_events(
            d_events, pub=pub, universe_id=universe_id, chunk_count=chunk_count
        )
        missing = [i for i, p in enumerate(parts) if p is None]
        if missing:
            extra = self._fetch_chunks_by_d_parallel(
                pub=pub,
                universe_id=universe_id,
                chunk_count=chunk_count,
                timeout=timeout,
                relays=targets,
                since=since,
                missing=missing,
            )
            for ev in extra:
                eid = str(ev.get("id") or "")
                if eid and eid not in have_ids:
                    d_events.append(ev)
                    have_ids.add(eid)
        if d_events and len(d_events) >= chunk_count:
            return d_events, "#d"

        filt_broad: dict[str, Any] = {
            "kinds": [KIND_BUNDLE_CHUNK_JSON],
            "authors": [pub],
            "limit": min(8000, chunk_count + 200),
            **base_since,
        }
        broad = self.query(filt_broad, timeout=timeout, relays=targets)
        matched = [ev for ev in broad if _references_event_root(ev, header_id)]
        if matched:
            return matched, "authors+client-e"
        return d_events, "#d" if d_events else "authors+client-e"

    def _parts_from_chunk_events(
        self,
        events: list[dict[str, Any]],
        *,
        pub: str,
        universe_id: str,
        chunk_count: int,
    ) -> tuple[list[str | None], dict[str, int]]:
        parts: list[str | None] = [None] * chunk_count
        stats = {"events_seen": len(events), "events_arb": 0, "events_indexed": 0}
        for ev in events:
            if str(ev.get("pubkey") or "").lower() != pub:
                continue
            if not has_arb_root(ev, pub, universe_id):
                continue
            stats["events_arb"] += 1
            idx_raw = tag_value(ev, "i")
            try:
                idx = int(idx_raw) if idx_raw is not None else -1
            except ValueError:
                idx = -1
            if 0 <= idx < chunk_count:
                parts[idx] = str(ev.get("content") or "")
                stats["events_indexed"] += 1
        return parts, stats

    def diagnose_bundle_load(
        self,
        pub: str,
        universe_id: str,
        *,
        header: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        pub = str(pub).lower()
        diag: dict[str, Any] = {
            "pub": pub,
            "universe_id": universe_id,
            "relays": list(self.relays),
            "hint_relays": self._hint_relays(),
            "stage": "start",
        }
        hdr = header
        if not hdr:
            hdr = self.get(
                {
                    "kinds": [KIND_BUNDLE_HEADER],
                    "authors": [pub],
                    "#d": [bundle_header_d_tag(pub, universe_id)],
                    "limit": 1,
                },
                timeout=self.query_timeout,
                relays=self._hint_relays(),
            )
        if not hdr:
            diag["stage"] = "no_header"
            return diag
        diag["header_id"] = str(hdr.get("id") or "")[:16]
        try:
            meta = json.loads(hdr.get("content") or "null")
        except json.JSONDecodeError:
            diag["stage"] = "bad_header_json"
            return diag
        chunk_count = max(0, int(meta.get("chunkCount") or 0)) if isinstance(meta, dict) else 0
        diag["chunk_count"] = chunk_count
        if not chunk_count:
            diag["stage"] = "zero_chunk_count"
            return diag
        events, strategy = self._fetch_main_chunk_events(
            pub=pub,
            universe_id=universe_id,
            header_id=str(hdr["id"]),
            chunk_count=chunk_count,
            timeout=self.query_timeout,
            relays=self._chunk_query_relays(self._hint_relays()),
            since=None,
        )
        diag["query_strategy"] = strategy
        parts, stats = self._parts_from_chunk_events(
            events, pub=pub, universe_id=universe_id, chunk_count=chunk_count
        )
        diag.update(stats)
        have = sum(1 for p in parts if p is not None)
        diag["chunks_have"] = have
        missing = [i for i, p in enumerate(parts) if p is None]
        diag["chunks_missing"] = len(missing)
        diag["missing_sample"] = missing[:8]
        diag["stage"] = "ok" if not missing else "chunks_incomplete"
        return diag

    def load_universe_bundle(
        self,
        pub: str,
        universe_id: str,
        *,
        header: dict[str, Any] | None = None,
        skip_revoke_check: bool = False,
    ) -> dict[str, Any] | None:
        pub = str(pub).lower()
        self.last_bundle_diag = {"stage": "start", "pub": pub, "universe_id": universe_id}
        if not skip_revoke_check and self.is_universe_revoked(pub, universe_id):
            raise ArboritoError("NOSTR_REVOKED", "This public tree was retracted by the publisher.")

        hdr = header
        if not hdr:
            hdr = self.get(
                {
                    "kinds": [KIND_BUNDLE_HEADER],
                    "authors": [pub],
                    "#d": [bundle_header_d_tag(pub, universe_id)],
                    "limit": 1,
                },
                timeout=self.query_timeout,
                relays=self._hint_relays(),
            )
        if not hdr or str(hdr.get("pubkey") or "").lower() != pub:
            self.last_bundle_diag = self.diagnose_bundle_load(pub, universe_id, header=hdr)
            self.last_bundle_diag["stage"] = "no_header"
            return None
        try:
            meta = json.loads(hdr.get("content") or "null")
        except json.JSONDecodeError:
            self.last_bundle_diag = {"stage": "bad_header_json", "header_id": str(hdr.get("id") or "")[:16]}
            return None
        if isinstance(meta, dict) and meta.get("revoked"):
            raise ArboritoError("NOSTR_REVOKED", "This public tree was retracted by the publisher.")
        chunk_count = max(0, int(meta.get("chunkCount") or 0)) if isinstance(meta, dict) else 0
        if not chunk_count:
            self.last_bundle_diag = {"stage": "zero_chunk_count", "header_id": str(hdr.get("id") or "")[:16]}
            return None

        header_id = str(hdr["id"])
        # Match Arborito: do not filter chunks with `since` (header can be newer
        # than chunks after republish / clock skew).
        since = None
        cache_key = self._cache_key(pub, universe_id)
        hdr_stamp = str(meta.get("updatedAt") or "") if isinstance(meta, dict) else ""
        cached = self._bundle_cache.get(cache_key)
        if cached and cached.get("_cache_stamp") == f"{header_id}:{hdr_stamp}":
            self.last_bundle_diag = {"stage": "ok", "chunk_count": chunk_count, "query_strategy": "cache"}
            return cached["bundle"]

        parts: list[str | None] = [None] * chunk_count
        last_stats: dict[str, Any] = {}
        self._probe_relays(self._hint_relays())
        deadline = time.time() + MAX_LOAD_WALL_SEC
        hint_live = self._filter_live_relays(self._chunk_query_relays(self._hint_relays()))
        relay_passes: list[tuple[float, list[str] | None]] = [
            (FAST_RELAY_TIMEOUT, hint_live[:2] or None),
            (self.query_timeout, hint_live[:4] or None),
        ]
        all_live = self._filter_live_relays(self.relays)
        if len(all_live) > len(hint_live):
            relay_passes.append((self.query_timeout, all_live[:6] or None))
        for timeout, subset in relay_passes:
            if time.time() >= deadline:
                break
            if not subset:
                continue
            use_timeout = min(timeout, max(0.6, deadline - time.time()))
            events, strategy = self._fetch_main_chunk_events(
                pub=pub,
                universe_id=universe_id,
                header_id=header_id,
                chunk_count=chunk_count,
                timeout=use_timeout,
                relays=subset,
                since=since,
            )
            again, stats = self._parts_from_chunk_events(
                events, pub=pub, universe_id=universe_id, chunk_count=chunk_count
            )
            last_stats = {**stats, "query_strategy": strategy, "relays": subset}
            for i in range(chunk_count):
                if parts[i] is None and again[i] is not None:
                    parts[i] = again[i]
            if all(p is not None for p in parts):
                break

        if any(p is None for p in parts):
            missing = [i for i, p in enumerate(parts) if p is None]
            self.last_bundle_diag = {
                "stage": "chunks_incomplete",
                "header_id": header_id[:16],
                "chunk_count": chunk_count,
                "chunks_have": chunk_count - len(missing),
                "chunks_missing": len(missing),
                "missing_sample": missing[:8],
                "relays": list(self.relays),
                "hint_relays": self._hint_relays(),
                **last_stats,
            }
            return None
        try:
            bundle = json.loads("".join(parts))  # type: ignore[arg-type]
        except json.JSONDecodeError:
            self.last_bundle_diag = {
                "stage": "bundle_json_error",
                "header_id": header_id[:16],
                "chunk_count": chunk_count,
                **last_stats,
            }
            return None
        if not isinstance(bundle, dict):
            self.last_bundle_diag = {"stage": "bundle_not_object", **last_stats}
            return None
        bundle.setdefault("meta", {})
        if isinstance(bundle["meta"], dict):
            hdr_code = str(meta.get("shareCode") or "").strip() if isinstance(meta, dict) else ""
            if hdr_code and not str(bundle["meta"].get("shareCode") or "").strip():
                bundle["meta"]["shareCode"] = hdr_code
        bundle["_nostr_header"] = meta
        self._bundle_cache[cache_key] = {"bundle": bundle, "_cache_stamp": f"{header_id}:{hdr_stamp}"}
        self.last_bundle_diag = {
            "stage": "ok",
            "chunk_count": chunk_count,
            "query_strategy": last_stats.get("query_strategy"),
        }
        return bundle

    def load_lesson_chunks(
        self,
        pub: str,
        universe_id: str,
        content_keys: list[str],
        *,
        timeout: float = 5.0,
    ) -> dict[str, dict[str, Any]]:
        keys = [str(k) for k in content_keys if str(k).strip()]
        if not keys:
            return {}
        out: dict[str, dict[str, Any]] = {}

        def fetch_one(key: str) -> tuple[str, dict[str, Any] | None]:
            return key, self.load_lesson_chunk(pub, universe_id, key)

        workers = max(1, min(len(keys), 8))
        pool = ThreadPoolExecutor(max_workers=workers)
        futs = [pool.submit(fetch_one, key) for key in keys]
        try:
            for fut in as_completed(futs, timeout=timeout + 2.0):
                try:
                    key, chunk = fut.result()
                except Exception:
                    continue
                if chunk:
                    out[key] = chunk
        except TimeoutError:
            pass
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return out

    def load_lesson_chunk(self, pub: str, universe_id: str, content_key: str) -> dict[str, Any] | None:
        targets = self._hint_relays()[:1] or self.relays[:1]
        key = str(content_key or "").strip()
        ev = self.get(
            {
                "kinds": [KIND_BUNDLE_CHUNK_JSON],
                "authors": [pub],
                "#d": [lesson_chunk_d_tag(pub, universe_id, key)],
                "limit": 1,
            },
            timeout=FAST_RELAY_TIMEOUT,
            relays=targets,
        )
        if not ev or str(ev.get("pubkey") or "").lower() != str(pub).lower():
            return None
        try:
            raw = json.loads(ev.get("content") or "null")
        except json.JSONDecodeError:
            return None
        if not isinstance(raw, dict):
            return None
        n = max(0, int(raw.get("contentParts") or 0) or 0)
        if not n:
            return raw
        parts: list[str | None] = [None] * n
        for i in range(n):
            pev = self.get(
                {
                    "kinds": [KIND_BUNDLE_CHUNK_JSON],
                    "authors": [pub],
                    "#d": [lesson_chunk_d_tag(pub, universe_id, f"{key}:p:{i}")],
                    "limit": 1,
                },
                timeout=FAST_RELAY_TIMEOUT,
                relays=targets,
            )
            if not pev or str(pev.get("pubkey") or "").lower() != str(pub).lower():
                return None
            raw_part = str(pev.get("content") or "")
            try:
                piece = json.loads(raw_part)
            except json.JSONDecodeError:
                parts[i] = raw_part
                continue
            if isinstance(piece, dict) and isinstance(piece.get("content"), str):
                # Legacy wrapped parts from early 0.1.7 builds.
                parts[i] = piece["content"]
            else:
                parts[i] = raw_part
        if any(p is None for p in parts):
            return None
        return {"content": "".join(parts)}  # type: ignore[arg-type]

    def load_snapshot_chunk(self, pub: str, universe_id: str, snapshot_key: str) -> dict[str, Any] | None:
        targets = self._hint_relays()[:1] or self.relays[:1]
        key = str(snapshot_key or "").strip()
        d = f"arborito:snap:{pub}:{universe_id}:{key}"
        ev = self.get(
            {
                "kinds": [KIND_BUNDLE_CHUNK_JSON],
                "authors": [pub],
                "#d": [d],
                "limit": 1,
            },
            timeout=FAST_RELAY_TIMEOUT,
            relays=targets,
        )
        if not ev or str(ev.get("pubkey") or "").lower() != str(pub).lower():
            return None
        try:
            raw = json.loads(ev.get("content") or "null")
        except json.JSONDecodeError:
            return None
        if not isinstance(raw, dict):
            return None
        n = max(0, int(raw.get("chunkCount") or 0) or 0)
        if not n:
            return raw
        parts: list[str | None] = [None] * n
        for i in range(n):
            pev = self.get(
                {
                    "kinds": [KIND_BUNDLE_CHUNK_JSON],
                    "authors": [pub],
                    "#d": [f"{d}:c:{i}"],
                    "limit": 1,
                },
                timeout=FAST_RELAY_TIMEOUT,
                relays=targets,
            )
            if not pev or str(pev.get("pubkey") or "").lower() != str(pub).lower():
                return None
            parts[i] = str(pev.get("content") or "")
        if any(p is None for p in parts):
            return None
        try:
            joined = json.loads("".join(parts))  # type: ignore[arg-type]
        except json.JSONDecodeError:
            return None
        return joined if isinstance(joined, dict) else None

    def load_search_pack(self, pub: str, universe_id: str) -> dict[str, Any] | None:
        targets = self._hint_relays()[:1] or self.relays[:1]
        ev = self.get(
            {
                "kinds": [KIND_BUNDLE_CHUNK_JSON],
                "authors": [pub],
                "#d": [search_pack_d_tag(pub, universe_id)],
                "limit": 1,
            },
            timeout=FAST_RELAY_TIMEOUT,
            relays=targets,
        )
        if not ev or str(ev.get("pubkey") or "").lower() != str(pub).lower():
            return None
        try:
            raw = json.loads(ev.get("content") or "null")
        except json.JSONDecodeError:
            return None
        if not isinstance(raw, dict):
            return None
        if isinstance(raw.get("entries"), list):
            return raw
        if raw.get("entriesJson") is not None:
            try:
                arr = json.loads(str(raw.get("entriesJson") or "[]"))
            except json.JSONDecodeError:
                arr = []
            return {"version": 1, "entries": arr if isinstance(arr, list) else []}
        n = max(0, int(raw.get("chunkCount") or 0) or 0)
        if not n:
            return None
        parts: list[str | None] = [None] * n
        for i in range(n):
            pev = self.get(
                {
                    "kinds": [KIND_BUNDLE_CHUNK_JSON],
                    "authors": [pub],
                    "#d": [search_pack_chunk_d_tag(pub, universe_id, i)],
                    "limit": 1,
                },
                timeout=FAST_RELAY_TIMEOUT,
                relays=targets,
            )
            if not pev or str(pev.get("pubkey") or "").lower() != str(pub).lower():
                return None
            parts[i] = str(pev.get("content") or "")
        if any(p is None for p in parts):
            return None
        try:
            joined = json.loads("".join(parts))  # type: ignore[arg-type]
        except json.JSONDecodeError:
            return None
        if not isinstance(joined, dict):
            return None
        if isinstance(joined.get("entries"), list):
            return joined
        if joined.get("entriesJson") is not None:
            try:
                arr = json.loads(str(joined.get("entriesJson") or "[]"))
            except json.JSONDecodeError:
                arr = []
            return {"version": 1, "entries": arr if isinstance(arr, list) else []}
        return None

    def load_forum_pack(self, pub: str, universe_id: str) -> dict[str, Any] | None:
        targets = self._hint_relays()[:1] or self.relays[:1]
        ev = self.get(
            {
                "kinds": [KIND_BUNDLE_CHUNK_JSON],
                "authors": [pub],
                "#d": [forum_pack_d_tag(pub, universe_id)],
                "limit": 1,
            },
            timeout=FAST_RELAY_TIMEOUT,
            relays=targets,
        )
        if not ev or str(ev.get("pubkey") or "").lower() != str(pub).lower():
            return None
        try:
            raw = json.loads(ev.get("content") or "null")
        except json.JSONDecodeError:
            return None
        if not isinstance(raw, dict):
            return None
        n = max(0, int(raw.get("chunkCount") or 0) or 0)
        if not n:
            return raw
        parts: list[str | None] = [None] * n
        for i in range(n):
            pev = self.get(
                {
                    "kinds": [KIND_BUNDLE_CHUNK_JSON],
                    "authors": [pub],
                    "#d": [forum_pack_chunk_d_tag(pub, universe_id, i)],
                    "limit": 1,
                },
                timeout=FAST_RELAY_TIMEOUT,
                relays=targets,
            )
            if not pev or str(pev.get("pubkey") or "").lower() != str(pub).lower():
                return None
            parts[i] = str(pev.get("content") or "")
        if any(p is None for p in parts):
            return None
        try:
            joined = json.loads("".join(parts))  # type: ignore[arg-type]
        except json.JSONDecodeError:
            return None
        return joined if isinstance(joined, dict) else None


def merge_client_relays(client: NostrClient, recommended: list[str] | None) -> NostrClient:
    if not recommended:
        return client
    merged = default_nostr_relays(extra=recommended)
    return NostrClient(merged, query_timeout=client.query_timeout, hints_only=True)


def format_bundle_diag(diag: dict[str, Any]) -> str:
    stage = str(diag.get("stage") or "?")
    if stage == "ok":
        return "ok"
    bits = [stage]
    if diag.get("chunk_count") is not None:
        bits.append(f"chunks {diag.get('chunks_have', '?')}/{diag.get('chunk_count')}")
    if diag.get("events_seen") is not None:
        bits.append(f"events={diag.get('events_seen')}")
    if diag.get("events_arb") is not None:
        bits.append(f"arb={diag.get('events_arb')}")
    if diag.get("query_strategy"):
        bits.append(f"via={diag['query_strategy']}")
    if diag.get("header_id"):
        bits.append(f"hdr={diag['header_id']}")
    if diag.get("missing_sample"):
        bits.append(f"faltan idx {diag['missing_sample']}")
    if diag.get("hint_relays"):
        bits.append(f"relay={diag['hint_relays'][0].split('//')[-1][:24]}")
    return ", ".join(str(b) for b in bits)

"""Publish signed Nostr events (bundles, account register)."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .bundle_publish import prepare_nostr_split_bundle_v2, split_utf8_chunks
from .nostr_protocol import (
    KIND_BUNDLE_CHUNK_JSON,
    KIND_BUNDLE_HEADER,
    KIND_TREE_CODE,
    KIND_USER_ACCOUNT_RECORD,
    NOSTR_CHUNK_CONTENT_MAX,
    TAG_APP,
    TAG_APP_VALUE,
    account_sync_login_d_tag,
    arb_root_tag,
    bundle_header_d_tag,
    bundle_main_chunk_d_tag,
    forum_pack_chunk_d_tag,
    forum_pack_d_tag,
    search_pack_chunk_d_tag,
    search_pack_d_tag,
    tree_code_d_tag,
)


def require_nostr_signing() -> None:
    """Signing is built-in (BIP-340); keep the name for callers that gate publish."""
    return


def sign_event(unsigned: dict[str, Any], priv_hex: str) -> dict[str, Any]:
    """Sign a NIP-01 event (BIP-340 Schnorr) — no native ``secp256k1`` package."""
    import hashlib
    import os

    from .bip340 import pubkey_gen, schnorr_sign

    priv = bytes.fromhex(str(priv_hex).strip().lower())
    if len(priv) != 32:
        raise ValueError("Nostr private key must be 32 bytes hex")
    pub = pubkey_gen(priv).hex()
    created_at = int(unsigned.get("created_at") or time.time())
    kind = int(unsigned["kind"])
    tags = list(unsigned.get("tags") or [])
    content = str(unsigned.get("content") or "")
    payload = json.dumps(
        [0, pub, created_at, kind, tags, content],
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    event_id = hashlib.sha256(payload).hexdigest()
    sig = schnorr_sign(bytes.fromhex(event_id), priv, os.urandom(32)).hex()
    return {
        "id": event_id,
        "pubkey": pub,
        "created_at": created_at,
        "kind": kind,
        "tags": tags,
        "content": content,
        "sig": sig,
    }


def _relay_accepted_event(raw: str, event_id: str) -> bool | None:
    """Parse a NIP-20 ``OK`` reply. ``None`` means the relay did not answer clearly."""
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(msg, list) or not msg:
        return None
    if str(msg[0]).upper() != "OK":
        return None
    if len(msg) < 3:
        return None
    if str(msg[1]) != str(event_id):
        return None
    return bool(msg[2])


def publish_event(client: Any, event: dict[str, Any]) -> bool:
    import websocket

    content = event.get("content")
    if isinstance(content, str) and len(content.encode("utf-8")) > NOSTR_CHUNK_CONTENT_MAX:
        raise RuntimeError(
            f"Nostr event content exceeds {NOSTR_CHUNK_CONTENT_MAX} UTF-8 bytes "
            f"(kind={event.get('kind')})"
        )
    payload = json.dumps(["EVENT", event])
    event_id = str(event.get("id") or "")
    relays = getattr(client, "relays", None) or []
    ok = False
    for relay in relays[:5]:
        try:
            ws = websocket.create_connection(relay, timeout=4.0)
            ws.send(payload)
            accepted: bool | None = None
            try:
                raw = ws.recv()
                accepted = _relay_accepted_event(raw, event_id) if event_id else None
            except Exception:
                accepted = None
            ws.close()
            if accepted is False:
                continue
            ok = True
            break
        except Exception:
            continue
    return ok


def publish_burst(client: Any, events: list[dict[str, Any]], concurrency: int = 5) -> int:
    if not events:
        return 0
    ok_count = 0
    workers = max(1, min(concurrency, len(events)))

    def one(ev: dict[str, Any]) -> bool:
        return publish_event(client, ev)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(one, ev) for ev in events]
        for fut in as_completed(futs):
            try:
                if fut.result():
                    ok_count += 1
            except Exception:
                pass
    return ok_count


def _require_burst(ok_count: int, events: list[dict[str, Any]], label: str) -> None:
    if ok_count < len(events):
        raise RuntimeError(
            f"Failed to publish {label} to relays ({ok_count}/{len(events)} accepted)"
        )


def _make_json_slot_event(
    pair: dict[str, str],
    universe_id: str,
    slot: str,
    key: str,
    obj: Any,
    *,
    created_at: int | None = None,
) -> dict[str, Any]:
    from .nostr_protocol import NOSTR_CHUNK_CONTENT_MAX

    ts = created_at if created_at is not None else int(time.time())
    if slot == "search" and key == "v1":
        d = search_pack_d_tag(pair["pub"], universe_id)
    elif slot == "forum" and key == "v1":
        d = forum_pack_d_tag(pair["pub"], universe_id)
    else:
        d = f"arborito:{slot}:{pair['pub']}:{universe_id}:{key}"
    content = json.dumps(obj if obj is not None else {}, ensure_ascii=False)
    if len(content.encode("utf-8")) > NOSTR_CHUNK_CONTENT_MAX:
        raise RuntimeError(
            f"Nostr {slot}/{key} payload exceeds {NOSTR_CHUNK_CONTENT_MAX} UTF-8 bytes"
        )
    return sign_event(
        {
            "kind": KIND_BUNDLE_CHUNK_JSON,
            "created_at": ts,
            "tags": [["d", d], arb_root_tag(pair["pub"], universe_id), ["slot", slot]],
            "content": content,
        },
        pair["priv"],
    )


def publish_bundle(
    client: Any,
    pair: dict[str, str],
    universe_id: str,
    bundle: dict[str, Any],
    *,
    include_forum: bool = True,
) -> dict[str, Any]:
    """Publish arborito-bundle v2 to Nostr relays."""
    split = prepare_nostr_split_bundle_v2(bundle, include_forum=include_forum)
    slim = split["slimBundle"]
    main_json = json.dumps(slim, ensure_ascii=False, separators=(",", ":"))
    parts = split_utf8_chunks(main_json)
    ts = int(time.time())
    meta = {
        "v": 3,
        "chunkCount": len(parts),
        "title": (slim.get("meta") or {}).get("title") or "Arborito",
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "format": slim.get("format") or "arborito-bundle",
        "shareCode": (slim.get("meta") or {}).get("shareCode"),
    }
    header = sign_event(
        {
            "kind": KIND_BUNDLE_HEADER,
            "created_at": ts,
            "tags": [
                ["d", bundle_header_d_tag(pair["pub"], universe_id)],
                arb_root_tag(pair["pub"], universe_id),
                [TAG_APP, TAG_APP_VALUE],
            ],
            "content": json.dumps(meta, ensure_ascii=False),
        },
        pair["priv"],
    )
    if not publish_event(client, header):
        raise RuntimeError("Failed to publish bundle header to relays")

    main_events = []
    for i, content in enumerate(parts):
        main_events.append(
            sign_event(
                {
                    "kind": KIND_BUNDLE_CHUNK_JSON,
                    "created_at": ts,
                    "tags": [
                        ["d", bundle_main_chunk_d_tag(pair["pub"], universe_id, i)],
                        ["e", header["id"], "", "root"],
                        ["i", str(i)],
                        ["n", str(len(parts))],
                        arb_root_tag(pair["pub"], universe_id),
                    ],
                    "content": content,
                },
                pair["priv"],
            )
        )
    _require_burst(publish_burst(client, main_events, concurrency=5), main_events, "main chunks")

    lesson_events = []
    for key, chunk in split["lessonChunks"].items():
        try:
            lesson_events.append(
                _make_json_slot_event(pair, universe_id, "lesson", key, chunk, created_at=ts)
            )
        except RuntimeError as exc:
            if "exceeds" not in str(exc):
                raise
            body = ""
            if isinstance(chunk, dict) and isinstance(chunk.get("content"), str):
                body = chunk["content"]
            else:
                body = json.dumps(chunk if chunk is not None else {}, ensure_ascii=False)
            # Raw UTF-8 parts — do not JSON-wrap (escaping would exceed the byte max).
            body_parts = split_utf8_chunks(body)
            lesson_events.append(
                _make_json_slot_event(
                    pair,
                    universe_id,
                    "lesson",
                    key,
                    {"contentParts": len(body_parts)},
                    created_at=ts,
                )
            )
            for i, content in enumerate(body_parts):
                lesson_events.append(
                    sign_event(
                        {
                            "kind": KIND_BUNDLE_CHUNK_JSON,
                            "created_at": ts,
                            "tags": [
                                ["d", f"arborito:lesson:{pair['pub']}:{universe_id}:{key}:p:{i}"],
                                arb_root_tag(pair["pub"], universe_id),
                                ["slot", "lesson"],
                                ["i", str(i)],
                                ["n", str(len(body_parts))],
                            ],
                            "content": content,
                        },
                        pair["priv"],
                    )
                )
    if lesson_events:
        _require_burst(
            publish_burst(client, lesson_events, concurrency=5), lesson_events, "lesson chunks"
        )

    snap_events = []
    for key, chunk in split["snapshotChunks"].items():
        try:
            snap_events.append(
                _make_json_slot_event(pair, universe_id, "snap", key, chunk, created_at=ts)
            )
        except RuntimeError as exc:
            if "exceeds" not in str(exc):
                raise
            text = json.dumps(chunk if chunk is not None else {}, ensure_ascii=False)
            snap_parts = split_utf8_chunks(text)
            snap_events.append(
                _make_json_slot_event(
                    pair,
                    universe_id,
                    "snap",
                    key,
                    {"version": 1, "chunkCount": len(snap_parts)},
                    created_at=ts,
                )
            )
            for i, content in enumerate(snap_parts):
                snap_events.append(
                    sign_event(
                        {
                            "kind": KIND_BUNDLE_CHUNK_JSON,
                            "created_at": ts,
                            "tags": [
                                [
                                    "d",
                                    f"arborito:snap:{pair['pub']}:{universe_id}:{key}:c:{i}",
                                ],
                                arb_root_tag(pair["pub"], universe_id),
                                ["slot", "snap"],
                                ["i", str(i)],
                                ["n", str(len(snap_parts))],
                            ],
                            "content": content,
                        },
                        pair["priv"],
                    )
                )
    if snap_events:
        _require_burst(
            publish_burst(client, snap_events, concurrency=5), snap_events, "snapshot chunks"
        )

    entries = split["searchPack"].get("entries") or []
    search_payload: dict[str, Any] = {"version": 1, "entries": entries}
    search_text = json.dumps(search_payload, ensure_ascii=False)
    search_parts = split_utf8_chunks(search_text)
    if len(search_parts) <= 1:
        search_ev = _make_json_slot_event(
            pair, universe_id, "search", "v1", search_payload, created_at=ts
        )
        if not publish_event(client, search_ev):
            raise RuntimeError("Failed to publish search pack to relays")
    else:
        manifest_ev = _make_json_slot_event(
            pair,
            universe_id,
            "search",
            "v1",
            {"version": 1, "chunkCount": len(search_parts)},
            created_at=ts,
        )
        if not publish_event(client, manifest_ev):
            raise RuntimeError("Failed to publish search pack manifest to relays")
        search_chunk_events = []
        for i, content in enumerate(search_parts):
            search_chunk_events.append(
                sign_event(
                    {
                        "kind": KIND_BUNDLE_CHUNK_JSON,
                        "created_at": ts,
                        "tags": [
                            ["d", search_pack_chunk_d_tag(pair["pub"], universe_id, i)],
                            arb_root_tag(pair["pub"], universe_id),
                            ["slot", "search"],
                            ["i", str(i)],
                            ["n", str(len(search_parts))],
                        ],
                        "content": content,
                    },
                    pair["priv"],
                )
            )
        _require_burst(
            publish_burst(client, search_chunk_events, concurrency=5),
            search_chunk_events,
            "search pack chunks",
        )

    if include_forum:
        fs = split["forumSplit"]
        messages = []
        for part in fs.get("messageParts") or []:
            if isinstance(part, list):
                messages.extend(part)
        forum_payload = {
            "version": 1,
            "threads": fs.get("threads") or [],
            "messages": messages,
            "moderationLog": fs.get("moderationLog") or [],
        }
        forum_text = json.dumps(forum_payload, ensure_ascii=False)
        forum_parts = split_utf8_chunks(forum_text)
        if len(forum_parts) <= 1:
            forum_ev = _make_json_slot_event(
                pair, universe_id, "forum", "v1", forum_payload, created_at=ts
            )
            if not publish_event(client, forum_ev):
                raise RuntimeError("Failed to publish forum pack to relays")
        else:
            manifest_ev = _make_json_slot_event(
                pair,
                universe_id,
                "forum",
                "v1",
                {"version": 1, "chunkCount": len(forum_parts)},
                created_at=ts,
            )
            if not publish_event(client, manifest_ev):
                raise RuntimeError("Failed to publish forum pack manifest to relays")
            forum_chunk_events = []
            for i, content in enumerate(forum_parts):
                forum_chunk_events.append(
                    sign_event(
                        {
                            "kind": KIND_BUNDLE_CHUNK_JSON,
                            "created_at": ts,
                            "tags": [
                                ["d", forum_pack_chunk_d_tag(pair["pub"], universe_id, i)],
                                arb_root_tag(pair["pub"], universe_id),
                                ["slot", "forum"],
                                ["i", str(i)],
                                ["n", str(len(forum_parts))],
                            ],
                            "content": content,
                        },
                        pair["priv"],
                    )
                )
            _require_burst(
                publish_burst(client, forum_chunk_events, concurrency=5),
                forum_chunk_events,
                "forum pack chunks",
            )

    return {"pub": pair["pub"], "universe_id": universe_id, "header_id": header["id"], "chunk_count": len(parts)}


def publish_tree_code_claim(
    client: Any,
    pair: dict[str, str],
    code: str,
    universe_id: str,
    *,
    relays: list[str] | None = None,
) -> bool:
    from .nostr_protocol import normalize_tree_share_code

    norm = normalize_tree_share_code(code) or code
    payload = {
        "kind": "tree_code",
        "code": norm,
        "universeId": universe_id,
        "ownerPub": pair["pub"],
        "at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
    }
    if relays:
        payload["recommendedRelays"] = relays
    ev = sign_event(
        {
            "kind": KIND_TREE_CODE,
            "created_at": int(time.time()),
            "tags": [["d", tree_code_d_tag(norm)], arb_root_tag(pair["pub"], universe_id), [TAG_APP, TAG_APP_VALUE]],
            "content": json.dumps(payload, ensure_ascii=False),
        },
        pair["priv"],
    )
    return publish_event(client, ev)


def build_sync_login_event(
    username: str,
    login_hash: str,
    signer_pub: str,
    signer_priv: str,
    *,
    credential: str,
    pow_bits: int,
    pow_nonce: str,
) -> dict[str, Any]:
    rec = {
        "v": 2,
        "hash": login_hash,
        "powBits": pow_bits,
        "powNonce": pow_nonce,
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
    }
    if credential:
        rec["credential"] = credential
    unsigned = {
        "kind": KIND_USER_ACCOUNT_RECORD,
        "created_at": int(time.time()),
        "tags": [
            [TAG_APP, TAG_APP_VALUE],
            ["d", account_sync_login_d_tag(username)],
        ],
        "content": json.dumps(rec, separators=(",", ":")),
    }
    return sign_event(unsigned, signer_priv)


def register_sync_login(
    client: Any,
    username: str,
    login_hash: str,
    signer_pair: dict[str, str],
    *,
    credential: str,
    pow_bits: int,
    pow_nonce: str,
) -> bool:
    ev = build_sync_login_event(
        username,
        login_hash,
        signer_pair["pub"],
        signer_pair["priv"],
        credential=credential,
        pow_bits=pow_bits,
        pow_nonce=pow_nonce,
    )
    return publish_event(client, ev)

"""Progress sync — local SM-2 memory + NIP-44 Care pull/push (KIND_USER_PROGRESS)."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Optional

from .cli_session import CliSession
from .nostr_protocol import (
    KIND_ACCOUNT_USER_PAIR_ESCROW,
    KIND_USER_PROGRESS,
    PRIVATE_TREE_NIP44_PLAINTEXT_MAX,
    TAG_APP,
    TAG_APP_VALUE,
    account_escrow_d_tag,
    arb_root_tag,
    has_arb_root,
)

_ONE_DAY_MS = 24 * 60 * 60 * 1000


def local_memory_progress(sess: CliSession) -> dict[str, Any]:
    mem = sess._data.get("memory") or {}
    if not isinstance(mem, dict):
        return {}
    prog = mem.get("local_progress") or mem.get("progress") or {}
    return prog if isinstance(prog, dict) else {}


def report_memory_sm2(
    prev: Optional[dict[str, Any]],
    quality: int,
    *,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """SM-2 spaced repetition (parity with Arborito ``srs-memory.js``)."""
    q = max(0, min(5, int(quality)))
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    item: dict[str, Any] = {
        "lvl": 0,
        "ease": 2.5,
        "interval": 0,
        "lastReview": 0,
        "dueDate": 0,
        "reviews": 0,
    }
    if isinstance(prev, dict):
        item.update(prev)
    item["reviews"] = int(item.get("reviews") or 0) + 1
    if q < 3:
        item["lvl"] = 0
        item["interval"] = 1
    else:
        lvl = int(item.get("lvl") or 0)
        if lvl == 0:
            item["interval"] = 1
        elif lvl == 1:
            item["interval"] = 6
        else:
            item["interval"] = int(round(float(item.get("interval") or 1) * float(item.get("ease") or 2.5)))
        item["lvl"] = lvl + 1
        ease = float(item.get("ease") or 2.5)
        ease = ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
        item["ease"] = max(1.3, ease)
    item["lastReview"] = now
    item["dueDate"] = now + int(item["interval"]) * _ONE_DAY_MS
    item["quality"] = q
    return item


def memory_status(item: Optional[dict[str, Any]], *, now_ms: int | None = None) -> dict[str, Any]:
    if not item:
        return {"health": 1.0, "isDue": False, "interval": 0}
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    due = int(item.get("dueDate") or 0)
    interval = int(item.get("interval") or 0)
    if now >= due:
        return {"health": 0.0, "isDue": True, "interval": interval}
    last = int(item.get("lastReview") or 0)
    total = max(1, due - last)
    elapsed = now - last
    health = 1.0 - (elapsed / total)
    if health < 0:
        health = 0.0
    return {"health": health, "isDue": False, "interval": interval}


def memory_due_ids(sess: CliSession, *, now_ms: int | None = None) -> list[str]:
    """Due reviews from local SM-2 rows (``dueDate``)."""
    prog = local_memory_progress(sess)
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    due: list[str] = []
    for lid, row in prog.items():
        if not isinstance(row, dict):
            continue
        if "dueDate" not in row:
            if row.get("isDue") or row.get("due"):
                due.append(str(lid))
            continue
        if now >= int(row.get("dueDate") or 0):
            due.append(str(lid))
    return due


def record_local_review(
    sess: CliSession,
    lesson_id: str,
    quality: int,
    *,
    now_ms: int | None = None,
) -> dict[str, Any]:
    mem = sess._data.setdefault("memory", {})
    if not isinstance(mem, dict):
        mem = {}
        sess._data["memory"] = mem
    prog = mem.setdefault("local_progress", {})
    if not isinstance(prog, dict):
        prog = {}
        mem["local_progress"] = prog
    prev = prog.get(lesson_id) if isinstance(prog.get(lesson_id), dict) else None
    item = report_memory_sm2(prev, quality, now_ms=now_ms)
    prog[lesson_id] = item
    sess.save()
    return item


def merge_memory_maps(local: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    """Newer row wins (``lastReview`` / ``updatedAt`` / ``last``)."""
    out = dict(local) if isinstance(local, dict) else {}
    if not isinstance(remote, dict):
        return out
    for nid, remote_row in remote.items():
        local_row = out.get(nid)
        if not isinstance(local_row, dict):
            if isinstance(remote_row, dict):
                out[str(nid)] = dict(remote_row)
            continue
        if not isinstance(remote_row, dict):
            continue
        remote_at = int(remote_row.get("updatedAt") or remote_row.get("last") or remote_row.get("lastReview") or 0)
        local_at = int(local_row.get("updatedAt") or local_row.get("last") or local_row.get("lastReview") or 0)
        out[str(nid)] = (
            {**local_row, **remote_row} if remote_at >= local_at else {**remote_row, **local_row}
        )
    return out


class ProgressUndecryptableError(RuntimeError):
    """KIND_USER_PROGRESS header(s) exist but ciphertext/parts could not be opened."""


def merge_game_data_buckets(local: Any, remote: Any) -> dict[str, Any]:
    out: dict[str, Any] = dict(local) if isinstance(local, dict) else {}
    if not isinstance(remote, dict):
        return out
    for game_id, remote_bucket in remote.items():
        if not isinstance(remote_bucket, dict):
            continue
        local_bucket = out.get(game_id)
        if not isinstance(local_bucket, dict):
            out[str(game_id)] = dict(remote_bucket)
            continue
        remote_updated = int(remote_bucket.get("_sys_updated") or 0)
        local_updated = int(local_bucket.get("_sys_updated") or 0)
        if remote_updated >= local_updated:
            out[str(game_id)] = {**local_bucket, **remote_bucket}
        else:
            out[str(game_id)] = {**remote_bucket, **local_bucket}
    return out


def merge_bookmark_maps(local: Any, remote: Any) -> dict[str, Any]:
    out: dict[str, Any] = dict(local) if isinstance(local, dict) else {}
    if not isinstance(remote, dict):
        return out
    for nid, remote_row in remote.items():
        if remote_row is None:
            continue
        local_row = out.get(nid)
        if local_row is None:
            out[str(nid)] = remote_row
            continue
        if isinstance(remote_row, dict) and isinstance(local_row, dict):
            remote_at = int(remote_row.get("updatedAt") or remote_row.get("ts") or 0)
            local_at = int(local_row.get("updatedAt") or local_row.get("ts") or 0)
            out[str(nid)] = (
                {**local_row, **remote_row} if remote_at >= local_at else {**remote_row, **local_row}
            )
    return out


_DEFAULT_AVATARS = frozenset({"👤", "🌱", ""})


def _profile_ts(value: Any) -> int:
    try:
        s = str(value or "")
        if not s:
            return 0
        v = s.replace("Z", "+00:00") if s.endswith("Z") else s
        return int(datetime.fromisoformat(v).timestamp() * 1000)
    except Exception:
        return 0


def merge_remote_gamification(local: Any, remote: Any) -> dict[str, Any]:
    """Parity with Arborito ``gamification-merge.js`` (max XP/streak; emoji by profileUpdatedAt)."""
    g: dict[str, Any] = dict(local) if isinstance(local, dict) else {}
    if not isinstance(remote, dict):
        return g
    if (remote.get("xp") or 0) > (g.get("xp") or 0):
        g["xp"] = remote.get("xp")
    g["dailyXP"] = max(int(g.get("dailyXP") or 0), int(remote.get("dailyXP") or 0))
    g["streak"] = max(int(g.get("streak") or 0), int(remote.get("streak") or 0))
    g["weeklyLumens"] = max(int(g.get("weeklyLumens") or 0), int(remote.get("weeklyLumens") or 0))
    g["streakShields"] = max(int(g.get("streakShields") or 0), int(remote.get("streakShields") or 0))
    g["lumensSpent"] = max(int(g.get("lumensSpent") or 0), int(remote.get("lumensSpent") or 0))
    g["arcadeDailyXP"] = max(int(g.get("arcadeDailyXP") or 0), int(remote.get("arcadeDailyXP") or 0))

    local_profile_at = _profile_ts(g.get("profileUpdatedAt"))
    remote_profile_at = _profile_ts(remote.get("profileUpdatedAt"))
    remote_profile_wins = remote_profile_at > 0 and remote_profile_at >= local_profile_at

    remote_username = str(remote.get("username") or "").strip()
    if remote_username and ((not g.get("username")) or remote_profile_wins):
        g["username"] = remote_username

    remote_avatar = str(remote.get("avatar") or "").strip()
    if remote_avatar:
        local_avatar = str(g.get("avatar") or "").strip()
        if local_avatar in _DEFAULT_AVATARS or remote_profile_wins or not local_avatar:
            g["avatar"] = remote_avatar
            if remote_profile_at > local_profile_at:
                g["profileUpdatedAt"] = remote.get("profileUpdatedAt")

    if remote.get("lastLoginDate") and (
        not g.get("lastLoginDate") or str(g.get("lastLoginDate")) < str(remote.get("lastLoginDate"))
    ):
        g["lastLoginDate"] = remote.get("lastLoginDate")
    if remote.get("lastStudyDate") and (
        not g.get("lastStudyDate") or str(g.get("lastStudyDate")) < str(remote.get("lastStudyDate"))
    ):
        g["lastStudyDate"] = remote.get("lastStudyDate")
    if remote.get("weeklyWeekKey"):
        g["weeklyWeekKey"] = remote.get("weeklyWeekKey")
    if remote.get("arcadeXpDay"):
        g["arcadeXpDay"] = remote.get("arcadeXpDay")

    if isinstance(remote.get("seeds"), list):
        by_id = {str(s.get("id")): s for s in (g.get("seeds") or []) if isinstance(s, dict) and s.get("id")}
        for s in remote["seeds"]:
            if isinstance(s, dict) and s.get("id"):
                by_id[str(s["id"])] = s
        g["seeds"] = list(by_id.values())

    if isinstance(remote.get("inventory"), list) and remote["inventory"]:
        seen = {str(x) for x in (g.get("inventory") or [])}
        inv = list(g.get("inventory") or [])
        for item in remote["inventory"]:
            k = str(item)
            if k not in seen:
                seen.add(k)
                inv.append(item)
        g["inventory"] = inv

    if isinstance(remote.get("gardenDecor"), dict):
        g["gardenDecor"] = {**(g.get("gardenDecor") or {}), **remote["gardenDecor"]}
    if isinstance(remote.get("quizXpAwarded"), dict):
        g["quizXpAwarded"] = {**(g.get("quizXpAwarded") or {}), **remote["quizXpAwarded"]}
    if isinstance(remote.get("rankingOptIn"), bool):
        g["rankingOptIn"] = bool(g.get("rankingOptIn")) or remote["rankingOptIn"]
    if remote.get("rankingAnonymous") is True:
        g["rankingAnonymous"] = True
    return g


def merge_progress_snapshots(local: Any, remote: Any) -> dict[str, Any]:
    """Rsync-style merge: lesson completions are a union; maps use newer-wins."""
    base = local if isinstance(local, dict) else {}
    rem = remote if isinstance(remote, dict) else {}
    local_progress = [str(x) for x in (base.get("progress") or [])] if isinstance(base.get("progress"), list) else []
    remote_progress = [str(x) for x in (rem.get("progress") or [])] if isinstance(rem.get("progress"), list) else []
    return {
        "v": 1,
        "progress": list(dict.fromkeys([*local_progress, *remote_progress])),
        "memory": merge_memory_maps(base.get("memory") or {}, rem.get("memory") or {}),
        "bookmarks": merge_bookmark_maps(base.get("bookmarks"), rem.get("bookmarks")),
        "gameData": merge_game_data_buckets(base.get("gameData"), rem.get("gameData")),
        "arcadeSaves": merge_game_data_buckets(base.get("arcadeSaves"), rem.get("arcadeSaves")),
        "gamification": merge_remote_gamification(base.get("gamification"), rem.get("gamification")),
    }


def _as_object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _sorted_object_fingerprint(obj: Any, row_stamp) -> list:
    o = _as_object(obj)
    return [[k, row_stamp(o[k])] for k in sorted(o.keys())]


def _stamp_memory_row(row: Any) -> Any:
    if not isinstance(row, dict):
        return row
    return {
        "updatedAt": int(row.get("updatedAt") or row.get("last") or row.get("lastReview") or 0),
        "ease": row.get("ease"),
        "interval": row.get("interval"),
        "reps": row.get("reps"),
        "lapses": row.get("lapses"),
        "due": row.get("due"),
        "state": row.get("state"),
    }


def _stamp_bookmark_row(row: Any) -> Any:
    if row is None:
        return None
    if not isinstance(row, dict):
        return row
    return {
        "updatedAt": int(row.get("updatedAt") or row.get("ts") or 0),
        "index": row.get("index"),
        "kind": row.get("kind"),
        "title": row.get("title"),
    }


def _stamp_game_bucket(bucket: Any) -> Any:
    if not isinstance(bucket, dict):
        return None
    return {"updated": int(bucket.get("_sys_updated") or 0), "keys": sorted(bucket.keys())}


def _stamp_gamification(g: Any) -> dict[str, Any]:
    x = _as_object(g)
    seeds = x.get("seeds") if isinstance(x.get("seeds"), list) else []
    inventory = x.get("inventory") if isinstance(x.get("inventory"), list) else []
    return {
        "avatar": str(x.get("avatar") or "").strip(),
        "username": str(x.get("username") or "").strip(),
        "profileUpdatedAt": str(x.get("profileUpdatedAt") or ""),
        "xp": int(x.get("xp") or 0),
        "dailyXP": int(x.get("dailyXP") or 0),
        "streak": int(x.get("streak") or 0),
        "weeklyLumens": int(x.get("weeklyLumens") or 0),
        "streakShields": int(x.get("streakShields") or 0),
        "lumensSpent": int(x.get("lumensSpent") or 0),
        "seeds": sorted(str(s.get("id")) for s in seeds if isinstance(s, dict) and s.get("id")),
        "inventory": sorted(str(i) for i in inventory),
    }


def fingerprint_progress_payload(data: Any) -> str:
    """Stable content identity (ignores top-level updatedAt / v)."""
    if not isinstance(data, dict):
        return ""
    progress = sorted(str(x) for x in (data.get("progress") or []) if str(x)) if isinstance(data.get("progress"), list) else []
    return json.dumps(
        {
            "progress": progress,
            "memory": _sorted_object_fingerprint(data.get("memory"), _stamp_memory_row),
            "bookmarks": _sorted_object_fingerprint(data.get("bookmarks"), _stamp_bookmark_row),
            "gameData": _sorted_object_fingerprint(data.get("gameData"), _stamp_game_bucket),
            "arcadeSaves": _sorted_object_fingerprint(data.get("arcadeSaves"), _stamp_game_bucket),
            "gamification": _stamp_gamification(data.get("gamification")),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def is_progress_payload_empty(data: Any) -> bool:
    if not isinstance(data, dict):
        return True
    if isinstance(data.get("progress"), list) and data["progress"]:
        return False
    if _as_object(data.get("memory")):
        return False
    if _as_object(data.get("bookmarks")):
        return False
    if _as_object(data.get("gameData")):
        return False
    if _as_object(data.get("arcadeSaves")):
        return False
    g = _as_object(data.get("gamification"))
    if int(g.get("xp") or 0) > 0:
        return False
    if int(g.get("streak") or 0) > 0:
        return False
    if int(g.get("weeklyLumens") or 0) > 0:
        return False
    avatar = str(g.get("avatar") or "").strip()
    if avatar and avatar not in ("👤", "🌱"):
        return False
    if str(g.get("username") or "").strip():
        return False
    if isinstance(g.get("seeds"), list) and g["seeds"]:
        return False
    if isinstance(g.get("inventory"), list) and g["inventory"]:
        return False
    return True


def should_publish_merged_progress(*, remote: Any, merged: Any) -> bool:
    """Publish only when merged content differs from remote (or remote missing)."""
    if is_progress_payload_empty(merged):
        return False
    if not isinstance(remote, dict):
        return True
    return fingerprint_progress_payload(merged) != fingerprint_progress_payload(remote)




def user_progress_d_tag(owner_pub: str, universe_id: str, user_pub: str) -> str:
    return f"arborito:progress:{owner_pub}:{universe_id}:{user_pub}"


def user_progress_part_d_tag(owner_pub: str, universe_id: str, user_pub: str, index: int) -> str:
    i = max(0, int(index) if index is not None else 0)
    return f"arborito:progress:{owner_pub}:{universe_id}:{user_pub}:p:{i}"


def _tag_value(event: dict[str, Any], name: str) -> str:
    for row in event.get("tags") or []:
        if isinstance(row, (list, tuple)) and len(row) >= 2 and str(row[0]) == name:
            return str(row[1])
    return ""


def list_escrow_blobs(client: Any, username: str) -> list[dict[str, Any]]:
    from .session_nostr import normalize_username

    u = normalize_username(username)
    if not u:
        return []
    try:
        evs = client.query(
            [
                {
                    "kinds": [KIND_ACCOUNT_USER_PAIR_ESCROW],
                    "#d": [account_escrow_d_tag(u)],
                    "limit": 20,
                }
            ],
            timeout=6.0,
        )
    except Exception:
        evs = []
    ranked = sorted(evs or [], key=lambda e: int(e.get("created_at") or 0), reverse=True)
    out: list[dict[str, Any]] = []
    for ev in ranked:
        try:
            blob = json.loads(ev.get("content") or "null")
        except json.JSONDecodeError:
            continue
        if isinstance(blob, dict):
            out.append(blob)
    return out


def publish_escrow_blob(client: Any, username: str, escrow: dict[str, Any], signer: dict[str, str]) -> bool:
    from .nostr_publish import publish_event, sign_event
    from .session_nostr import normalize_username

    u = normalize_username(username)
    if not u or not isinstance(escrow, dict) or not signer.get("priv"):
        return False
    ev = sign_event(
        {
            "kind": KIND_ACCOUNT_USER_PAIR_ESCROW,
            "created_at": int(time.time()),
            "tags": [
                [TAG_APP, TAG_APP_VALUE],
                ["d", account_escrow_d_tag(u)],
                ["u", u],
            ],
            "content": json.dumps(escrow, ensure_ascii=False, separators=(",", ":")),
        },
        signer["priv"],
    )
    return bool(publish_event(client, ev))


def restore_or_create_network_identity(
    client: Any,
    *,
    username: str,
    sync_secret: str,
    account_signer: dict[str, str],
) -> dict[str, str]:
    """Decrypt escrow or mint a new network pair and publish escrow."""
    from .account_escrow import decrypt_account_escrow, encrypt_account_escrow
    from .identity_store import create_network_pair, load_network_pair, save_network_pair

    cached = load_network_pair(username)
    if cached:
        return cached
    for blob in list_escrow_blobs(client, username):
        try:
            recovered = decrypt_account_escrow(blob, sync_secret)
        except ValueError:
            continue
        pair = recovered["identityPair"]
        save_network_pair(username, pair)
        return pair
    pair = create_network_pair()
    escrow = encrypt_account_escrow(username=username, identity_pair=pair, sync_secret=sync_secret)
    if not publish_escrow_blob(client, username, escrow, account_signer):
        raise RuntimeError("Could not publish network identity escrow to relays.")
    save_network_pair(username, pair)
    return pair


def build_progress_payload(memory: dict[str, Any], *, progress: Optional[list[str]] = None) -> dict[str, Any]:
    return {
        "v": 1,
        "updatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "progress": list(progress or []),
        "memory": memory if isinstance(memory, dict) else {},
        "bookmarks": {},
        "gamification": {},
        "gameData": {},
        "arcadeSaves": {},
    }


def list_user_progress_records(
    client: Any,
    *,
    owner_pub: str,
    universe_id: str,
    user_pub: str,
) -> list[dict[str, Any]]:
    d = user_progress_d_tag(owner_pub, universe_id, user_pub)
    filters = [
        {
            "kinds": [KIND_USER_PROGRESS],
            "authors": [str(user_pub)],
            "#d": [d],
            "limit": 20,
        },
        {
            "kinds": [KIND_USER_PROGRESS],
            "authors": [str(user_pub)],
            "#user": [str(user_pub)],
            "limit": 20,
        },
    ]
    by_id: dict[str, dict[str, Any]] = {}
    for filt in filters:
        try:
            evs = client.query([filt], timeout=6.0)
        except Exception:
            evs = []
        for ev in evs or []:
            if not ev or not ev.get("id"):
                continue
            if not has_arb_root(ev, owner_pub, universe_id):
                continue
            if str(ev.get("pubkey") or "") != str(user_pub):
                continue
            if _tag_value(ev, "role") == "part":
                continue
            by_id[str(ev["id"])] = ev
    ranked = sorted(by_id.values(), key=lambda e: int(e.get("created_at") or 0), reverse=True)
    out: list[dict[str, Any]] = []
    for ev in ranked:
        try:
            parsed = json.loads(ev.get("content") or "null")
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            out.append(parsed)
    return out


def decrypt_user_progress_record(
    client: Any,
    *,
    owner_pub: str,
    universe_id: str,
    user_pub: str,
    pair: dict[str, str],
    record: dict[str, Any],
) -> Optional[dict[str, Any]]:
    from .nip44 import decrypt_for_self, unpack_from_sync

    if not isinstance(record, dict) or not pair.get("priv"):
        return None
    n = max(0, int(record.get("n") or 0))
    if int(record.get("v") or 0) == 2 and n > 0 and record.get("ct"):
        parts: list[str | None] = [None] * n
        for i in range(n):
            pd = user_progress_part_d_tag(owner_pub, universe_id, user_pub, i)
            try:
                ev = client.get(
                    {
                        "kinds": [KIND_USER_PROGRESS],
                        "authors": [str(user_pub)],
                        "#d": [pd],
                        "limit": 1,
                    },
                    timeout=8.0,
                )
            except Exception:
                ev = None
            if ev and str(ev.get("pubkey") or "") == str(user_pub):
                parts[i] = str(ev.get("content") or "")
        if any(not p for p in parts):
            return None
        try:
            data = unpack_from_sync(pair, str(record["ct"]), [str(p) for p in parts])
        except Exception:
            return None
        return data if isinstance(data, dict) else None
    if record.get("ct"):
        try:
            data = decrypt_for_self(pair, str(record["ct"]))
        except Exception:
            return None
        return data if isinstance(data, dict) else None
    return None


def _parse_updated_at_ms(value: str) -> int:
    try:
        v = value.replace("Z", "+00:00") if value.endswith("Z") else value
        return int(datetime.fromisoformat(v).timestamp() * 1000)
    except Exception:
        return 0


def pull_encrypted_progress(
    client: Any,
    *,
    owner_pub: str,
    universe_id: str,
    pair: dict[str, str],
) -> Optional[dict[str, Any]]:
    """Return newest decrypted progress, or None if relays have no record.

    Raises ProgressUndecryptableError when header(s) exist but every decrypt fails
    (missing parts / wrong key) — that must not be treated as an empty remote.
    """
    user_pub = str(pair.get("pub") or "")
    records = list_user_progress_records(
        client, owner_pub=owner_pub, universe_id=universe_id, user_pub=user_pub
    )
    best: Optional[dict[str, Any]] = None
    best_at = -1
    headers_seen = False
    for rec in records:
        if not isinstance(rec, dict):
            continue
        headers_seen = True
        data = decrypt_user_progress_record(
            client,
            owner_pub=owner_pub,
            universe_id=universe_id,
            user_pub=user_pub,
            pair=pair,
            record=rec,
        )
        if not data:
            continue
        updated = _parse_updated_at_ms(str(data.get("updatedAt") or rec.get("updatedAt") or ""))
        if best is None or updated >= best_at:
            best = data
            best_at = updated
    if headers_seen and best is None:
        raise ProgressUndecryptableError("progress record present but undecryptable")
    return best


def push_encrypted_progress(
    client: Any,
    *,
    owner_pub: str,
    universe_id: str,
    pair: dict[str, str],
    data: dict[str, Any],
) -> bool:
    from .nip44 import pack_for_sync
    from .nostr_publish import publish_burst, publish_event, sign_event

    user_pub = str(pair.get("pub") or "")
    if not pair.get("priv") or not user_pub:
        return False
    packed = pack_for_sync(pair, data, max_plain=PRIVATE_TREE_NIP44_PLAINTEXT_MAX)
    parts = list(packed["partCiphertexts"])  # type: ignore[arg-type]
    n = len(parts)
    updated_at = str(data.get("updatedAt") or datetime.now(timezone.utc).isoformat())
    header = {
        "v": 2,
        "updatedAt": updated_at,
        "n": n,
        "ct": packed["manifestCiphertext"],
    }
    header_ev = sign_event(
        {
            "kind": KIND_USER_PROGRESS,
            "created_at": int(time.time()),
            "tags": [
                arb_root_tag(owner_pub, universe_id),
                ["d", user_progress_d_tag(owner_pub, universe_id, user_pub)],
                ["user", user_pub],
            ],
            "content": json.dumps(header, ensure_ascii=False, separators=(",", ":")),
        },
        pair["priv"],
    )
    if not publish_event(client, header_ev):
        return False
    part_events = []
    for i, ct in enumerate(parts):
        part_events.append(
            sign_event(
                {
                    "kind": KIND_USER_PROGRESS,
                    "created_at": int(time.time()),
                    "tags": [
                        arb_root_tag(owner_pub, universe_id),
                        ["d", user_progress_part_d_tag(owner_pub, universe_id, user_pub, i)],
                        ["user", user_pub],
                        ["role", "part"],
                        ["i", str(i)],
                        ["n", str(n)],
                    ],
                    "content": str(ct),
                },
                pair["priv"],
            )
        )
    publish_burst(client, part_events, concurrency=5)
    return True


def pull_progress(sess: CliSession, client: Any) -> bool:
    """Pull Care memory for the session focus tree (encrypted) into local_progress."""
    from .identity_store import load_network_pair

    username = str(sess.user.get("username") or "")
    if not sess.user.get("logged_in") or not username:
        return False
    pair = load_network_pair(username)
    if not pair:
        return False
    ref = sess.get_nostr_ref()
    if not ref:
        return False
    try:
        data = pull_encrypted_progress(
            client,
            owner_pub=ref["pub"],
            universe_id=ref["universe_id"],
            pair=pair,
        )
    except ProgressUndecryptableError:
        return False
    if not data:
        return False
    mem = sess._data.setdefault("memory", {})
    if not isinstance(mem, dict):
        mem = {}
        sess._data["memory"] = mem
    if isinstance(data.get("memory"), dict):
        local = mem.get("local_progress") if isinstance(mem.get("local_progress"), dict) else {}
        mem["local_progress"] = merge_memory_maps(local, data["memory"])
    if isinstance(data.get("progress"), list):
        prev = mem.get("completed_nodes") if isinstance(mem.get("completed_nodes"), list) else []
        mem["completed_nodes"] = list(
            dict.fromkeys([*[str(x) for x in prev], *[str(x) for x in data["progress"]]])
        )
    sess.save()
    return True


def auto_sync(sess: CliSession) -> None:
    if not sess.user.get("logged_in"):
        return
    try:
        from .nostr_client import NostrClient
        from .nostr_relays import default_nostr_relays

        relays = sess.get_relays() or default_nostr_relays()
        client = NostrClient(relays)
        pull_progress(sess, client)
    except Exception:
        pass

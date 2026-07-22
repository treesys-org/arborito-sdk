"""Publisher key storage for branch republish."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any, Optional

from .cli_session import sdk_home
from .nostr_protocol import CODE_ALPHABET, normalize_tree_share_code


def publishers_path() -> Path:
    return sdk_home() / "publishers.json"


def load_publishers() -> dict[str, Any]:
    p = publishers_path()
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_publishers(data: dict[str, Any]) -> None:
    p = publishers_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def get_publisher_record(branch_key: str) -> Optional[dict[str, str]]:
    row = load_publishers().get(branch_key)
    if not isinstance(row, dict):
        return None
    pub = str(row.get("pub") or "").strip().lower()
    priv = str(row.get("priv") or "").strip()
    universe_id = str(row.get("universe_id") or "").strip()
    if not pub or not priv or not universe_id:
        return None
    out = {"pub": pub, "priv": priv, "universe_id": universe_id}
    code = str(row.get("share_code") or "").strip()
    if code:
        out["share_code"] = code
    return out


def set_publisher_record(branch_key: str, record: dict[str, str]) -> None:
    data = load_publishers()
    data[branch_key] = {
        "pub": record["pub"],
        "priv": record["priv"],
        "universe_id": record["universe_id"],
        "share_code": record.get("share_code") or "",
    }
    save_publishers(data)


def generate_tree_share_code() -> str:
    chars = []
    for _ in range(8):
        chars.append(CODE_ALPHABET[secrets.randbelow(len(CODE_ALPHABET))])
    s = "".join(chars)
    return f"{s[:4]}-{s[4:]}"


def create_nostr_pair() -> dict[str, str]:
    from .identity_store import create_network_pair

    return create_network_pair()


def format_nostr_tree_url(pub: str, universe_id: str) -> str:
    return f"nostr://{str(pub).lower()}/{universe_id}"

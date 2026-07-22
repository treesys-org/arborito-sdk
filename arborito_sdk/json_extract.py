"""Extract JSON from model output — same rules as inject-game-sdk.js (fences + brace slice)."""

from __future__ import annotations

import json
import re
from typing import Any

CODE_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def extract_json_text(raw: str) -> str:
    clean = (raw or "").strip()
    if not clean:
        return ""
    if "🦉" in clean and "ERROR" in clean:
        raise ValueError("SAGE_ERROR_MARKER")
    m = CODE_BLOCK.search(clean)
    if m:
        clean = m.group(1).strip()
    fb, ff = clean.find("{"), clean.find("[")
    lb, lf = clean.rfind("}"), clean.rfind("]")
    start, end = -1, -1
    if fb != -1 and (ff == -1 or fb < ff):
        start, end = fb, lb + 1
    elif ff != -1:
        start, end = ff, lf + 1
    if start != -1 and end > start:
        clean = clean[start:end]
    return clean


def parse_json_from_model_output(raw: str) -> Any:
    try:
        clean = extract_json_text(raw)
    except ValueError:
        raise
    if not clean:
        raise ValueError("EMPTY")
    return json.loads(clean)

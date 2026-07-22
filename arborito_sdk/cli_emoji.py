"""CLI / TUI emoji chrome aligned with Arborito node defaults.

Terminal prints Unicode raw (no Twemoji). Keep glyphs simple and consistent
with archive defaults (🌳 / 📁 / 📄 / 📝) and the Arborito app.
"""

from __future__ import annotations

# Node type fallbacks when a node has no custom ``icon`` (archive + CLI list).
TYPE_EMOJI = {
    "root": "🌳",
    "branch": "📁",
    "leaf": "📄",
    "exam": "📝",
}

# Focus crumbs / prompt (same as TYPE_EMOJI for product nodes).
FOCUS_ROOT = TYPE_EMOJI["root"]
FOCUS_MODULE = TYPE_EMOJI["branch"]
FOCUS_LESSON = TYPE_EMOJI["leaf"]

# Library rows: full course vs composed playlist.
BRANCH_CHIP = "🌿"
COMPOSED_TREE = "🌲"

DEFAULT_AVATAR = "🌳"

# Top-level CLI / shell commands (Click help + REPL completion + shell help).
CMD_EMOJI: dict[str, str] = {
    "help": "🆘",
    "exit": "🚪",
    "quit": "🚪",
    "list": "📋",
    "go": "🧭",
    "back": "↩️",
    "where": "📍",
    "read": "📖",
    "edit": "✏️",
    "games": "🎮",
    "info": "ℹ️",
    "search": "🔍",
    "quiz": "📝",
    "ask": "💬",
    "memory": "🌱",
    "branch": BRANCH_CHIP,
    "tree": COMPOSED_TREE,
    "cp": "📋",
    "fav": "⭐",
    "session": "👤",
    "config": "⚙️",
    "script": "📜",
    "run": "📜",
    "batch": "📜",
    "shell": "🐚",
    "forest": BRANCH_CHIP,
    "bosque": BRANCH_CHIP,
}

# Subcommands (completion + nested help).
SUB_EMOJI: dict[str, str] = {
    "list": "📋",
    "open": "📂",
    "import": "📥",
    "export": "📤",
    "remove": "🗑️",
    "publish": "📣",
    "add": "➕",
    "new": "🌱",
    "login": "👤",
    "logout": "🚪",
    "whoami": "👤",
    "relay": "⚙️",
    "ai": "⚙️",
    "go": "🧭",
    "back": "↩️",
    "where": "📍",
    "read": "📖",
    "edit": "✏️",
    "games": "🎮",
    "info": "ℹ️",
    "search": "🔍",
    "quiz": "📝",
    "ask": "💬",
    "due": "🌱",
    "report": "🌱",
    "branch": BRANCH_CHIP,
    "tree": COMPOSED_TREE,
}


def cmd_emoji(name: str, default: str = "•") -> str:
    return CMD_EMOJI.get(str(name or "").lower(), default)


def sub_emoji(name: str, default: str = "•") -> str:
    return SUB_EMOJI.get(str(name or "").lower(), default)


def type_emoji(node_type: str, default: str = "•") -> str:
    return TYPE_EMOJI.get(str(node_type or ""), default)

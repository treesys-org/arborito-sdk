"""Arborito Python SDK — load courses and Quiz V2 outside the browser.

This is **not** the Arcade cartridge SDK injected as ``window.arborito`` in HTML
games. Use this package for terminal tools, Pygame, desktop apps, bots, etc.

Install: ``pip install arborito-sdk``  CLI: ``arborito-cli``  Import: ``arborito_sdk``
"""

__version__ = "0.2.2"

from .archive import load_arborito_archive, load_arborito_course
from .client import Arborito, User, attach_helpers
from .errors import (
    AI_EMPTY_RESPONSE,
    AI_NETWORK,
    AI_PARSE_ERROR,
    AI_SAGE_ERROR,
    AI_TIMEOUT,
    ArboritoError,
    ERROR_CODES,
)

__all__ = [
    '__version__',
    "Arborito",
    "User",
    "attach_helpers",
    "load_arborito_archive",
    "load_arborito_course",
    "ArboritoError",
    "ERROR_CODES",
    "AI_TIMEOUT",
    "AI_SAGE_ERROR",
    "AI_PARSE_ERROR",
    "AI_EMPTY_RESPONSE",
    "AI_NETWORK",
]

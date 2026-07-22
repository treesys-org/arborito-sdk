"""Arborito Python SDK CLI entry point."""

from __future__ import annotations

from .cli_app import main

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())

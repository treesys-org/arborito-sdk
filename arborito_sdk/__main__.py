"""``python -m arborito_sdk`` — same as the ``arborito-cli`` command."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())

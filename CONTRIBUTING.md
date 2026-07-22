# Contributing to arborito-sdk

Thank you for helping improve the Python SDK and CLI.

## Development setup

```bash
git clone https://github.com/treesys-org/arborito-sdk.git
cd arborito-sdk
pip install -e ".[dev]"
# optional: full terminal lesson editor (Textual)
pip install -e ".[tui]"
arborito-cli --help
pytest tests/ -q
```

CLI lesson editor: see [`CLI.md`](CLI.md) (`read`, `edit`, `edit --raw`). When changing Quiz V2 authoring, keep `quiz_v2.py` in sync with `arborito/src/features/learning/quiz-v2-schema.js`.

## Release checklist (maintainers)

1. Bump `version` in `pyproject.toml` and `arborito_sdk/__init__.py`.
2. Update `CHANGELOG.md`.
3. Open a pull request on GitHub; merge to `main`.
4. Push git tag `vX.Y.Z` matching `pyproject.toml` to trigger PyPI publish (if configured).

## Nostr protocol spec

Canonical kinds and d-tags: `nostr_spec/spec.json`.

Regenerate bundled copy and sync into the Arborito app:

```bash
python scripts/generate_nostr_spec.py --app
```

## CI

- **SDK Quality**: push to `main`, manual dispatch.
- **Publish to PyPI**: git tag `vX.Y.Z`.

## License

GPL-3.0-or-later, see `LICENSE` and `NOTICE`.

# Changelog

## 0.2.4 (2026-07-26)

- **`matchPairs` / static pairs:** multi-item Quiz V2 blocks inherit the parent concept and yield one unique term↔definition face per item (question→answer when present), so Memory-style boards get more distinct pairs from a single lesson.

## 0.2.3 (2026-07-25)

- **CLI** `search --courses QUERY`: search the public Arborito course directory on Nostr relays. Results skip trees on the maintainer blocklist (embedded copy plus live refresh from GitHub `treesys-org/arborito`).
- Print share codes so you can `branch add XXXX-XXXX` from the hits.

## 0.2.2 (2026-07-23) — Initial release

First public release on PyPI.

### Highlights

- **Python API** (`arborito_sdk`): load `.arborito` archives and Nostr trees; navigate branches/trees; read and edit lessons; run Quiz V2 practice; report Care / SM-2 memory. Same logical surface as browser Arcade (`window.arborito`), with Arcade method names (`fromLesson`, `buildCard`, …) plus Python-style helpers (`grade_answer`, `matches_any`, …).
- **CLI** (`arborito-cli`): interactive shell, course navigation, enriched lesson editor (optional `[tui]`), quiz, search, publish.
- **Nostr** (`pip install 'arborito-sdk[nostr]'`): sync-login / register, publish and load public trees, Care memory `pull` / `push` / `sync` with the same packed progress envelopes as Arborito.
- **Extras**: share codes, composed trees, narrative helpers, grounded quiz grading, `lesson.plainText` for NPC / HUD prose.
- **Archive format**: `format: "arborito"` with `meta.titles` / `meta.descriptions` per curriculum language (no primary `language` flag).

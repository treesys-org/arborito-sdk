# Arborito Python SDK

Build **Pygame games, bots, kiosks, validators, and offline trainers** from any `.arborito` course. Same *capabilities* as browser Arcade cartridges (`window.arborito`).

> **arborito-games** is only the HTML Arcade catalog (like Flathub). **This repo** is for Python and native apps.

**Version:** 0.2.2 (initial release)

## Naming: camelCase vs snake_case

The browser injects `window.arborito` with **camelCase** methods (`fromLesson`, `buildCard`, `tasksFromLesson`). The Python SDK keeps those same names on the Arcade surface so a cartridge and a Pygame game share one vocabulary.

Python-only helpers use **snake_case** (`grade_answer`, `matches_any`, `branch_profile`, `lesson_action`). CamelCase aliases exist where useful (`gradeAnswer`, `matchesAny`, `branchProfile`, `lessonAction`, `plainText` / `plain_text`).

## Install

```bash
pip install arborito-sdk
# Rich terminal lesson editor (F2 Quiz, forms, block list):
pip install 'arborito-sdk[tui]'
# Nostr account + publish:
pip install 'arborito-sdk[nostr]'
```

Package name: `arborito-sdk` · CLI command: `arborito-cli` · Python import: `arborito_sdk`

## Mental model

```
list → go → read | edit | quiz | ask
```

**Library:** `branch` (full courses) and `tree` (composed playlists).

## CLI commands

Run `arborito-cli`.
**Interactive:** `arborito-cli course.arborito` (REPL with breadcrumb prompt).

| Area | Commands |
|------|----------|
| Interactive | `shell` or `arborito-cli course.arborito` (REPL) |
| Navigate | `list`, `go N`, `go back`, `go where`, `go "name"` |
| Lesson | `read` (enriched), `edit` (TUI / F2 Quiz), `edit --raw`, `games` |
| Study | `quiz`, `ask` |
| Course | `info`, `search` |
| Branches | `branch list`, `branch add CODE`, `branch open "Name"`, `branch import`, `branch new`, `branch publish`, `branch export`, `branch remove` |
| Trees | `tree list`, `tree open "Name"`, `tree import`, `tree export`, `tree remove` |
| Copy | `cp branch "Name"` / `cp tree "Name"` |
| Account | `session register`, `session login`, `session logout`, `session whoami` |
| Memory | `memory due`, `memory report` |
| Config | `config relay …`, `config ai …` |

Network: only share codes `XXXX-XXXX` or local `.arborito` files, no manual `nostr://` URLs. Sync and refresh run automatically when loading from the network.

## Quick start

```bash
pip install 'arborito-sdk[tui]'
arborito-cli course.arborito
branch import course.arborito
branch open "My Course"
list
go 1
read # enriched blocks (not raw @quiz)
edit # F2 Quiz, Ctrl+S save
quiz --rounds 5
```

## Lesson editor (terminal)

| Command | Behaviour |
|---------|-----------|
| `read` | Structured view: Quiz · concept, question, answer |
| `edit` | Block list + forms (**requires `[tui]`** for full UI) |
| `edit --raw` | Open lesson markdown in `$EDITOR` |

Details: [CLI.md](https://github.com/treesys-org/arborito-sdk/blob/main/CLI.md). Full WYSIWYG editing is in **Arborito Construction mode**.

## Lesson outline (construct TOC)

Syllabus rows use an `@section` fence with `index` (path) and `title`. Nest depth
is the path segment count (max 8). Indexes are rewritten on every save/move:

```markdown
@section
index: 1
title: Introduction
@/section

Text of the first section.

@section
index: 1.1
title: Concepts
@/section

Detail.

@section
index: 1.2
title: Exercise
@/section

More practice.

@section
index: 1.2.1
title: Extra
@/section

Nested.

@section
index: 2
title: Practice
@/section

Second root section.
```

- Nesting = `index` segment count.
- Humans and the machine share one coordinate (`index:`).
- ←→↑↓ operate on that geometry; `apply_toc_section_move` returns `{ok, body, selectedIndex}` where `ok` is path math (not whether the markdown bytes changed).
- Normal `##` / `###` without a path are content titles once the lesson already has `index:` rows.
- Titles may repeat; indexes stay unique after `prepare_construct_outline_body`.

## The API every game needs

```
lesson → challenge → your UI → memory (optional)
```

```python
from arborito_sdk import Arborito

api = Arborito.from_arborito("course.arborito", lang="EN")
lesson = api.lesson.at(0)
cards = api.challenge.fromLesson(lesson)
card = api.challenge.modes.buildCard(cards[0], "cloze", lang="EN")
prose = api.lesson.plainText(lesson)  # NPC / HUD (strips @section, @quiz, …)
api.memory.report(lesson["id"], quality=4)
```

**Care sync with the Arborito app** (Nostr tree + account):

```python
api = Arborito.from_share_code("ABCD-EF23", lang="EN")
api.login("player", "their-sync-secret")  # restores network identity escrow
api.memory.pull()  # merge Care from relays
api.memory.report(lesson["id"], quality=4)
api.memory.push()  # or api.memory.sync() = pull+push
```

Requires `pip install 'arborito-sdk[nostr]'`. CLI: `session login` then `memory pull|push|sync`.

Optional: `ask.lesson_action(...)` (local LLM + branch context), `ask.json(...)` (your own prompt), `api.narrative.start()` (programmatic only, no CLI narrative command).

### Quiz helpers

```python
lesson = api.lesson.by_id(pool_item["lessonId"])
ctx = api.lesson.context_for_ai(lesson)
ok = api.quiz.grade_answer(lesson, {"q": "…", "correct": "…"}, player_text)
match = api.quiz.matches_any(player_text, ["answer", "synonym"])
picked = api.quiz.pick(pool, session={})  # session["used"] persists
tasks = api.challenge.tasksFromLesson(lesson, {"max": 10})
replay = api.quiz.find_code_replay("echo hi", lesson=lesson)
```

In **static mode**, `grade_answer` only uses local matching (no LLM). Browser cartridges use the same helpers under camelCase (`gradeAnswer`, `matchesAny`, `tasksFromLesson`, `findCodeReplay`, …), see [sdk-spec.md](https://github.com/treesys-org/arborito/blob/main/docs/sdk-spec.md).

## Loaders

| Method | Use |
|--------|-----|
| `Arborito.from_arborito(path)` | Local export (recommended) |
| `Arborito.from_share_code("ABCD-EF23")` | Public share code |
| `Arborito.from_nostr(pub, universe_id)` | Direct Nostr reference |

## Docs

- [CLI.md](https://github.com/treesys-org/arborito-sdk/blob/main/CLI.md) — full CLI reference + terminal editor keys
- [CHANGELOG.md](https://github.com/treesys-org/arborito-sdk/blob/main/CHANGELOG.md) — release notes
- [sdk-spec.md](https://github.com/treesys-org/arborito/blob/main/docs/sdk-spec.md) — API contract
- [PYTHON_SDK.md](https://github.com/treesys-org/arborito/blob/main/docs/PYTHON_SDK.md)

## Test

```bash
cd arborito-sdk && pip install -e ".[dev,nostr]" && python -m unittest discover -s tests -q
```

## Example

```bash
# Static quiz (no AI server)
python examples/minimal_quiz.py path/to/course.arborito EN

# AI tutor (needs llama.cpp on LLAMA_CPP_HOST or port 8080/8765)
python examples/ai_tutor.py path/to/course.arborito EN
```

### AI in three lines

```python
profile = api.lesson.branch_profile(lesson)
res = api.ask.lesson_action(lesson, player_said, {"persona": "Guide", "profile": profile})
print(res["output"])
```

See `examples/ai_tutor.py` for a full REPL.

## Contributing

[CONTRIBUTING.md](https://github.com/treesys-org/arborito-sdk/blob/main/CONTRIBUTING.md)

Chat: [Matrix #arborito:matrix.org](https://matrix.to/#/%23arborito:matrix.org) · [treesys.org](https://treesys.org)

## License

GPL-3.0-or-later, [LICENSE](https://github.com/treesys-org/arborito-sdk/blob/main/LICENSE)

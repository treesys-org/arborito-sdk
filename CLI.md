# Arborito SDK CLI

```
list → go → read | edit | quiz | ask
```

Package name: `arborito-sdk` · CLI command: `arborito-cli` · Python import: `arborito_sdk`

## Lesson editor (enriched TUI)

`read` and `edit` show **structured blocks** in the terminal, not raw `@quiz` fences.

```bash
pip install 'arborito-sdk[tui]' # full editor with F2–F5 toolbar (Textual)
arborito-cli course.arborito
go 1
read # enriched view: Quiz · concept, question, answer…
edit # block list + forms (Ctrl+S save, F2 insert Quiz)
edit --raw # open full markdown in $EDITOR
read --raw # dump raw .md
```

| Key | Action |
|-----|--------|
| `F2` | Insert @quiz (form: concept, question, answer, traps) |
| `F3` | Insert @section |
| `F4` | Insert @game |
| `F5` | Edit @info metadata |
| `Enter` | Edit selected block |
| `Ctrl+S` | Save to `.arborito` |
| `Ctrl+X` | Exit |

Without `[tui]`, `edit` falls back to a simple numbered block menu + Click prompts.

## Navigation

| Command | Action |
|---------|--------|
| `go 2` | Child #2 from `list` |
| `go back` / `go where` | Undo / breadcrumb |
| `go "name"` | Node with literal name |

## Library (branches and trees)

| | `branch` (course) | `tree` (playlist) |
|---|-------------------|-------------------|
| List | `branch list` | `tree list` |
| Network | `branch add CODE` | (none) |
| Open | `branch open "Name"` | `tree open "Name"` |
| Create | `branch new "Name"` | (none) |
| Import | `branch import file.arborito [--lang ES]` | `tree import file.arborito [--lang ES]` |
| Copy | `cp branch "Name"` | `cp tree "Name"` |
| Memory | `memory due`, `memory report` | |
| Remove | `branch remove "Name"` | `tree remove "Name"` |
| Export | `branch export "Name" out.arborito` | `tree export …` |

`branch open` with no argument opens the only branch when exactly one is in the list.

Network: only share codes `XXXX-XXXX`: **no `nostr://` URLs**. Sync and refresh run automatically when loading from the network.

## Interactive shell

```bash
arborito-cli shell --fresh # empty, then: branch import / branch add / branch open
arborito-cli shell # resume last course
arborito-cli course.arborito # REPL with that file
arborito-cli shell # after branch open / import
```

In the shell: `help` shows commands. `-h` / `--help` prints the same help (and `branch --help` works as a shortcut). `forest` is an alias for `branch list` (also accepted: `bosque`).

## Publish

```bash
branch publish "Name" --author "Your name" --description "Course description"
```

First publish: generates publisher key pair, `brn-…` universe id, and share code `XXXX-XXXX`. 
Republish reuses keys stored in `~/.arborito-sdk/publishers.json`.

Requires `pip install 'arborito-sdk[nostr]'` and relays (`config relay set …`).

## Account

```bash
session register USER --secret
session login USER --secret
session whoami
```

Registration requires PoW (~1 min) and `pip install 'arborito-sdk[nostr]'`.

## Config

```bash
config relay list|set|reset
config ai list
config ai set mode dynamic
config ai set host http://127.0.0.1:8080
config ai set preset balanced
```

## Test (one line)

```bash
cd arborito-sdk && pip install -e ".[dev]" && python -m unittest discover -s tests -q
```

## Out of scope for the CLI

Embedded Arcade play, forum, votes, certificates, TTS. Publish ships the course bundle and share code; global directory listing and delist are not in this CLI. YAML narrative modules: use `read` / `quiz`, or `api.narrative` in Python.

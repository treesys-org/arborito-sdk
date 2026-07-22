"""Textual application for the Arborito CLI lesson editor."""

from __future__ import annotations

from typing import Any, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Static, TextArea

from .client import Arborito
from .lesson_document import (
    FencedBlock,
    InfoBlock,
    LessonDocument,
    ProseBlock,
    QuizBlock,
    block_list_labels,
)
from .lesson_write import save_lesson_raw
from .quiz_v2 import new_challenge


class QuizEditScreen(Screen):
    """Form editor for a single @quiz block."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(self, challenge: dict[str, Any], *, block_index: Optional[int] = None) -> None:
        super().__init__()
        self.challenge = dict(challenge)
        self.block_index = block_index

    def compose(self) -> ComposeResult:
        c = self.challenge
        yield Header(show_clock=False)
        yield Static("📋 Edit quiz", classes="screen-title")
        yield Label("Concept")
        yield Input(value=str(c.get("core_concept") or ""), id="concept")
        yield Label("Definition")
        yield Input(value=str(c.get("short_definition") or ""), id="definition")
        yield Label("Question")
        yield Input(value=str(c.get("main_question") or ""), id="question")
        yield Label("Correct answer")
        yield Input(value=str(c.get("correct_answer") or ""), id="answer")
        yield Label("Traps (one per line)")
        yield TextArea("\n".join(c.get("traps") or []), id="traps", language="markdown")
        with Horizontal(classes="button-row"):
            yield Button("Save", variant="primary", id="btn-save")
            yield Button("Cancel", id="btn-cancel")
        yield Footer()

    def action_cancel(self) -> None:
        self.app.pop_screen()

    def action_save(self) -> None:
        self._collect()
        self.dismiss({"challenge": self.challenge, "index": self.block_index})

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            self.action_save()
        elif event.button.id == "btn-cancel":
            self.action_cancel()

    def _collect(self) -> None:
        from .quiz_v2 import parse_inline_cloze

        self.challenge["core_concept"] = self.query_one("#concept", Input).value.strip()
        definition = self.query_one("#definition", Input).value.strip()
        text, idxs = parse_inline_cloze(definition)
        self.challenge["short_definition"] = text
        self.challenge["cloze_indices"] = idxs
        self.challenge["main_question"] = self.query_one("#question", Input).value.strip()
        self.challenge["correct_answer"] = self.query_one("#answer", Input).value.strip()
        traps = self.query_one("#traps", TextArea).text
        self.challenge["traps"] = [ln.strip() for ln in traps.splitlines() if ln.strip()]


class ProseEditScreen(Screen):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(self, text: str, *, block_index: int) -> None:
        super().__init__()
        self.text = text
        self.block_index = block_index

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("📝 Edit text (Markdown)", classes="screen-title")
        yield TextArea(self.text, id="prose", language="markdown")
        with Horizontal(classes="button-row"):
            yield Button("Save", variant="primary", id="btn-save")
            yield Button("Cancel", id="btn-cancel")
        yield Footer()

    def action_cancel(self) -> None:
        self.app.pop_screen()

    def action_save(self) -> None:
        text = self.query_one("#prose", TextArea).text.rstrip("\n")
        self.dismiss({"text": text, "index": self.block_index})

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            self.action_save()
        elif event.button.id == "btn-cancel":
            self.action_cancel()


class InfoEditScreen(Screen):
    BINDINGS = [Binding("escape", "cancel", "Cancel"), Binding("ctrl+s", "save", "Save")]

    def __init__(self, info: InfoBlock) -> None:
        super().__init__()
        self.info = info

    def compose(self) -> ComposeResult:
        f = self.info.fields
        tags = f.get("tags") or []
        tag_str = ", ".join(str(t) for t in tags) if isinstance(tags, list) else str(tags)
        yield Header(show_clock=False)
        yield Static("ℹ️  @info metadata", classes="screen-title")
        yield Label("Title")
        yield Input(value=str(f.get("title") or ""), id="title")
        yield Label("Icon")
        yield Input(value=str(f.get("icon") or "📄"), id="icon")
        yield Label("Description")
        yield Input(value=str(f.get("description") or ""), id="description")
        yield Label("Tags (comma-separated)")
        yield Input(value=tag_str, id="tags")
        with Horizontal(classes="button-row"):
            yield Button("Save", variant="primary", id="btn-save")
            yield Button("Cancel", id="btn-cancel")
        yield Footer()

    def action_cancel(self) -> None:
        self.app.pop_screen()

    def action_save(self) -> None:
        self.info.fields["title"] = self.query_one("#title", Input).value.strip()
        self.info.fields["icon"] = self.query_one("#icon", Input).value.strip() or "📄"
        self.info.fields["description"] = self.query_one("#description", Input).value.strip()
        raw_tags = self.query_one("#tags", Input).value.strip()
        self.info.fields["tags"] = [t.strip() for t in raw_tags.split(",") if t.strip()]
        self.dismiss({"info": self.info})

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            self.action_save()
        elif event.button.id == "btn-cancel":
            self.action_cancel()


class BlockListItem(ListItem):
    def __init__(self, index: int, label: str) -> None:
        super().__init__()
        self.block_index = index
        self.label_text = label

    def compose(self) -> ComposeResult:
        yield Label(self.label_text)


class LessonEditorApp(App):
    """Nano-style lesson editor: block list + footer shortcuts."""

    CSS = """
    Screen {
        background: #0f172a;
    }
    .screen-title {
        padding: 0 1 1 1;
        color: #a78bfa;
        text-style: bold;
    }
    #block-list {
        height: 1fr;
        border: solid #334155;
        margin: 0 1;
    }
    .toolbar {
        height: auto;
        padding: 0 1 1 1;
    }
    .button-row {
        height: auto;
        padding: 1;
    }
    #status {
        padding: 0 1;
        color: #94a3b8;
    }
    TextArea {
        height: 1fr;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=True),
        Binding("ctrl+x", "quit", "Quit", show=True),
        Binding("f2", "insert_quiz", "Quiz", show=True),
        Binding("f3", "insert_section", "Section", show=True),
        Binding("f6", "insert_subsection", "Sub", show=True),
        Binding("f4", "insert_game", "Game", show=True),
        Binding("f5", "edit_info", "Info", show=True),
        Binding("enter", "edit_block", "Edit", show=True),
        Binding("delete", "delete_block", "Delete", show=True),
    ]

    def __init__(self, *, api: Arborito, lesson_id: str, document: LessonDocument) -> None:
        super().__init__()
        self.api = api
        self.lesson_id = lesson_id
        self.document = document
        self._dirty = False

    def _info_offset(self) -> int:
        return 1 if self.document.info and self.document.info.fields else 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("✏️  Lesson editor: structured blocks (not raw markdown)", id="title-bar")
        yield ListView(id="block-list")
        with Horizontal(classes="toolbar"):
            yield Button("F2 Quiz", id="tb-quiz")
            yield Button("F3 Section", id="tb-section")
            yield Button("F6 Sub", id="tb-sub")
            yield Button("F4 Game", id="tb-game")
            yield Button("F5 Info", id="tb-info")
        yield Static("↑↓ navigate · Enter edit · Ctrl+S save · Ctrl+X quit", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_list()

    def _refresh_list(self, *, select: Optional[int] = None) -> None:
        lv = self.query_one("#block-list", ListView)
        lv.clear()
        labels = block_list_labels(self.document)
        for i, label in enumerate(labels):
            lv.append(BlockListItem(i, label))
        if labels:
            lv.index = select if select is not None else min(lv.index or 0, len(labels) - 1)

    def _selected_index(self) -> Optional[int]:
        lv = self.query_one("#block-list", ListView)
        item = lv.highlighted_child
        if isinstance(item, BlockListItem):
            return item.block_index
        return None

    def action_save(self) -> None:
        raw = self.document.to_markdown()
        try:
            entry = save_lesson_raw(self.api, self.lesson_id, raw)
        except ValueError as e:
            self.notify(str(e), severity="error")
            return
        self._dirty = False
        self.notify(f"Saved {entry}", severity="information")

    def action_quit(self) -> None:
        if self._dirty:
            self.notify("Unsaved changes — Ctrl+S before quitting", severity="warning")
            return
        self.exit()

    def action_insert_quiz(self) -> None:
        self.document.blocks.append(QuizBlock(challenge=new_challenge()))
        self._dirty = True
        self._refresh_list(select=len(block_list_labels(self.document)) - 1)
        self.action_edit_block()

    def action_insert_section(self) -> None:
        self.document.blocks.append(FencedBlock(tag="section", fields={"title": "New section"}))
        self._dirty = True
        self._refresh_list(select=len(block_list_labels(self.document)) - 1)

    def action_insert_subsection(self) -> None:
        """Insert nested subsection using the same outline math as Arborito construct."""
        from .lesson_document import parse_lesson_document
        from .lesson_toc_mutations import add_toc_subsection_after, get_toc_line_ranges, prepare_construct_outline_body

        raw = prepare_construct_outline_body(self.document.to_markdown())
        ranges = get_toc_line_ranges(raw)
        parent_idx = 0
        sel = self._selected_index()
        if sel is not None and ranges and not ranges[0].get("synthetic"):
            block_idx = sel - self._info_offset()
            if block_idx < 0:
                parent_idx = 0
            elif block_idx < len(ranges):
                parent_idx = block_idx
            else:
                parent_idx = len(ranges) - 1
        next_raw = add_toc_subsection_after(raw, parent_idx, "New subsection", "")
        if next_raw == raw:
            # No ATX outline: append a fence subsection after the selection.
            insert_at = len(self.document.blocks)
            if sel is not None:
                bi = sel - self._info_offset()
                if 0 <= bi < len(self.document.blocks):
                    insert_at = bi + 1
            self.document.blocks.insert(
                insert_at, FencedBlock(tag="subsection", fields={"title": "New subsection"})
            )
        else:
            self.document = parse_lesson_document(next_raw)
        self._dirty = True
        self._refresh_list(select=len(block_list_labels(self.document)) - 1)

    def action_insert_game(self) -> None:
        self.document.blocks.append(FencedBlock(tag="game", fields={"url": "", "label": "Game", "optional": "yes"}))
        self._dirty = True
        self._refresh_list(select=len(block_list_labels(self.document)) - 1)

    def action_edit_info(self) -> None:
        if not self.document.info:
            self.document.info = InfoBlock(fields={})
        self.push_screen(InfoEditScreen(self.document.info), self._on_info_saved)

    def action_edit_block(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        if self.document.info and self.document.info.fields and idx == 0:
            self.action_edit_info()
            return
        block_idx = idx - self._info_offset()
        if block_idx < 0 or block_idx >= len(self.document.blocks):
            return
        block = self.document.blocks[block_idx]
        if isinstance(block, QuizBlock):
            self.push_screen(
                QuizEditScreen(block.challenge, block_index=block_idx),
                self._on_quiz_saved,
            )
        elif isinstance(block, ProseBlock):
            self.push_screen(ProseEditScreen(block.text, block_index=block_idx), self._on_prose_saved)
        elif isinstance(block, FencedBlock):
            self.notify(f"@{block.tag}: edit with F5 or basic mode for now", severity="warning")

    def action_delete_block(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        if self.document.info and self.document.info.fields and idx == 0:
            self.document.info = None
        else:
            block_idx = idx - self._info_offset()
            if 0 <= block_idx < len(self.document.blocks):
                self.document.blocks.pop(block_idx)
        self._dirty = True
        self._refresh_list()

    def _on_quiz_saved(self, result: Optional[dict]) -> None:
        if not result:
            return
        idx = result.get("index")
        if idx is not None and 0 <= idx < len(self.document.blocks):
            block = self.document.blocks[idx]
            if isinstance(block, QuizBlock):
                block.challenge = result["challenge"]
                self._dirty = True
                self._refresh_list(select=idx + self._info_offset())

    def _on_prose_saved(self, result: Optional[dict]) -> None:
        if not result:
            return
        idx = result.get("index")
        if idx is not None and 0 <= idx < len(self.document.blocks):
            block = self.document.blocks[idx]
            if isinstance(block, ProseBlock):
                block.text = result["text"]
                self._dirty = True
                self._refresh_list(select=idx + self._info_offset())

    def _on_info_saved(self, _result: Optional[dict]) -> None:
        self._dirty = True
        self._refresh_list(select=0)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        mapping = {
            "tb-quiz": self.action_insert_quiz,
            "tb-section": self.action_insert_section,
            "tb-sub": self.action_insert_subsection,
            "tb-game": self.action_insert_game,
            "tb-info": self.action_edit_info,
        }
        fn = mapping.get(event.button.id or "")
        if fn:
            fn()

    def on_list_view_selected(self, _event: ListView.Selected) -> None:
        self.action_edit_block()

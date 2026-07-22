"""CLI focus, lesson save, prompts, SM-2 memory."""

from __future__ import annotations

from pathlib import Path

from arborito_sdk.cli_session import CliSession
from arborito_sdk.client import Arborito, User
from arborito_sdk.lesson_write import reconstruct_arborito_file, save_lesson_raw
from arborito_sdk.progress_sync import memory_due_ids, record_local_review, report_memory_sm2
from arborito_sdk.quiz_v2 import build_mode_card, parse_inline_cloze, serialize_quiz_block


def test_set_focus_clears_lesson_on_branch():
    sess = CliSession()
    sess.set_focus(module_id="m1", module_name="Mod", lesson_id="l1", lesson_name="Leaf")
    sess.set_focus(module_id="m2", module_name="Other", lesson_id="", lesson_name="")
    assert sess.focus["module_id"] == "m2"
    assert sess.focus["lesson_id"] == ""
    assert sess.focus["lesson_name"] == ""


def test_set_focus_none_leaves_unchanged():
    sess = CliSession()
    sess.set_focus(lesson_id="l1", lesson_name="Leaf")
    sess.set_focus(module_id="m1")
    assert sess.focus["lesson_id"] == "l1"
    assert sess.focus["module_id"] == "m1"


def test_es_recall_prompt():
    ch = {
        "core_concept": "GNU/Linux",
        "correct_answer": "Un sistema operativo",
        "short_definition": "Sistema libre",
        "modes": ["recall"],
    }
    card = build_mode_card(ch, "recall", lang="ES")
    assert card is not None
    assert "¿Qué es" in card["question"]


def test_cloze_reparse_on_definition_edit():
    text, idxs = parse_inline_cloze("A {short new} definition here")
    assert text == "A short new definition here"
    assert idxs == [1, 2]
    ch = {
        "core_concept": "X",
        "short_definition": text,
        "cloze_indices": idxs,
        "correct_answer": "Y",
        "modes": ["cloze"],
    }
    serialized = serialize_quiz_block(ch)
    assert "{short" in serialized or "{short new}" in serialized or "short new" in serialized
    assert "{definition}" not in serialized  # stale indices must not brace wrong words


def test_reconstruct_keeps_exam_flag():
    raw = reconstruct_arborito_file({"title": "T", "exam": True}, "Body")
    assert "exam: yes" in raw


def test_sm2_schedules_due_date():
    now = 1_700_000_000_000
    item = report_memory_sm2(None, 5, now_ms=now)
    assert item["dueDate"] == now + 1 * 24 * 60 * 60 * 1000
    assert item["lvl"] == 1
    failed = report_memory_sm2(item, 2, now_ms=now + 1000)
    assert failed["lvl"] == 0
    assert failed["interval"] == 1


def test_memory_due_ids_uses_due_date():
    sess = CliSession()
    now = 1_700_000_000_000
    record_local_review(sess, "leaf-a", 2, now_ms=now)
    # Fail schedules +1 day — not due yet
    assert "leaf-a" not in memory_due_ids(sess, now_ms=now)
    assert "leaf-a" in memory_due_ids(sess, now_ms=now + 2 * 24 * 60 * 60 * 1000)


def test_client_memory_report_and_due():
    api = Arborito([], User("t", "ES"), ai_mode="static")
    now_item = api.memory.report("n1", 5)
    assert now_item["dueDate"] > 0
    assert api.memory.isDue("n1") is False
    # Force due
    api._memory_store["n1"]["dueDate"] = 0
    assert api.memory.isDue("n1") is True
    assert "n1" in api.memory.due()


def test_save_lesson_updates_canonical_row(tmp_path: Path):
    from zipfile import ZipFile

    archive = tmp_path / "course.arborito"
    entry = "lessons/ES/01-a.md"
    body = (
        "@info\n"
        "title: A\n"
        "tags: alpha, beta\n"
        "@/info\n\n"
        "Hello\n\n"
        "@quiz\n"
        "concept: C\n"
        "answer: Alpha\n"
        "modes: recall\n"
        "@/quiz\n"
    )
    with ZipFile(archive, "w") as zf:
        zf.writestr(
            "manifest.json",
            '{"format":"arborito","meta":{"titles":{"ES":"T"}}}',
        )
        zf.writestr(entry, body)

    from arborito_sdk.archive import load_arborito_course

    course = load_arborito_course(archive, lang="ES")
    api = Arborito(
        course["lessons"],
        User("t", "ES"),
        ai_mode="static",
        tree_root=course["tree_root"],
        lesson_by_id=course["lesson_by_id"],
    )
    api._source_path = str(archive)
    lid = course["lessons"][0]["id"]
    assert api.lesson.read_meta(api.lesson.by_id(lid))["tags"] == ["alpha", "beta"]

    new_body = body.replace("answer: Alpha", "answer: Beta")
    save_lesson_raw(api, lid, new_body, archive_path=archive)
    hit = api._lesson_by_id[lid]
    assert "answer: Beta" in hit["raw"]
    assert hit["challenges"][0]["correct_answer"] == "Beta"

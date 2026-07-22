"""Smoke checks for lesson TOC outline mutations."""

from __future__ import annotations

from arborito_sdk.lesson_toc_mutations import (
    add_toc_section_after,
    add_toc_subsection_after,
    get_toc_line_ranges,
    prepare_construct_outline_math,
    toc_heading_title_for_edit,
    toc_range_outline_level,
)


def _titles(body: str) -> list[str]:
    return [toc_heading_title_for_edit(r.get("headingRaw")) for r in get_toc_line_ranges(body)]


def test_first_section_from_empty_has_title_and_path():
    body = add_toc_section_after("", 0, "Nueva sección", "Write the content here.")
    ranges = get_toc_line_ranges(body)
    assert len(ranges) == 1
    assert ranges[0]["id"] == "1"
    assert _titles(body) == ["Nueva sección"]
    assert "index: 1" in body
    assert "title: Nueva sección" in body
    assert "Write the content here." in body


def test_prepare_assigns_human_path_ids():
    body = prepare_construct_outline_math(
        "## A\na\n\n### B\nb\n\n### C\nc\n\n## D\nd\n"
    )
    paths = [r["id"] for r in get_toc_line_ranges(body)]
    assert paths == ["1", "1.1", "1.2", "2"]
    assert _titles(body) == ["A", "B", "C", "D"]


def test_plus_on_root_nests_children():
    body = "## Root\nr\n"
    body = add_toc_subsection_after(body, 0, "A", "a")
    body = add_toc_subsection_after(body, 0, "B", "b")
    assert _titles(body) == ["Root", "A", "B"]
    levels = [toc_range_outline_level(r) for r in get_toc_line_ranges(body)]
    assert levels == [2, 3, 3]

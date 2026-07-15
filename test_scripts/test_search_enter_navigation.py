from __future__ import annotations

import fitz

from view.pdf_view import PDFView


def _results() -> list[tuple[int, str, fitz.Rect]]:
    return [
        (1, "first", fitz.Rect(10, 10, 20, 20)),
        (2, "second", fitz.Rect(30, 30, 40, 40)),
    ]


def test_enter_searches_once_then_cycles_results(qapp) -> None:
    view = PDFView()
    searches: list[str] = []
    jumps: list[tuple[int, fitz.Rect]] = []
    view.sig_search.connect(searches.append)
    view.sig_jump_to_result.connect(lambda page, rect: jumps.append((page, rect)))
    try:
        view.search_input.setText("needle")
        view._trigger_search()
        assert searches == ["needle"]

        view.display_search_results(_results())
        view._trigger_search()
        view._trigger_search()

        assert searches == ["needle"]
        assert [page for page, _rect in jumps] == [1, 2]
        assert view.current_search_index == 1
    finally:
        view.close()
        view.deleteLater()


def test_enter_does_not_navigate_while_results_are_streaming(qapp) -> None:
    view = PDFView()
    searches: list[str] = []
    jumps: list[tuple[int, fitz.Rect]] = []
    view.sig_search.connect(searches.append)
    view.sig_jump_to_result.connect(lambda page, rect: jumps.append((page, rect)))
    try:
        view.search_input.setText("needle")
        view._trigger_search()
        view.append_search_results(_results()[:1])

        view._trigger_search()

        assert searches == ["needle"]
        assert jumps == []
        assert view.search_status_label.text() == "搜尋中..."
    finally:
        view.close()
        view.deleteLater()


def test_editing_query_forces_a_new_search(qapp) -> None:
    view = PDFView()
    searches: list[str] = []
    view.sig_search.connect(searches.append)
    try:
        view.search_input.setText("first")
        view._trigger_search()
        view.display_search_results(_results())

        view.search_input.setText("second")
        view._on_search_query_edited("second")
        view._trigger_search()

        assert searches == ["first", "second"]
    finally:
        view.close()
        view.deleteLater()

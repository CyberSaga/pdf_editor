from __future__ import annotations

from PySide6.QtWidgets import QComboBox

from view.pdf_view import PDFView


def test_color_profile_sidebar_combo_exists(qapp) -> None:
    _ = qapp
    view = PDFView()

    combo = getattr(view, "color_profile_combo", None)
    assert isinstance(combo, QComboBox)
    assert combo.count() == 3
    assert combo.itemData(0) == "srgb"
    assert combo.itemData(1) == "gray"
    assert combo.itemData(2) == "cmyk"


def test_color_profile_combo_emits_signal_on_user_change(qapp) -> None:
    _ = qapp
    view = PDFView()
    events: list[str] = []
    view.sig_color_profile_changed.connect(events.append)

    view.color_profile_combo.setCurrentIndex(1)
    assert events[-1] == "gray"


def test_set_color_profile_updates_combo_without_emitting(qapp) -> None:
    _ = qapp
    view = PDFView()
    events: list[str] = []
    view.sig_color_profile_changed.connect(events.append)

    view.set_color_profile("cmyk")
    assert view.color_profile_combo.currentData() == "cmyk"
    assert events == []


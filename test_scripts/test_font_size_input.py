from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtTest import QTest

from view.pdf_view import PDFView
from view.text_editing import _validated_font_size_input


@pytest.mark.parametrize(
    ("text", "expected"),
    [("9.5", 9.5), ("10.0", 10.0), ("12.3", 12.3), ("18", 18.0)],
)
def test_validated_font_size_accepts_presets_and_one_decimal(text: str, expected: float) -> None:
    assert _validated_font_size_input(text) == expected


@pytest.mark.parametrize("text", ["", "-1", "0", "0.5", "1000", "9.55", "abc"])
def test_validated_font_size_rejects_invalid_values(text: str) -> None:
    assert _validated_font_size_input(text) is None


def test_font_size_combo_is_editable_with_one_decimal_validator(qapp) -> None:
    view = PDFView()
    try:
        assert view.text_size.isEditable()
        line_edit = view.text_size.lineEdit()
        assert line_edit is not None
        validator = line_edit.validator()
        assert isinstance(validator, QDoubleValidator)
        assert validator.decimals() == 1
        assert validator.bottom() == 1.0
        assert validator.top() == 999.9
    finally:
        view.close()
        view.deleteLater()


@pytest.mark.parametrize("valid_text", ["9.5", "10.0", "12.3"])
def test_committed_manual_font_size_keeps_one_decimal(qapp, valid_text: str) -> None:
    view = PDFView()
    try:
        line_edit = view.text_size.lineEdit()
        assert line_edit is not None
        view._on_text_size_input_edited(valid_text)
        line_edit.setText(valid_text)

        assert view._commit_text_size_input() is True
        assert view.text_size.currentText() == valid_text
        assert view._last_valid_text_size_text == valid_text
    finally:
        view.close()
        view.deleteLater()


@pytest.mark.parametrize("invalid_text", ["", "-2", "0", "0.5", "1000", "9.55"])
def test_invalid_manual_font_size_restores_last_valid_value(qapp, invalid_text: str) -> None:
    view = PDFView()
    try:
        line_edit = view.text_size.lineEdit()
        assert line_edit is not None
        view._on_text_size_input_edited("9.5")
        line_edit.setText("9.5")
        assert view._commit_text_size_input() is True

        view._on_text_size_input_edited(invalid_text)
        line_edit.setText(invalid_text)

        assert view._commit_text_size_input() is False
        assert view.text_size.currentText() == "9.5"
        assert view._last_valid_text_size_text == "9.5"
    finally:
        view.close()
        view.deleteLater()


def test_manual_font_size_applies_only_after_commit(qapp, monkeypatch) -> None:
    view = PDFView()
    applied: list[str] = []
    monkeypatch.setattr(view.text_edit_manager, "on_edit_font_size_changed", applied.append)
    view.text_size.currentTextChanged.connect(view._on_edit_font_size_changed)
    try:
        view.show()
        line_edit = view.text_size.lineEdit()
        assert line_edit is not None
        line_edit.setFocus()
        line_edit.selectAll()
        QTest.keyClicks(line_edit, "9.5")

        assert applied == []

        QTest.keyClick(line_edit, Qt.Key.Key_Return)
        qapp.processEvents()
        assert applied == ["9.5"]
    finally:
        view.close()
        view.deleteLater()


def test_existing_font_size_preset_still_applies_immediately(qapp, monkeypatch) -> None:
    view = PDFView()
    applied: list[str] = []
    monkeypatch.setattr(view.text_edit_manager, "on_edit_font_size_changed", applied.append)
    try:
        view._on_edit_font_size_changed("18")

        assert applied == ["18"]
        assert view._last_valid_text_size_text == "18"
    finally:
        view.close()
        view.deleteLater()


@pytest.mark.parametrize("invalid_text", ["", "-2", "0", "0.5", "1000", "9.55"])
def test_invalid_keyboard_input_reaches_commit_and_restores(qapp, invalid_text: str) -> None:
    view = PDFView()
    try:
        view.show()
        line_edit = view.text_size.lineEdit()
        assert line_edit is not None
        line_edit.setFocus()
        line_edit.selectAll()
        if invalid_text:
            QTest.keyClicks(line_edit, invalid_text)
        else:
            QTest.keyClick(line_edit, Qt.Key.Key_Backspace)

        assert line_edit.text() == invalid_text
        QTest.keyClick(line_edit, Qt.Key.Key_Return)
        qapp.processEvents()

        assert view.text_size.currentText() == "12"
        assert view._last_valid_text_size_text == "12"
    finally:
        view.close()
        view.deleteLater()


def test_valid_keyboard_input_commits_exact_display_text(qapp) -> None:
    view = PDFView()
    try:
        view.show()
        line_edit = view.text_size.lineEdit()
        assert line_edit is not None
        line_edit.setFocus()
        line_edit.selectAll()
        QTest.keyClicks(line_edit, "10.0")
        QTest.keyClick(line_edit, Qt.Key.Key_Return)
        qapp.processEvents()

        assert view.text_size.currentText() == "10.0"
        assert view._last_valid_text_size_text == "10.0"
    finally:
        view.close()
        view.deleteLater()

"""Tests for the read-only span->operator mapping audit (plan Task 3)."""
from __future__ import annotations

import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_text_source_mapping import audit_document, main  # noqa: E402


def test_audit_document_counts_bound_and_rejected():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Bindable text", fontsize=12.0, fontname="helv")
    # Task 13 P2: a 90°-rotated show now BINDS (quarter-turn admission);
    # keep a genuinely inadmissible shape in the mix — a sheared Tm — to
    # pin that the audit still attributes refusals by their stable code.
    page.insert_text(
        (200, 400), "Rotated 90", fontsize=12.0, fontname="helv", rotate=90
    )
    content_xref = page.get_contents()[0]
    stream = doc.xref_stream(content_xref)
    sheared = stream + (
        b"\nBT /helv 12 Tf 1 0 0.5 1 300 700 Tm (Sheared text) Tj ET"
    )
    doc.update_stream(content_xref, sheared)
    counts = audit_document(doc)
    doc.close()
    assert counts["bound"] == 2
    assert counts["trm_sheared"] == 1
    assert sum(counts.values()) == 3


def test_audit_main_reports_without_leaking_text(tmp_path, capsys):
    pdf_path = tmp_path / "case.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "SecretContent42", fontsize=12.0, fontname="helv")
    doc.save(str(pdf_path))
    doc.close()

    exit_code = main(["--corpus", str(tmp_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "case" in out
    assert "bound=1" in out
    assert "SecretContent42" not in out  # never emit document text

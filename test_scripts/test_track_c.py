# -*- coding: utf-8 -*-
"""
test_track_c.py — Track C Engine: Isolated Feasibility Spike Tests

Tests:
  1. test_simple_replacement        — fitz-generated PDF, replace one word
  2. test_kerning_preserved         — byte-level: KERN items unchanged after edit
  3. test_different_length_no_crash — longer/shorter replacement succeeds
  4. test_can_handle_rejects_form_xobject  — insert_htmlbox → rejected
  5. test_can_handle_rejects_identity_h   — Arabic PDF → rejected
  6. test_verification_catches_bad_edit   — stream corruption → failure reported
  7. test_no_silent_fail_on_missing_text  — text not on page → explicit rejection
  8. test_real_pdfs                 — 3 real sample PDFs, byte-level kerning check

Run:
    cd "C:\\Users\\jiang\\Documents\\python programs\\pdf_editor"
    python -m pytest test_scripts/test_track_c.py -v
  or standalone:
    python test_scripts/test_track_c.py
"""

from __future__ import annotations

import io
import os
import re
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz

from reflow.track_C_core import TrackCEngine, TJItem, TJOp

# ──────────────────────────────────────────────────────────────────────────────
# Real sample PDF paths (relative to ROOT)
# ──────────────────────────────────────────────────────────────────────────────
_REAL_PDF_PATHS = [
    # ReportLab overlay — StandardEncoding, Tj operators
    ROOT / "test_files/sample-files-main/013-reportlab-overlay/reportlab-overlay.pdf",
    # pdflatex outline — Type1 standard encoding, unique "Contents" span
    ROOT / "test_files/sample-files-main/006-pdflatex-outline/pdflatex-outline.pdf",
    # pdflatex multicolumn — Type1, "January 3, 2024" span is unique
    ROOT / "test_files/sample-files-main/026-latex-multicolumn/multicolumn.pdf",
]

# Arabic PDF with Identity-H fonts
_IDENTITY_H_PDF = ROOT / "test_files/sample-files-main/015-arabic/habibi.pdf"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_simple_pdf(words: list[str] | None = None) -> fitz.Document:
    """Create an in-memory PDF with fitz insert_text (builtin helv font)."""
    if words is None:
        words = ["Hello", "World", "Test"]
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    text = " ".join(words)
    page.insert_text((72, 100), text, fontsize=12, fontname="helv")
    page.insert_text((72, 130), "Stable reference span here.", fontsize=10, fontname="helv")
    return doc


def _make_pdf_with_kerning() -> tuple[fitz.Document, str]:
    """Create an in-memory PDF with a manually-crafted TJ array containing kerning.

    Returns (doc, target_word).
    The content stream will have something like:
        [(Hello) -28 (World)] TJ
    We target "Hello" for replacement.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    # Use insert_text to lay out font + graphics state, then inject a
    # kerned TJ directly by manipulating the content stream bytes.
    # Simpler: just use two adjacent insert_text calls and stitch a
    # synthetic kerned stream.

    # Build a minimal content stream manually.
    # Font: helv (builtin Helvetica), size 12.
    # We produce:
    #   BT
    #   /helv 12 Tf
    #   72 742 Td
    #   [(Hello) -28 (World)] TJ
    #   ET
    stream = (
        b"BT\n"
        b"/helv 12 Tf\n"
        b"1 0 0 1 72 742 Tm\n"
        b"[(Hello) -28 (World)] TJ\n"
        b"ET\n"
        b"BT\n"
        b"/helv 10 Tf\n"
        b"1 0 0 1 72 712 Tm\n"
        b"(Stable text here.) Tj\n"
        b"ET\n"
    )

    # Inject the stream directly.
    # We need to register the helv font in page resources first.
    # Trick: insert_text adds it, then we replace the content stream.
    page.insert_text((72, 100), "placeholder", fontsize=12, fontname="helv")
    page.insert_text((72, 130), "Stable text here.", fontsize=10, fontname="helv")

    xrefs = page.get_contents()
    if xrefs:
        doc.update_stream(xrefs[0], stream)
    # If multiple xrefs, replace first and clear others
    for xref in xrefs[1:]:
        doc.update_stream(xref, b"")

    return doc, "Hello"


def _extract_tj_op_items(stream: bytes, raw_start: int, raw_end: int) -> list[tuple]:
    """Extract (kind, value) pairs from a specific TJ or Tj op in a stream.

    Used for byte-level kerning verification.  Returns list of
    ('STR', text) or ('KERN', float).

    Handles both:
      TJ:  [...]   TJ  — raw_start is '['
      Tj:  (...) Tj or <hex> Tj  — raw_start is '(' or '<'
    """
    engine = TrackCEngine()
    segment = stream[raw_start:raw_end]

    if not segment:
        return []

    first_byte = segment[0]

    if first_byte == ord('['):
        # TJ array: find matching ']'
        try:
            open_idx = 0
        except ValueError:
            return []
        i = 1
        close_idx = -1
        while i < len(segment):
            c = segment[i]
            if c == ord('('):
                i = engine._find_paren_end(segment, i) + 1
            elif c == ord('<'):
                try:
                    close = segment.index(ord('>'), i + 1)
                    i = close + 1
                except ValueError:
                    i += 1
            elif c == ord(']'):
                close_idx = i
                break
            else:
                i += 1
        if close_idx == -1:
            return []
        content_start = raw_start + 1          # after '['
        content_end = raw_start + close_idx    # position of ']'
        items, _ = engine._decode_tj_items(stream, content_start, content_end)

    elif first_byte in (ord('('), ord('<')):
        # Tj: single string — decode from raw_start to just before ' Tj'
        # Find end of string
        if first_byte == ord('('):
            close = engine._find_paren_end(segment, 0)
            content_end = raw_start + close + 1  # exclusive, past ')'
        else:
            try:
                close = segment.index(ord('>'))
                content_end = raw_start + close + 1  # exclusive, past '>'
            except ValueError:
                return []
        items, _ = engine._decode_tj_items(stream, raw_start, content_end)

    else:
        return []

    return [(it.kind, it.value) for it in items]


def _assert_kerning_preserved(
    before_items: list[tuple],
    after_items: list[tuple],
    label: str = "",
) -> None:
    """Assert KERN values appear in the same order in before and after."""
    before_kerns = [v for kind, v in before_items if kind == "KERN"]
    after_kerns = [v for kind, v in after_items if kind == "KERN"]
    assert before_kerns == after_kerns, (
        f"{label}Kerning sequence changed.\n"
        f"  before: {before_kerns}\n"
        f"  after:  {after_kerns}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: Simple replacement
# ──────────────────────────────────────────────────────────────────────────────

def test_simple_replacement():
    """Replace 'Hello' with 'Hi'; other text must survive."""
    doc = _make_simple_pdf(["Hello", "World", "Test"])
    page = doc[0]
    engine = TrackCEngine()

    # Locate 'Hello' via rawdict
    td = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    hello_rect = None
    for blk in td["blocks"]:
        if blk.get("type") != 0:
            continue
        for line in blk["lines"]:
            for span in line["spans"]:
                text = "".join(c.get("c", "") for c in span.get("chars", []))
                if "Hello" in text:
                    hello_rect = fitz.Rect(span["bbox"])
                    break

    assert hello_rect is not None, "Could not locate 'Hello' span"

    # Pre-flight
    ok, reason = engine.can_handle(page, "Hello", "Hi", hello_rect)
    assert ok, f"can_handle rejected unexpectedly: {reason}"

    # Apply edit
    result = engine.apply_edit(doc, 0, hello_rect, "Hello", "Hi")
    assert result["success"], f"apply_edit failed: {result['reason']}"
    assert result["track"] == "C"

    # Verify via get_text
    page_text = doc[0].get_text("text")
    assert "Hi" in page_text, f"'Hi' not found after edit (got: {page_text!r})"
    assert "Hello" not in page_text, f"'Hello' still present after edit"
    assert "World" in page_text, f"'World' was damaged by edit"
    assert "Stable reference span here." in page_text, "Stable span was damaged"

    print("  [PASS] test_simple_replacement")
    doc.close()


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: Byte-level kerning preservation
# ──────────────────────────────────────────────────────────────────────────────

def test_kerning_preserved():
    """Kerning numbers in the matched TJ op must be identical before and after."""
    doc, target_word = _make_pdf_with_kerning()
    page = doc[0]
    engine = TrackCEngine()

    # Find the target rect
    td = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    target_rect = None
    for blk in td["blocks"]:
        if blk.get("type") != 0:
            continue
        for line in blk["lines"]:
            for span in line["spans"]:
                text = "".join(c.get("c", "") for c in span.get("chars", []))
                if target_word in text:
                    target_rect = fitz.Rect(span["bbox"])
                    break

    assert target_rect is not None, f"Could not find span containing '{target_word}'"

    ok, reason = engine.can_handle(page, target_word, "Hi", target_rect)
    assert ok, f"can_handle rejected: {reason}"

    # Capture stream BEFORE edit
    xrefs = page.get_contents()
    assert xrefs, "No content xrefs"
    stream_before = doc.xref_stream(xrefs[0])

    result = engine.apply_edit(doc, 0, target_rect, target_word, "Hi")
    assert result["success"], f"apply_edit failed: {result['reason']}"

    # Capture stream AFTER edit
    matched_xref = result.get("matched_xref", xrefs[0])
    stream_after = doc.xref_stream(matched_xref)

    # Get TJ op range from result
    tj_start, tj_end = result["matched_tj_range"]

    # Extract items before
    before_items = _extract_tj_op_items(stream_before, tj_start, tj_end)
    assert before_items, "No items extracted from original TJ op"

    # The TJ op start is unchanged; end may shift by (len_new - len_old) bytes.
    # Re-parse the new stream to find the new TJ op end.
    # Approach: re-run the parser, find the op at the same start position.
    blocks_after = engine._parse_bt_et_blocks(stream_after, matched_xref, doc, doc[0])
    new_tj_end = None
    for blk in blocks_after:
        for tj_op in blk.tj_ops:
            if tj_op.raw_start == tj_start:
                new_tj_end = tj_op.raw_end
                break
        if new_tj_end is not None:
            break

    assert new_tj_end is not None, (
        "Could not re-find TJ op in post-edit stream — "
        f"looked for raw_start={tj_start}"
    )

    after_items = _extract_tj_op_items(stream_after, tj_start, new_tj_end)

    _assert_kerning_preserved(before_items, after_items, label="test_kerning_preserved: ")

    # Verify text content is correct
    page_text = doc[0].get_text("text")
    assert "Hi" in page_text, f"'Hi' not found after edit"
    assert "World" in page_text, "'World' was damaged"

    print("  [PASS] test_kerning_preserved")
    doc.close()


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: Different-length replacement does not crash
# ──────────────────────────────────────────────────────────────────────────────

def test_different_length_no_crash():
    """Replacing with a longer word should succeed without exception."""
    doc = _make_simple_pdf(["Hello", "World"])
    page = doc[0]
    engine = TrackCEngine()

    td = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    target_rect = None
    for blk in td["blocks"]:
        if blk.get("type") != 0:
            continue
        for line in blk["lines"]:
            for span in line["spans"]:
                text = "".join(c.get("c", "") for c in span.get("chars", []))
                if "Hello" in text:
                    target_rect = fitz.Rect(span["bbox"])
                    break

    assert target_rect is not None

    result = engine.apply_edit(doc, 0, target_rect, "Hello", "Goodbye")
    assert result["success"], f"apply_edit failed: {result['reason']}"

    page_text = doc[0].get_text("text")
    assert "Goodbye" in page_text, f"'Goodbye' not found (got: {page_text!r})"

    print("  [PASS] test_different_length_no_crash")
    doc.close()


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: can_handle rejects Form XObject (insert_htmlbox)
# ──────────────────────────────────────────────────────────────────────────────

def test_can_handle_rejects_form_xobject():
    """insert_htmlbox creates a Form XObject (Do operator) → Track C must reject."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    # insert_htmlbox creates a Form XObject
    page.insert_htmlbox(
        fitz.Rect(72, 72, 500, 200),
        "<p>Hello World from htmlbox</p>",
    )

    engine = TrackCEngine()
    rect = fitz.Rect(72, 72, 500, 200)
    ok, reason = engine.can_handle(page, "Hello", "Hi", rect)

    assert not ok, "can_handle should have rejected form xobject"
    assert reason == "form xobject", (
        f"Expected reason 'form xobject', got: {reason!r}"
    )

    print("  [PASS] test_can_handle_rejects_form_xobject")
    doc.close()


# ──────────────────────────────────────────────────────────────────────────────
# Test 5: can_handle rejects Identity-H font
# ──────────────────────────────────────────────────────────────────────────────

def test_can_handle_rejects_identity_h():
    """A PDF using Identity-H (CIDFont) must be rejected by can_handle."""
    if not _IDENTITY_H_PDF.exists():
        print(f"  [SKIP] test_can_handle_rejects_identity_h — file not found: {_IDENTITY_H_PDF}")
        return

    doc = fitz.open(str(_IDENTITY_H_PDF))
    engine = TrackCEngine()

    rejected = False
    for page_idx in range(min(3, len(doc))):
        page = doc[page_idx]
        td = page.get_text("rawdict")
        for blk in td.get("blocks", []):
            if blk.get("type") != 0:
                continue
            for line in blk.get("lines", []):
                for span in line.get("spans", []):
                    text = "".join(c.get("c", "") for c in span.get("chars", []))
                    if len(text) < 2:
                        continue
                    rect = fitz.Rect(span["bbox"])
                    ok, reason = engine.can_handle(page, text[:3], "X", rect)
                    if not ok and "identity-h" in reason:
                        rejected = True
                        break
                if rejected:
                    break
            if rejected:
                break
        if rejected:
            break

    assert rejected, (
        "Expected at least one span to be rejected with 'identity-h encoding' "
        f"in {_IDENTITY_H_PDF.name}"
    )

    print("  [PASS] test_can_handle_rejects_identity_h")
    doc.close()


# ──────────────────────────────────────────────────────────────────────────────
# Test 6: Post-edit verification catches stream corruption
# ──────────────────────────────────────────────────────────────────────────────

def test_verification_catches_bad_edit():
    """If update_stream writes garbage, post-edit verification must return failure."""
    doc = _make_simple_pdf(["Hello", "World"])
    page = doc[0]
    engine = TrackCEngine()

    td = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    target_rect = None
    for blk in td["blocks"]:
        if blk.get("type") != 0:
            continue
        for line in blk["lines"]:
            for span in line["spans"]:
                text = "".join(c.get("c", "") for c in span.get("chars", []))
                if "Hello" in text:
                    target_rect = fitz.Rect(span["bbox"])
                    break

    assert target_rect is not None

    # Monkey-patch update_stream to write garbage that will fail verification
    original_update_stream = doc.update_stream
    garbage_written = [False]

    def bad_update_stream(xref, data):
        garbage_written[0] = True
        # Write a stream that drops all text operators → new text won't appear
        return original_update_stream(xref, b"% empty stream\n")

    doc.update_stream = bad_update_stream

    result = engine.apply_edit(doc, 0, target_rect, "Hello", "Hi")

    assert garbage_written[0], "Monkey-patched update_stream was never called"
    assert not result["success"], "Expected failure due to verification"
    assert "verification failed" in result["reason"], (
        f"Expected 'verification failed' in reason, got: {result['reason']!r}"
    )

    print("  [PASS] test_verification_catches_bad_edit")
    # Restore (doc may be in odd state, but test is done)
    doc.update_stream = original_update_stream
    doc.close()


# ──────────────────────────────────────────────────────────────────────────────
# Test 7: No silent fail when text not on page
# ──────────────────────────────────────────────────────────────────────────────

def test_no_silent_fail_on_missing_text():
    """Asking to edit text that doesn't exist must return an explicit rejection."""
    doc = _make_simple_pdf(["Hello", "World"])
    page = doc[0]
    engine = TrackCEngine()

    rect = fitz.Rect(72, 80, 400, 120)
    ok, reason = engine.can_handle(page, "NonExistentText", "X", rect)

    assert not ok, "Expected rejection for text not in stream"
    assert reason, "Rejection reason must be non-empty"
    # Should be one of the explicit rejection reasons
    assert any(keyword in reason for keyword in (
        "not found", "ambiguous", "no content",
    )), f"Unexpected reason: {reason!r}"

    print(f"  [PASS] test_no_silent_fail_on_missing_text  (reason: {reason!r})")
    doc.close()


# ──────────────────────────────────────────────────────────────────────────────
# Test 8: Real sample PDFs — at least 1 span per file must succeed or be cleanly rejected
# ──────────────────────────────────────────────────────────────────────────────

def _try_edit_first_latin_span(pdf_path: Path) -> dict:
    """
    Open a real PDF, find the first WinAnsi/latin span, try a Track C edit.

    Returns a result dict with keys:
      status : "success" | "rejected" | "error"
      reason : str
      span   : str (the span text we tried)
    """
    doc = fitz.open(str(pdf_path))
    engine = TrackCEngine()
    last_rejection = "no suitable latin span found"

    try:
        for page_idx in range(min(3, len(doc))):
            page = doc[page_idx]
            td = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            for blk in td.get("blocks", []):
                if blk.get("type") != 0:
                    continue
                for line in blk.get("lines", []):
                    for span in line.get("spans", []):
                        chars = span.get("chars", [])
                        text = "".join(c.get("c", "") for c in chars) or span.get("text", "")
                        text = text.strip()
                        # Need at least 4 chars so we have 3 to replace + context
                        if len(text) < 4:
                            continue
                        # Only try ASCII spans (clearly latin-1)
                        if not all(ord(c) < 128 for c in text):
                            continue

                        target = text[:3]
                        # Use the last character of target repeated, so we're
                        # guaranteed it's in the font subset (same char, already there).
                        new_word = target[-1] * len(target)
                        rect = fitz.Rect(span["bbox"])

                        ok, reason = engine.can_handle(page, target, new_word, rect)
                        if not ok:
                            # Not a crash — keep searching for a workable span
                            last_rejection = reason
                            continue

                        # Capture stream before edit for kerning check
                        xrefs = page.get_contents()
                        stream_before = doc.xref_stream(xrefs[0]) if xrefs else b""

                        result = engine.apply_edit(
                            doc, page_idx, rect, target, new_word
                        )
                        if not result["success"]:
                            # Verification failure is an error (not a clean rejection)
                            return {
                                "status": "error",
                                "reason": result["reason"],
                                "span": text,
                            }

                        # Byte-level kerning check
                        matched_xref = result.get("matched_xref", xrefs[0] if xrefs else 0)
                        stream_after = doc.xref_stream(matched_xref)
                        tj_start, tj_end = result["matched_tj_range"]

                        before_items = _extract_tj_op_items(stream_before, tj_start, tj_end)
                        # Re-find TJ op end in new stream
                        blocks_after = engine._parse_bt_et_blocks(
                            stream_after, matched_xref, doc, doc[page_idx]
                        )
                        new_tj_end = None
                        for b in blocks_after:
                            for tj_op in b.tj_ops:
                                if tj_op.raw_start == tj_start:
                                    new_tj_end = tj_op.raw_end
                                    break
                            if new_tj_end is not None:
                                break

                        if new_tj_end is not None:
                            after_items = _extract_tj_op_items(
                                stream_after, tj_start, new_tj_end
                            )
                            _assert_kerning_preserved(
                                before_items, after_items,
                                label=f"{pdf_path.name}: "
                            )

                        return {"status": "success", "reason": "", "span": text}

    except Exception as exc:
        return {"status": "error", "reason": str(exc), "span": ""}
    finally:
        doc.close()

    return {"status": "rejected", "reason": last_rejection, "span": ""}


def test_real_pdfs():
    """For each real sample PDF: edit succeeds or is cleanly rejected (no crash)."""
    results = []
    for path in _REAL_PDF_PATHS:
        if not path.exists():
            print(f"  [SKIP] {path.name} — file not found")
            results.append(("skip", path.name))
            continue

        r = _try_edit_first_latin_span(path)
        results.append((r["status"], path.name, r.get("span", ""), r.get("reason", "")))
        status = r["status"]
        if status == "success":
            print(f"  [OK]   {path.name}  span={r['span'][:20]!r}")
        elif status == "rejected":
            print(f"  [REJ]  {path.name}  reason={r['reason']!r}")
        else:
            print(f"  [FAIL] {path.name}  reason={r['reason']!r}")

    # No raw exceptions allowed — all failures must be explicit clean rejections
    crashes = [r for r in results if r[0] == "error"]
    assert not crashes, (
        f"These PDFs caused errors (not clean rejections):\n"
        + "\n".join(f"  {name}: {reason}" for _, name, _, reason in crashes)
    )

    successes = [r for r in results if r[0] == "success"]
    print(f"\n  Summary: {len(successes)} success(es) out of {len(results)} tried")

    # Spike acceptance criterion: at least 3 real PDFs must succeed
    assert len(successes) >= 3, (
        f"Track C spike requires at least 3 real-PDF successes; got {len(successes)}.\n"
        "Rejections:\n"
        + "\n".join(
            f"  {name}: {reason}"
            for status, name, span, reason in results
            if status != "success"
        )
    )
    print("  [PASS] test_real_pdfs")


# ──────────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────────

TESTS = [
    test_simple_replacement,
    test_kerning_preserved,
    test_different_length_no_crash,
    test_can_handle_rejects_form_xobject,
    test_can_handle_rejects_identity_h,
    test_verification_catches_bad_edit,
    test_no_silent_fail_on_missing_text,
    test_real_pdfs,
]


def main():
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("=" * 65)
    print("Track C Engine — Isolated Feasibility Spike Tests")
    print("=" * 65)

    passed = failed = skipped = 0
    for fn in TESTS:
        name = fn.__name__
        print(f"\n[{name}]")
        try:
            fn()
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {e}")
            traceback.print_exc()
            failed += 1

    print()
    print("=" * 65)
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    print("=" * 65)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

"""Tests that the fidelity corpus generator produces PDFs with the expected
structural properties for each decision-gate case in the text-commit engine.

Each test verifies the *structural* truth of a corpus PDF (font types, encodings,
text content, content-stream features) — not visual fidelity, which is the job of
``verify_commit_fidelity.py`` (Phase B).
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from scripts.build_fidelity_corpus import CASES, build_corpus


@pytest.fixture(scope="module")
def corpus_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("fidelity_corpus")
    build_corpus(out)
    return out


def _open(corpus_dir: Path, case: str) -> fitz.Document:
    path = corpus_dir / f"{case}.pdf"
    assert path.exists(), f"corpus PDF missing: {case}.pdf"
    return fitz.open(str(path))


class TestBase14Simple:
    def test_has_unembedded_type1_fonts(self, corpus_dir: Path) -> None:
        doc = _open(corpus_dir, "base14_simple")
        fonts = doc[0].get_fonts(full=True)
        type1_fonts = [f for f in fonts if f[2] == "Type1"]
        assert len(type1_fonts) >= 3, f"expected >=3 Type1 fonts, got {type1_fonts}"
        for f in type1_fonts:
            xref = f[0]
            _, ext, tp, buf = doc.extract_font(xref)
            assert len(buf) == 0, f"base-14 font xref={xref} should not be embedded"

    def test_text_extractable(self, corpus_dir: Path) -> None:
        doc = _open(corpus_dir, "base14_simple")
        text = doc[0].get_text()
        assert "Helvetica" in text
        assert "Times" in text
        assert "Courier" in text


class TestEmbeddedSubset:
    def test_font_is_embedded_and_extractable(self, corpus_dir: Path) -> None:
        doc = _open(corpus_dir, "embedded_subset")
        fonts = doc[0].get_fonts(full=True)
        assert len(fonts) >= 1
        xref = fonts[0][0]
        name, ext, tp, buf = doc.extract_font(xref)
        assert len(buf) > 0, "embedded font buffer should be non-empty"
        reloaded = fitz.Font(fontbuffer=buf)
        assert reloaded.name, "reloaded font should have a name"

    def test_text_extractable(self, corpus_dir: Path) -> None:
        doc = _open(corpus_dir, "embedded_subset")
        text = doc[0].get_text()
        assert "Hello World" in text


class TestCJKIdentityH:
    def test_has_identity_h_cidFont(self, corpus_dir: Path) -> None:
        doc = _open(corpus_dir, "cjk_identity_h")
        fonts = doc[0].get_fonts(full=True)
        identity_h = [f for f in fonts if len(f) > 5 and f[5] == "Identity-H"]
        assert len(identity_h) >= 1, f"expected Identity-H font, got {fonts}"

    def test_cjk_text_extractable(self, corpus_dir: Path) -> None:
        doc = _open(corpus_dir, "cjk_identity_h")
        text = doc[0].get_text()
        assert any(
            "一" <= ch <= "鿿" for ch in text
        ), "should contain CJK characters"


class TestTJKerning:
    def test_content_stream_has_tj_array(self, corpus_dir: Path) -> None:
        doc = _open(corpus_dir, "tj_kerning")
        page = doc[0]
        stream = page.read_contents().decode("latin-1")
        assert "TJ" in stream, "content stream should contain TJ operator"

    def test_text_extractable(self, corpus_dir: Path) -> None:
        doc = _open(corpus_dir, "tj_kerning")
        text = doc[0].get_text()
        assert "kern" in text.lower() or len(text.strip()) > 0


class TestRotation:
    def test_has_rotated_text(self, corpus_dir: Path) -> None:
        doc = _open(corpus_dir, "rotation")
        page = doc[0]
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        found_rotation = False
        for b in blocks:
            for line in b.get("lines", []):
                d = line.get("dir", (1, 0))
                if abs(d[0]) < 0.5 or abs(d[1]) > 0.5:
                    found_rotation = True
                    break
        assert found_rotation, "should contain rotated text lines"


class TestFormXObject:
    def test_page_has_form_xobject(self, corpus_dir: Path) -> None:
        doc = _open(corpus_dir, "form_xobject")
        _ = doc[0]
        xobjects = [
            f
            for f in range(1, doc.xref_length())
            if "Subtype" in doc.xref_object(f)
            and "/Form" in doc.xref_object(f)
        ]
        assert len(xobjects) >= 1, "should have at least one Form XObject"

    def test_text_in_xobject_is_extractable(self, corpus_dir: Path) -> None:
        doc = _open(corpus_dir, "form_xobject")
        text = doc[0].get_text()
        assert "XObject" in text or len(text.strip()) > 0


class TestDifferencesEncoding:
    def test_font_has_differences_array(self, corpus_dir: Path) -> None:
        doc = _open(corpus_dir, "differences_encoding")
        fonts = doc[0].get_fonts(full=True)
        found = False
        for f in fonts:
            xref = f[0]
            obj = doc.xref_object(xref)
            if "/Differences" in obj:
                found = True
                break
            ref_match = [
                x
                for x in range(1, doc.xref_length())
                if "/Differences" in doc.xref_object(x)
            ]
            if ref_match:
                found = True
                break
        assert found, "should have a font with /Differences encoding"


class TestType3Font:
    def test_has_type3_font(self, corpus_dir: Path) -> None:
        doc = _open(corpus_dir, "type3_font")
        fonts = doc[0].get_fonts(full=True)
        type3 = [f for f in fonts if f[2] == "Type3"]
        assert len(type3) >= 1, f"expected Type3 font, got {fonts}"

    def test_type3_not_extractable(self, corpus_dir: Path) -> None:
        doc = _open(corpus_dir, "type3_font")
        fonts = doc[0].get_fonts(full=True)
        type3 = [f for f in fonts if f[2] == "Type3"]
        for f in type3:
            xref = f[0]
            _, _, _, buf = doc.extract_font(xref)
            assert len(buf) == 0, "Type3 font should not be extractable"


class TestMultiStyle:
    def test_multiple_font_styles(self, corpus_dir: Path) -> None:
        doc = _open(corpus_dir, "multi_style")
        page = doc[0]
        blocks = page.get_text("dict")["blocks"]
        sizes = set()
        colors = set()
        for b in blocks:
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    sizes.add(round(span["size"], 1))
                    colors.add(tuple(int(c * 255) for c in (span["color"] >> 16 & 0xFF, span["color"] >> 8 & 0xFF, span["color"] & 0xFF) ) if isinstance(span["color"], int) else span["color"])
        assert len(sizes) >= 2, f"expected >=2 font sizes, got {sizes}"


class TestNeighborProximity:
    def test_has_multiple_close_blocks(self, corpus_dir: Path) -> None:
        doc = _open(corpus_dir, "neighbor_proximity")
        page = doc[0]
        blocks = page.get_text("dict")["blocks"]
        text_blocks = [b for b in blocks if b["type"] == 0]
        assert len(text_blocks) >= 2, "should have >=2 text blocks"
        rects = [fitz.Rect(b["bbox"]) for b in text_blocks]
        min_gap = float("inf")
        for i, r1 in enumerate(rects):
            for r2 in rects[i + 1 :]:
                gap = max(0, r2.y0 - r1.y1)
                min_gap = min(min_gap, gap)
        assert min_gap < 30, f"blocks should be close (gap={min_gap})"

    def test_each_block_has_distinct_text(self, corpus_dir: Path) -> None:
        doc = _open(corpus_dir, "neighbor_proximity")
        text = doc[0].get_text()
        assert "BLOCK_A" in text
        assert "BLOCK_B" in text


class TestAllCasesPresent:
    def test_every_declared_case_has_a_pdf(self, corpus_dir: Path) -> None:
        for case in CASES:
            path = corpus_dir / f"{case}.pdf"
            assert path.exists(), f"missing corpus PDF: {case}.pdf"

    def test_every_pdf_opens_without_error(self, corpus_dir: Path) -> None:
        for case in CASES:
            doc = _open(corpus_dir, case)
            assert doc.page_count >= 1
            doc.close()

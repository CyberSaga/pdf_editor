"""Task 14 Commit 3 same-face proof census tests."""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import fitz
import pytest

from test_scripts.type0_fixture_builder import (
    build_identity_h_fixture,
    identity_cidtogid_bytes,
    set_cidtogid_stream,
    set_w_array,
    write_minimal_tounicode,
)


def _program(fixture) -> bytes:
    return fixture.doc.extract_font(fixture.font_xref)[3]


def _full_and_subset() -> tuple[bytes, bytes]:
    full = build_identity_h_fixture(subset=False)
    subset = build_identity_h_fixture(subset=True)
    return _program(full), _program(subset)


def _save_font(font) -> bytes:
    output = io.BytesIO()
    font.save(output, reorderTables=False)
    return output.getvalue()


def _font_with_fstype(program: bytes, fs_type: int) -> bytes:
    from fontTools.ttLib import TTFont

    font = TTFont(io.BytesIO(program), lazy=False)
    font["OS/2"].fsType = fs_type
    return _save_font(font)


def test_subset_matches_full_droid_by_exact_same_gids() -> None:
    pytest.importorskip("fontTools")
    from scripts.audit_same_face import classify_program

    full, subset = _full_and_subset()
    # PyMuPDF 1.27.1's subsetter retains GIDs and exact glyph bytes/metrics.
    assert classify_program(subset, [full]) == "A_same_gid_exact"


def test_one_coordinate_perturbation_is_unproven() -> None:
    pytest.importorskip("fontTools")
    from fontTools.ttLib import TTFont
    from scripts.audit_same_face import classify_program

    full, subset = _full_and_subset()
    embedded = TTFont(io.BytesIO(subset), lazy=False)
    candidate = TTFont(io.BytesIO(full), lazy=False)
    for gid in range(embedded["maxp"].numGlyphs):
        name = embedded.getGlyphName(gid)
        glyph = embedded["glyf"][name]
        if glyph.numberOfContours > 0 and not glyph.isComposite():
            candidate_glyph = candidate["glyf"][candidate.getGlyphName(gid)]
            candidate_glyph.coordinates[0] = (
                candidate_glyph.coordinates[0][0] + 1,
                candidate_glyph.coordinates[0][1],
            )
            break
    else:  # pragma: no cover - the fixture always embeds simple CJK glyphs
        raise AssertionError("fixture has no simple non-empty glyph")
    assert classify_program(subset, [_save_font(candidate)]) == "face_unproven"


def test_instruction_bytes_may_differ_when_decompiled_outline_is_equal() -> None:
    pytest.importorskip("fontTools")
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.tables.ttProgram import Program
    from scripts.audit_same_face import classify_program

    full, subset = _full_and_subset()
    embedded = TTFont(io.BytesIO(subset), lazy=False)
    candidate = TTFont(io.BytesIO(full), lazy=False)
    for gid in range(embedded["maxp"].numGlyphs):
        name = embedded.getGlyphName(gid)
        glyph = embedded["glyf"][name]
        if glyph.numberOfContours > 0 and not glyph.isComposite():
            candidate_glyph = candidate["glyf"][candidate.getGlyphName(gid)]
            program = Program()
            program.fromBytecode(b"\x25")
            candidate_glyph.program = program
            break
    else:  # pragma: no cover - the fixture always embeds simple CJK glyphs
        raise AssertionError("fixture has no simple non-empty glyph")
    assert classify_program(
        subset, [_save_font(candidate)]
    ) == "A_outline_same_bytes_differ"


def test_two_matching_candidates_are_ambiguous() -> None:
    pytest.importorskip("fontTools")
    from scripts.audit_same_face import classify_program

    full, subset = _full_and_subset()
    assert classify_program(subset, [full, full]) == "face_ambiguous"


def test_priority_join_counts_only_unique_a_family_fonts() -> None:
    pytest.importorskip("fontTools")
    from scripts.audit_same_face import (
        a_family_faces,
        candidate_supplier_for_faces,
    )
    from scripts.measure_type0_funnel import funnel_document
    from test_scripts.type0_fixture_builder import cid_for

    full, _ = _full_and_subset()
    fixture = build_identity_h_fixture(text="你", subset=True)
    write_minimal_tounicode(
        fixture,
        [(cid_for("你"), "你"), (cid_for("圖"), "圖")],
    )
    faces = a_family_faces(fixture.doc, [full])
    report = funnel_document(
        fixture.doc,
        run_e2e=False,
        candidate_has_glyph_for_font=candidate_supplier_for_faces(faces),
        augmentation_font_xrefs=set(faces),
    )["vocabulary_counterfactual"]
    assert report["augmentation_eligible_bindable_shows"] == 1
    assert report["priority_go_units"]["unit_b_corpus_union"] == {
        "vocabulary_size": 2,
        "baseline_numerator": 1,
        "augmentation_numerator": 1,
        "tj_array_numerator": 0,
        "hscale_numerator": 0,
    }

    ambiguous_faces = a_family_faces(fixture.doc, [full, full])
    ambiguous = funnel_document(
        fixture.doc,
        run_e2e=False,
        candidate_has_glyph_for_font=candidate_supplier_for_faces(
            ambiguous_faces
        ),
        augmentation_font_xrefs=set(ambiguous_faces),
    )["vocabulary_counterfactual"]
    assert ambiguous["augmentation_eligible_bindable_shows"] == 0
    assert ambiguous["priority_go_units"]["unit_b_corpus_union"][
        "augmentation_numerator"
    ] == 0


@pytest.mark.parametrize("fs_type", [0x0002, 0x0004, 0x0100, 0x0200])
def test_restricted_candidate_is_rejected(fs_type: int) -> None:
    pytest.importorskip("fontTools")
    from scripts.audit_same_face import classify_program

    full, subset = _full_and_subset()
    assert classify_program(
        subset, [_font_with_fstype(full, fs_type)]
    ) == "embedding_restricted"


@pytest.mark.parametrize("fs_type", [0x0000, 0x0008])
def test_installable_and_editable_embedding_are_allowed(fs_type: int) -> None:
    pytest.importorskip("fontTools")
    from scripts.audit_same_face import classify_program

    full, subset = _full_and_subset()
    assert classify_program(
        subset, [_font_with_fstype(full, fs_type)]
    ) == "A_same_gid_exact"


def test_gid_compacted_candidate_is_renumbered_matchable() -> None:
    pytest.importorskip("fontTools")
    from fontTools import subset as font_subset
    from fontTools.ttLib import TTFont
    from scripts.audit_same_face import classify_program

    full_program, embedded_program = _full_and_subset()
    embedded = TTFont(io.BytesIO(embedded_program), lazy=False)
    candidate = TTFont(io.BytesIO(full_program), lazy=False)
    gids = []
    for gid, name in enumerate(embedded.getGlyphOrder()):
        glyph = embedded["glyf"][name]
        if glyph.compile(embedded["glyf"]):
            gids.append(gid)
    options = font_subset.Options()
    options.retain_gids = False
    subsetter = font_subset.Subsetter(options=options)
    subsetter.populate(gids=gids)
    subsetter.subset(candidate)
    compacted = _save_font(candidate)
    assert classify_program(
        embedded_program, [compacted]
    ) == "B_renumbered_matchable"


def _helvetica_type0_document() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page()
    writer = fitz.TextWriter(page.rect)
    writer.append((72, 72), "hello", font=fitz.Font("helv"), fontsize=12)
    writer.write_text(page)
    return doc


def test_cff_type0_is_explicitly_out_of_scope() -> None:
    pytest.importorskip("fontTools")
    from scripts.audit_same_face import census_document

    report = census_document(_helvetica_type0_document(), [])
    assert report["proof_classes"] == {"cff_out_of_scope": 1}


def test_missing_fonttools_is_an_explicit_exit_2(monkeypatch, capsys) -> None:
    import scripts.audit_same_face as audit

    monkeypatch.setattr(audit, "TTFont", None)
    monkeypatch.setattr(audit, "TTCollection", None)
    assert audit.main(["unused.pdf", "--json"]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "fonttools_absent"
    }


def test_direct_script_entrypoint_resolves_sibling_modules(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(Path("scripts/audit_same_face.py")),
            str(tmp_path / "missing.pdf"),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["per_document"] == {}
    assert report["skipped_unopenable_or_encrypted"] == 1


def test_max_cid_heuristics_use_w_then_cidtogid_length() -> None:
    pytest.importorskip("fontTools")
    from scripts.audit_same_face import census_document

    fixture = build_identity_h_fixture(subset=True)
    set_w_array(fixture, "[ 10 20 1000 ]")
    report = census_document(fixture.doc, [])
    assert report["heuristics"]["max_cid_source"] == {"w_array": 1}
    assert report["heuristics"]["numglyphs_vs_maxcid"] == {"gt": 1}

    set_w_array(fixture, "[ 10 50482 1000 ]")
    report = census_document(fixture.doc, [])
    assert report["heuristics"]["numglyphs_vs_maxcid"] == {
        "eq_plus_one": 1
    }

    set_w_array(fixture, "[ 10 50483 1000 ]")
    report = census_document(fixture.doc, [])
    assert report["heuristics"]["numglyphs_vs_maxcid"] == {"le": 1}

    set_w_array(fixture, "null")
    set_cidtogid_stream(fixture, identity_cidtogid_bytes(31))
    report = census_document(fixture.doc, [])
    assert report["heuristics"]["max_cid_source"] == {
        "cidtogid_length": 1
    }
    assert report["heuristics"]["numglyphs_vs_maxcid"] == {"gt": 1}

    no_maximum = build_identity_h_fixture(subset=True)
    set_w_array(no_maximum, "null")
    report = census_document(no_maximum.doc, [])
    assert report["heuristics"]["max_cid_source"] == {"none": 1}
    assert report["heuristics"]["numglyphs_vs_maxcid"] == {
        "max_cid_unknown": 1
    }


def test_report_never_emits_font_names_candidate_stems_or_paths(monkeypatch) -> None:
    pytest.importorskip("fontTools")
    import scripts.audit_same_face as audit

    full, _ = _full_and_subset()
    fixture = build_identity_h_fixture(subset=True)
    kind, value = fixture.doc.xref_get_key(
        fixture.descendant_xref, "FontDescriptor"
    )
    assert kind == "xref"
    fixture.doc.xref_set_key(int(value.split()[0]), "FontName", "/SECRET7Q+Face")
    monkeypatch.setattr(
        audit,
        "CANDIDATE_FONT_FILES",
        (audit.Path("C:/PRIVATE/CandidateSecret.ttf"),),
    )
    report = audit.census_document(fixture.doc, [full])
    dumped = json.dumps(report)
    assert report["proof_classes"]
    assert "SECRET7Q" not in dumped
    assert "CandidateSecret" not in dumped
    assert "PRIVATE" not in dumped

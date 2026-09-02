"""P4-B2 commit 5: the shadow-census harness (Stage E).

The harness wraps ``scripts/measure_type0_funnel.py`` without editing it:
``funnel_document`` (pass-through; captures the report and the document
ordinal), ``duplicate_source_painter_detail`` (multiplexer: baseline /
reach / exact per row, baseline returned unchanged) and ``_sole_loss_class``
(recorder).  It refuses to report unless the baseline reproduces the sealed
constants, and emits only closed-slug integer counters.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import measure_type0_funnel  # noqa: E402
from scripts.measure_p4b2_shadow_census import (  # noqa: E402
    EXACT_CELLS,
    REPORT_KEYS,
    SHADOW_COUNTER_KEYS,
    SealedConstants,
    SealedMismatch,
    ShadowCensus,
    _DEVICE_LOAD_BEARING_REASONS,
    _RowRecord,
    main,
    run_shadow_census,
)
from scripts.painter_evidence import EVENT_REASONS  # noqa: E402
from test_scripts.painter_matrix_fixtures import (  # noqa: E402
    hide_second_painter_in_ocg,
)
from test_scripts.test_text_commit_duplicate_painter_gate import (  # noqa: E402
    SOURCE_WIDTH,
    _build_second_show_doc,
)


def _build_corpus_bytes() -> list[bytes]:
    """Two single-page documents: a /W 0 clone twin painting on the target
    (baseline admits, reach rejects, exact overlaps) and an abutting twin
    (baseline admits, reach rejects, exact safe)."""
    overlapping, _ = _build_second_show_doc(
        offset=1.0,
        second_resource="F_CLONE",
        second_clone_font=True,
        second_clone_width=0,
    )
    abutting, _ = _build_second_show_doc(offset=SOURCE_WIDTH)
    try:
        return [overlapping.doc.tobytes(), abutting.doc.tobytes()]
    finally:
        overlapping.doc.close()
        abutting.doc.close()


_CORPUS_BYTES: list[bytes] | None = None


def _corpus() -> list[fitz.Document]:
    global _CORPUS_BYTES
    if _CORPUS_BYTES is None:
        _CORPUS_BYTES = _build_corpus_bytes()
    return [fitz.open("pdf", data) for data in _CORPUS_BYTES]


_SEALED: SealedConstants | None = None


def _sealed_cached(docs: list[fitz.Document]) -> SealedConstants:
    """One baseline census per module: every funnel run on the builder's
    3.5 MB face costs seconds, and the corpus is immutable."""
    global _SEALED
    if _SEALED is None:
        _SEALED = _sealed_for(docs)
    return _SEALED


_REPORT: dict | None = None


def _shared_report() -> dict:
    global _REPORT
    if _REPORT is None:
        docs = _corpus()
        try:
            _REPORT = run_shadow_census(docs, sealed=_sealed_cached(docs))
        finally:
            for doc in docs:
                doc.close()
    return _REPORT


def _sealed_for(docs: list[fitz.Document]) -> SealedConstants:
    """The baseline census numbers for ``docs`` (what a sealed run pins)."""
    totals = {
        "source_bindable": 0,
        "all_gates_pass": 0,
        "duplicate_painter_only": 0,
        "tj_array_only": 0,
        "hscale_only": 0,
    }
    for doc in docs:
        copy = fitz.open("pdf", doc.tobytes())
        try:
            report = measure_type0_funnel.funnel_document(copy, run_e2e=False)
        finally:
            copy.close()
        totals["source_bindable"] += int(report["funnel_shows"]["source_bindable"])
        sole = report["glyph_overlap_census"]["sole_loss"]
        for key in ("all_gates_pass", "duplicate_painter_only", "tj_array_only", "hscale_only"):
            totals[key] += int(sole[key])
    return SealedConstants(**totals)


def _walk_keys(value, out: set[str]) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            out.add(str(key))
            _walk_keys(inner, out)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            _walk_keys(inner, out)


def test_synthetic_corpus_partitions_rows_and_holds_the_identities() -> None:
    docs = _corpus()
    try:
        sealed = _sealed_cached(docs)
    finally:
        for doc in docs:
            doc.close()
    assert sealed.all_gates_pass == 4, sealed
    report = _shared_report()
    assert report["status"] == "ok"
    counters = report["counters"]
    assert set(counters) == set(SHADOW_COUNTER_KEYS)
    assert counters["rows_all_gates_pass"] == 4
    # The /W 0 clone AS A TARGET has a zero-width declared-advance core, so
    # even the reach arm admits its twin (F4 target side): one reach-safe
    # row that the exact arm turns into a same-baseline overlap.
    assert counters["reach_all_gates_pass"] == 1
    assert counters["reach_safe_twin_rows"] == 1
    assert counters["r_exact_overlap_same_baseline"] == 1
    assert counters["delta_rows"] == 3
    assert counters["d_exact_overlap_same_baseline"] == 1
    assert counters["d_exact_safe"] == 2
    assert counters["d_ambiguous"] == counters["d_unavailable"] == counters["d_error"] == 0
    assert counters["composed_all_gates_pass"] == 1 + 2 - 1
    assert counters["twin_ink_in_target_bbox"] == 1
    assert counters["evidence_builds"] == 2
    assert counters["evidence_pages"] == 2
    assert all(report["identities"].values()), report["identities"]
    assert set(report["identities"]) == {
        "d_partition",
        "r_partition",
        "p_partition",
        "delta_identity",
        "composed_identity",
    }
    assert report["sealed"] == {
        "source_bindable": sealed.source_bindable,
        "all_gates_pass": 4,
        "duplicate_painter_only": 0,
        "tj_array_only": 0,
        "hscale_only": 0,
    }


def test_baseline_verdicts_are_returned_unchanged() -> None:
    """The multiplexer must hand the census exactly the baseline answer:
    the wrapped run reproduces a plain run's sole-loss vector."""
    report = _shared_report()
    assert report["status"] == "ok"
    # A run with sealed constants derived from the plain census passed
    # its own assertion: that IS the unchanged-baseline proof.
    assert report["counters"]["gate_calls"] == report["counters"]["rows_all_gates_pass"]


def test_sealed_constant_mismatch_refuses_to_report(capsys) -> None:
    docs = _corpus()
    try:
        sealed = _sealed_cached(docs)
        wrong = SealedConstants(
            source_bindable=sealed.source_bindable,
            all_gates_pass=sealed.all_gates_pass + 1,
            duplicate_painter_only=sealed.duplicate_painter_only,
            tj_array_only=sealed.tj_array_only,
            hscale_only=sealed.hscale_only,
        )
        with pytest.raises(SealedMismatch) as info:
            run_shadow_census(docs, sealed=wrong)
        assert info.value.key == "all_gates_pass"
        assert str(info.value).isascii()
    finally:
        for doc in docs:
            doc.close()


def test_main_refuses_with_nonzero_exit_and_empty_stdout(tmp_path, capsys) -> None:
    docs = _corpus()
    paths = []
    try:
        for index, doc in enumerate(docs):
            path = tmp_path / f"doc{index}.pdf"
            path.write_bytes(doc.tobytes())
            paths.append(str(path))
    finally:
        for doc in docs:
            doc.close()
    code = main([*paths, "--expect", "all_gates_pass=99", "--no-candidate-fonts"])
    captured = capsys.readouterr()
    assert code == 3
    assert captured.out == ""
    assert "sealed_constant_mismatch" in captured.err
    assert "doc0" not in captured.err and "tmp" not in captured.err.lower()


def test_main_emits_closed_key_json_on_a_matching_corpus(tmp_path, capsys) -> None:
    docs = _corpus()
    paths = []
    try:
        sealed = _sealed_cached(docs)
        for index, doc in enumerate(docs):
            path = tmp_path / f"doc{index}.pdf"
            path.write_bytes(doc.tobytes())
            paths.append(str(path))
    finally:
        for doc in docs:
            doc.close()
    expects = [
        "--expect",
        f"source_bindable={sealed.source_bindable}",
        "--expect",
        f"all_gates_pass={sealed.all_gates_pass}",
        "--expect",
        "duplicate_painter_only=0",
        "--expect",
        "tj_array_only=0",
        "--expect",
        "hscale_only=0",
    ]
    code = main([*paths, *expects, "--json", "--no-candidate-fonts"])
    captured = capsys.readouterr()
    assert code == 0
    report = json.loads(captured.out)
    assert set(report) == set(REPORT_KEYS)
    keys: set[str] = set()
    _walk_keys(report, keys)
    assert all(key.isascii() for key in keys)
    assert captured.out.isascii()
    assert "doc0" not in captured.out and str(tmp_path) not in captured.out


def test_privacy_no_identity_reaches_the_report(monkeypatch) -> None:
    """Secret basefont, secret OCG label, secret text, and an exception
    whose message carries a glyph name: none may reach the JSON."""
    overlapping, _ = _build_second_show_doc(
        offset=1.0, second_resource="F_CLONE", second_clone_font=True
    )
    hidden, _ = _build_second_show_doc(offset=1.0)
    docs = [overlapping.doc, hidden.doc]
    try:
        clone_xref = next(
            int(entry[0])
            for entry in overlapping.page.get_fonts(full=True)
            if entry[4] == "F_CLONE"
        )
        overlapping.doc.xref_set_key(clone_xref, "BaseFont", "/SECRET7Q+Face")
        ocg = hide_second_painter_in_ocg(hidden, on=False)
        hidden.doc.xref_set_key(ocg, "Name", "(SECRETLABEL)")
        sealed = _sealed_for(docs)

        import scripts.measure_p4b2_shadow_census as harness

        real_builder = harness.build_page_painter_evidence
        calls = {"n": 0}

        def _flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("SECRET-EXC glyph uni518D failed")
            return real_builder(*args, **kwargs)

        monkeypatch.setattr(harness, "build_page_painter_evidence", _flaky)
        report = run_shadow_census(docs, sealed=sealed)
    finally:
        for doc in docs:
            doc.close()
    text = json.dumps(report)
    assert "SECRET" not in text
    assert "uni518D" not in text
    assert text.isascii()
    keys: set[str] = set()
    _walk_keys(report, keys)
    assert keys <= set(REPORT_KEYS) | set(SHADOW_COUNTER_KEYS) | {
        "d_partition",
        "r_partition",
        "p_partition",
        "delta_identity",
        "composed_identity",
        "source_bindable",
        "all_gates_pass",
        "duplicate_painter_only",
        "tj_array_only",
        "hscale_only",
    }
    counters = report["counters"]
    assert counters["exact_error"] >= 1
    assert counters["twin_oc_hidden"] >= 1
    assert set(EXACT_CELLS) == {
        "exact_safe",
        "exact_overlap_same_baseline",
        "exact_overlap_cross_baseline",
        "ambiguous",
        "unavailable",
        "error",
    }


def _minimal_twin_row(
    twin_reasons: tuple[str | None, ...], exact_reason: str | None = None
) -> _RowRecord:
    """A twin row with no other load-bearing signal set, so only the given
    twin_reasons / exact_reason drive trace/device accounting."""
    return _RowRecord(
        has_twins=True,
        baseline_admits=True,
        reach_admits=True,
        exact_kind="exact_safe",
        exact_reason=exact_reason,
        target_unproven=False,
        twin_ink_in_target_bbox=False,
        twin_kinds=(),
        twin_reasons=twin_reasons,
        tj_twin=False,
        unattributed_overlap=0,
        identity_refuted=0,
        tier0_bbox_would_reject=False,
    )


def test_load_bearing_counter_keys_are_closed_and_present() -> None:
    """Widened accounting: device-only load-bearing rows, the trace/device
    union, and one row_reason.<slug> key per closed EVENT_REASONS slug."""
    assert "device_load_bearing" in SHADOW_COUNTER_KEYS
    assert "trace_or_device_load_bearing" in SHADOW_COUNTER_KEYS
    assert len(EVENT_REASONS) > 0
    for slug in EVENT_REASONS:
        assert f"row_reason.{slug}" in SHADOW_COUNTER_KEYS
    # No duplicate keys: SHADOW_COUNTER_KEYS is now assembled from several
    # generated families, and a collision would be invisible to both the
    # set(...) == set(...) closed-key check and the report()'s dict
    # comprehension (a later value would silently clobber an earlier one).
    assert len(set(SHADOW_COUNTER_KEYS)) == len(SHADOW_COUNTER_KEYS)


def test_device_load_bearing_reasons_are_the_requested_seven() -> None:
    """Requirement (a): all 7 requested device/oracle-only slugs exist in
    the closed EVENT_REASONS set, so none were silently dropped by the
    EVENT_REASONS intersection."""
    assert _DEVICE_LOAD_BEARING_REASONS == {
        "oracle_disagreement",
        "oracle_unavailable",
        "fz_text_shared",
        "degenerate_stroke",
        "no_ink_rect",
        "conservative_overlap",
        "vertical_writing",
    }
    assert _DEVICE_LOAD_BEARING_REASONS <= set(EVENT_REASONS)


def test_device_load_bearing_counts_oracle_only_rows_without_double_counting() -> None:
    """A row whose only load-bearing signal is a device/oracle-only reason
    (oracle_disagreement) must count toward device_load_bearing but not
    trace_load_bearing; the union counter must not double count a row that
    is load-bearing under both rules; and row_reason.<slug> must count
    rows by BOTH twin_reasons and exact_reason, and nothing else."""
    sealed = SealedConstants(
        source_bindable=0,
        all_gates_pass=0,
        duplicate_painter_only=0,
        tj_array_only=0,
        hscale_only=0,
    )
    census = ShadowCensus(sealed)
    # Row A: device-only via a twin reason (oracle_disagreement is not a
    # trace reason).
    census.rows[(0, 0, 0)] = _minimal_twin_row(("oracle_disagreement",))
    # Row B: trace-only via a twin reason (tr_clip is a trace reason, not
    # a device reason).
    census.rows[(0, 0, 1)] = _minimal_twin_row(("tr_clip",))
    # Row C: both a trace and a device reason on the same row (twin
    # reasons).
    census.rows[(0, 0, 2)] = _minimal_twin_row(("oracle_disagreement", "tr_clip"))
    # Row D: device-only, but carried by the EXACT VERDICT's reason, not
    # any twin_reasons entry -- exercises the "or the exact verdict" half
    # of the reasons union.
    census.rows[(0, 0, 3)] = _minimal_twin_row((), exact_reason="oracle_unavailable")
    counters, _ = census.counters()
    assert counters["device_load_bearing"] == 3  # rows A, C, D
    assert counters["trace_load_bearing"] == 2  # rows B, C
    overlap = 1  # row C counted by both rules
    assert counters["trace_or_device_load_bearing"] == 4  # rows A, B, C, D once each
    assert counters["trace_or_device_load_bearing"] == (
        counters["trace_load_bearing"] + counters["device_load_bearing"] - overlap
    )
    # row_reason.* must reflect exactly which rows carried which slug, via
    # either twin_reasons or exact_reason, and no other slug fires.
    assert counters["row_reason.oracle_disagreement"] == 2  # rows A, C
    assert counters["row_reason.tr_clip"] == 2  # rows B, C
    assert counters["row_reason.oracle_unavailable"] == 1  # row D only
    loud_slugs = {"oracle_disagreement", "tr_clip", "oracle_unavailable"}
    for slug in EVENT_REASONS:
        if slug not in loud_slugs:
            assert counters[f"row_reason.{slug}"] == 0, slug


def test_trace_or_device_load_bearing_identity_on_the_synthetic_corpus() -> None:
    """Whatever the actual mix on the synthetic corpus, the union counter
    stays between max(trace, device) and their sum (no double counting,
    no undercounting)."""
    report = _shared_report()
    counters = report["counters"]
    trace = counters["trace_load_bearing"]
    device = counters["device_load_bearing"]
    union = counters["trace_or_device_load_bearing"]
    assert max(trace, device) <= union <= trace + device


def test_row_reason_counters_are_bounded_by_twin_rows() -> None:
    """Every row_reason.<slug> key is present and each counts at most the
    total number of twin rows the census saw."""
    report = _shared_report()
    counters = report["counters"]
    twin_rows = counters["twin_rows"]
    for slug in EVENT_REASONS:
        key = f"row_reason.{slug}"
        assert key in counters
        assert 0 <= counters[key] <= twin_rows


def test_census_module_is_not_edited_by_the_harness() -> None:
    """The wrappers are installed for the duration of a run only."""
    original = (
        measure_type0_funnel.funnel_document,
        measure_type0_funnel.duplicate_source_painter_detail,
        measure_type0_funnel._sole_loss_class,
    )
    _shared_report()
    assert (
        measure_type0_funnel.funnel_document,
        measure_type0_funnel.duplicate_source_painter_detail,
        measure_type0_funnel._sole_loss_class,
    ) == original

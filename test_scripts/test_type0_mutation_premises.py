"""Task 14 synthetic Type0 mutation-premise matrix."""
from __future__ import annotations

import json

from scripts.probe_type0_mutation_premises import (
    probe_p1_cache_visibility,
    probe_p2_array_path,
    probe_p3_descendant_rewrite,
    probe_p4_keep_reopen,
    probe_p5_existing_raster,
    probe_p6_multiobject_revert,
    probe_p7_shared_font_stale,
    probe_p8_encrypted_keep,
    probe_p9_prior_undo,
    run_all,
)


def test_p1_cache_visibility_has_closed_boolean_mechanisms() -> None:
    result = probe_p1_cache_visibility()
    assert set(result) == {
        "inplace_visible",
        "store_shrink_visible",
        "new_xref_visible",
        "reopen_visible",
    }
    assert all(type(value) is bool for value in result.values())


def test_p2_array_path_is_a_closed_informative_slug() -> None:
    result = probe_p2_array_path()
    assert set(result) == {"slug"}
    assert result["slug"] in {
        "ok_value_set",
        "array_destroyed",
        "placeholder_planted",
        "raised",
    }


def test_p3_descendant_rewrite_satisfies_both_storage_forms() -> None:
    result = probe_p3_descendant_rewrite()
    assert result["width_readback_ok_indirect"] is True
    assert result["width_readback_ok_inline"] is True
    assert result["fingerprint_changed"] is True
    assert type(result["snapshot_diff_xrefs_count"]) is int
    assert result["snapshot_diff_xrefs_count"] > 0


def test_p4_replaced_font_survives_keep_reopen() -> None:
    result = probe_p4_keep_reopen()
    assert result["mupdf_readable_after_keep_reopen"] is True
    assert result["render_ink_after_reopen"] is True
    assert result["fonttools_loads"] in (True, "fonttools_absent")
    assert result["length1_updated"] is True


def test_p5_existing_glyph_raster_is_identical() -> None:
    result = probe_p5_existing_raster()
    assert result == {"raster_identical": True, "differing_pixels": 0}


def test_p6_multiobject_revert_restores_decoded_evidence_and_fingerprint() -> None:
    result = probe_p6_multiobject_revert()
    assert result["decoded_identity"] is True
    assert type(result["raw_identity"]) is bool
    assert result["object_identity"] is True
    assert result["fingerprint_restored"] is True


def test_p7_other_page_plan_goes_stale_after_shared_font_mutation() -> None:
    assert probe_p7_shared_font_stale() == {
        "status_stale_plan": True,
        "snapshot_unchanged_by_commit_attempt": True,
        "capability_digest_changed": True,
    }


def test_p8_encrypted_keep_round_trip_renders_after_reauthentication() -> None:
    assert probe_p8_encrypted_keep() == {
        "needs_pass_after_keep_save": True,
        "render_ink_after_reauth": True,
        "tobytes_keep_roundtrip_ok": True,
    }


def test_p9_prior_tier0_undo_is_an_informative_closed_result() -> None:
    result = probe_p9_prior_undo()
    assert set(result) == {
        "undo_refused_stale",
        "doc_unchanged_by_refused_undo",
    }
    assert all(type(value) is bool for value in result.values())


def test_report_is_closed_and_contains_no_fixture_text_or_paths() -> None:
    report = run_all()
    assert set(report) == {f"P{i}" for i in range(1, 10)}
    dumped = json.dumps(report)
    assert "SECRET" not in dumped
    assert ":\\" not in dumped
    assert all(ord(char) < 0x3400 or ord(char) > 0x9FFF for char in dumped)

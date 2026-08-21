"""Task 13 P3-A — replay index spike red matrix (prototypes + harness).

Pins the spike contract from the 2026-08-21 serial analysis round
(plan `plans/task13-p3a-replay-index-spike.md` §4/§7):

- Part A: index key = (page xref, ordered stream xrefs, per-stream
  digests) — the pull-validation base.
- Part B: budget refusal parity — over-budget builds refuse with the
  frozen `content_stream_too_large_for_safe_replay` reason BEFORE any
  tokenization, warm lookups on a refused index re-surface it verbatim
  (never collapse into NO_MATCH/MALFORMED), and the production 4 MiB
  default is never silently disabled.
- Part C: Shape A (materialized ShowOp table) retains production replay
  output unchanged and reports memory accounting.
- Part D: Shape B (sparse index + checkpoints) build — rows mirror
  production shows, page-global evidence is retained (hybrid verdict),
  and checkpoint placement legality (never inside operand runs, never
  inside BI..EI, always at stream starts).
- Part E: Shape B checkpoint-restore equivalence — field-by-field ShowOp
  equality against full replay (float bit-identity on matrices), seq /
  wrapper-id seed continuity, origin_reliable parity, retained
  page-global truth for facts decided AFTER the target (wrapper close /
  crossed_q, malformed, EMC underflow, Do), cross-stream operand drop,
  restore isolation/idempotence.
- Part F: harness contract — stage decomposition names, scenario names,
  data policy (no document text / no paths in the report), budget flag
  default.

Data policy: every fixture-specific string carries the ``7Q`` marker and
must never appear in any harness report output.

Red-light status: written before `scripts/replay_index_spike.py` and
`scripts/benchmark_replay_index_spike.py` exist — every test in Parts
A–F fails at import until the spike lands. The explicitly-labeled
CONTROL tests pin production replay behavior the fixtures rely on and
are green throughout.
"""

from __future__ import annotations

import copy
import inspect as std_inspect
import json
import struct
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.replay import (  # noqa: E402
    DEFAULT_MAX_REPLAY_BYTES,
    PageReplay,
    ShowOp,
    replay_page_streams,
)

from scripts.replay_index_spike import (  # noqa: E402
    Checkpoint,
    IndexKey,
    MaterializedShowTable,
    ReplayIndexRefusedError,
    ShowRow,
    SparseCheckpointIndex,
    index_key_for_streams,
)

# --------------------------------------------------------------------------
# THE frozen literals this matrix pins (house rule: the test keeps its own
# constants; a rename upstream must fail here, never silently follow).
# --------------------------------------------------------------------------
CONTENT_STREAM_TOO_LARGE = "content_stream_too_large_for_safe_replay"

PAGE_XREF = 900


def _bits(values) -> bytes:
    """Bit-exact packing for float sequences (== treats -0.0 == 0.0)."""
    seq = list(values)
    return struct.pack(f"<{len(seq)}d", *seq)


def _assert_show_identical(restored: ShowOp, full: ShowOp) -> None:
    """Field-by-field equality plus float bit-identity on the matrices."""
    assert restored == full
    assert _bits(restored.tm) == _bits(full.tm)
    assert _bits(restored.ctm) == _bits(full.ctm)
    assert _bits(restored.origin_user) == _bits(full.origin_user)
    if full.trm_uniform_scale is None:
        assert restored.trm_uniform_scale is None
    else:
        assert restored.trm_uniform_scale is not None
        assert _bits([restored.trm_uniform_scale]) == _bits([full.trm_uniform_scale])


def _cp_at_or_before(
    index: SparseCheckpointIndex, stream_index: int, offset: int
) -> Checkpoint:
    """The greatest checkpoint positioned at or before (stream, offset)."""
    eligible = [
        c
        for c in index.checkpoints
        if (c.stream_index, c.offset) <= (stream_index, offset)
    ]
    assert eligible, "expected at least the stream-start checkpoint"
    return max(eligible, key=lambda c: (c.stream_index, c.offset))


# --------------------------------------------------------------------------
# Fixtures — raw synthetic content streams (7Q marker throughout).
# --------------------------------------------------------------------------

STATE_RICH = (
    b"0.5 0 0 0.5 10 20 cm "
    b"q 1 Tc 2 Tw q 1.5 0 0 1.5 5 5 cm 3 Tc Q "
    b"BT /F1 12 Tf 110 Tz 14 TL 2 Ts 1 Tr "
    b"10 0 0 10 100 700 Tm (A7Q) Tj "
    b"5 -12 Td (B7Q) Tj T* (C7Q) Tj "
    b"ET Q "
    b"BT 1 0 0 1 50 50 Tm (D7Q) Tj ET"
)

GS_NEST = (
    b"q 1 Tc 0.9 0 0 0.9 0 0 cm q 2 Tc 0.8 0 0 0.8 4 4 cm "
    b"BT /F1 9 Tf 1 0 0 1 30 30 Tm (in7Q) Tj ET "
    b"Q BT /F1 9 Tf 1 0 0 1 31 31 Tm (mid7Q) Tj ET "
    b"Q BT /F1 9 Tf 1 0 0 1 32 32 Tm (out7Q) Tj ET"
)

TJ_ARRAY = b"BT /F1 10 Tf 1 0 0 1 10 10 Tm [ (K) -50 (7Q) ] TJ (tail7Q) Tj ET"

QUOTE_OP = b'BT /F1 10 Tf 14 TL 1 0 0 1 10 40 Tm (first7Q) Tj 0.5 0.25 (word7Q) " ET'

APOSTROPHE_OP = b"BT /F1 10 Tf 16 TL 1 0 0 1 10 90 Tm (l17Q) Tj (l27Q) ' ET"

WRAPPER_SEED = (
    b"/OC /L0 BDC EMC /OC /L1 BDC EMC /OC /L2 BDC EMC "
    b"BT /F1 10 Tf 1 0 0 1 5 5 Tm (pre7Q) Tj ET "
    b"/OC /L3 BDC BT /F1 10 Tf 1 0 0 1 8 8 Tm (tgt7Q) Tj ET EMC"
)

WRAPPER_CLOSE_AFTER = b"/OC /P7Q BDC BT /F1 8 Tf 1 0 0 1 6 6 Tm (tgt7Q) Tj ET EMC"

# The wrapper opens INSIDE the q, so the Q after the target pops below its
# opening gs depth — production sets crossed_q on exactly that shape
# (replay.py Q handler: open_gs_depth > len(gs_stack)); a Q popping back
# TO the opening depth is legal and stays uncrossed.
WRAPPER_CROSSED_Q = b"q /OC /P7Q BDC BT /F1 8 Tf 1 0 0 1 6 6 Tm (tgt7Q) Tj ET Q EMC"

MALFORMED_AFTER = b"BT /F1 8 Tf 1 0 0 1 9 9 Tm (tgt7Q) Tj ET (unterminated7Q"

UNDERFLOW_AFTER = b"BT /F1 8 Tf 1 0 0 1 9 9 Tm (tgt7Q) Tj ET EMC"

DO_AFTER = b"BT /F1 8 Tf 1 0 0 1 9 9 Tm (tgt7Q) Tj ET /Fm7Q Do"

DROPPED_SHOW = b"BT /F1 8 Tf Tj 1 0 0 1 4 4 Tm (a7Q) Tj 0 -10 Td (b7Q) Tj ET"

CROSS_STREAM = [
    (911, b"BT /F1 7 Tf 1 0 0 1 5 5 Tm (s17Q) Tj 5 Tc 100 200"),
    (912, b"Td (s27Q) Tj ET"),
]

DUPLICATE_TARGETS = b"BT /F1 6 Tf 1 0 0 1 3 3 Tm (dup7Q) Tj 0 -12 Td (dup7Q) Tj ET"

Q_UNDERFLOW = b"Q q 5 Tc BT /F1 9 Tf 1 0 0 1 7 7 Tm (u7Q) Tj ET Q"

MIXED_KINDS = b"BT /F1 9 Tf 1 0 0 1 2 2 Tm (K7Q) Tj <4B3751> Tj [ (K) -50 (7Q) ] TJ ET"

INLINE_IMAGE = (
    b"BT /F1 9 Tf 1 0 0 1 12 12 Tm (before7Q) Tj ET "
    b"BI /W 1 /H 1 /BPC 8 /CS /G ID \xde\xad q Q (fake7Q) Tj \xbe EI "
    b"BT /F1 9 Tf 1 0 0 1 13 13 Tm (after7Q) Tj ET"
)

NEAR_EPSILON = (
    b"q 1 0.0000009 0 1 0 0 cm "
    b"BT /F1 10 Tf 1 0 0 1 4 4 Tm (r7Q) Tj ET Q "
    b"q 1 0.0000011 0 1 0 0 cm "
    b"BT /F1 10 Tf 1 0 0 1 4 4 Tm (s7Q) Tj ET Q"
)

RELIABLE_PAIR = b"BT /F1 9 Tf 1 0 0 1 20 20 Tm (p7Q) Tj (q7Q) Tj 0 -11 Td (r7Q) Tj ET"


def _streams(data: bytes, xref: int = 905) -> list[tuple[int, bytes]]:
    return [(xref, data)]


def _build_b(
    data_or_streams, interval: int = 1
) -> tuple[SparseCheckpointIndex, PageReplay, list[tuple[int, bytes]]]:
    streams = (
        data_or_streams
        if isinstance(data_or_streams, list)
        else _streams(data_or_streams)
    )
    index = SparseCheckpointIndex.build(
        PAGE_XREF, streams, checkpoint_interval_ops=interval
    )
    full = replay_page_streams(streams)
    return index, full, streams


# ============================================================== Part A: key


def test_index_key_stable_for_identical_streams():
    streams = _streams(STATE_RICH)
    key = index_key_for_streams(PAGE_XREF, streams)
    assert isinstance(key, IndexKey)
    assert key == index_key_for_streams(PAGE_XREF, [(905, bytes(STATE_RICH))])


def test_index_key_changes_when_any_stream_byte_changes():
    base = index_key_for_streams(PAGE_XREF, _streams(STATE_RICH))
    mutated = index_key_for_streams(PAGE_XREF, _streams(STATE_RICH + b" "))
    assert base != mutated
    assert base.stream_digests != mutated.stream_digests


def test_index_key_changes_when_stream_order_changes():
    two = [(911, b"1 Tc"), (912, b"2 Tw")]
    swapped = [(912, b"2 Tw"), (911, b"1 Tc")]
    assert index_key_for_streams(PAGE_XREF, two) != index_key_for_streams(
        PAGE_XREF, swapped
    )


# =========================================================== Part B: budget


def _over_budget_streams() -> list[tuple[int, bytes]]:
    big = b"%" + b"x" * DEFAULT_MAX_REPLAY_BYTES
    return [(931, big)]


def _bomb(*_args, **_kwargs):
    raise AssertionError("lexer must not run on an over-budget page")


def test_shape_a_over_budget_build_refuses_verbatim_without_lexing(
    monkeypatch,
):
    import model.text_commit.replay as replay_mod
    import scripts.replay_index_spike as spike_mod

    monkeypatch.setattr(replay_mod, "lex_content_stream", _bomb)
    monkeypatch.setattr(spike_mod, "lex_content_stream", _bomb)
    table = MaterializedShowTable.build(PAGE_XREF, _over_budget_streams())
    assert table.refusal_reason == CONTENT_STREAM_TOO_LARGE
    # Review round F4: a refused Shape A lookup must SURFACE the refusal,
    # never collapse into an empty miss (production refusal carries
    # shows=(), so an unguarded scan would silently return ()).
    with pytest.raises(ReplayIndexRefusedError) as caught:
        table.lookup(b"K7Q")
    assert caught.value.reason == CONTENT_STREAM_TOO_LARGE


def test_shape_b_over_budget_build_refuses_verbatim_without_lexing(
    monkeypatch,
):
    import model.text_commit.replay as replay_mod
    import scripts.replay_index_spike as spike_mod

    monkeypatch.setattr(replay_mod, "lex_content_stream", _bomb)
    monkeypatch.setattr(spike_mod, "lex_content_stream", _bomb)
    index = SparseCheckpointIndex.build(PAGE_XREF, _over_budget_streams())
    assert index.refusal_reason == CONTENT_STREAM_TOO_LARGE
    assert index.rows == ()
    assert index.checkpoints == ()


def test_shape_b_warm_lookup_on_refused_index_surfaces_refusal(monkeypatch):
    streams = _over_budget_streams()
    index = SparseCheckpointIndex.build(PAGE_XREF, streams)

    import scripts.replay_index_spike as spike_mod

    monkeypatch.setattr(spike_mod, "lex_content_stream", _bomb)
    with pytest.raises(ReplayIndexRefusedError) as first:
        index.candidate_seqs(streams, b"K7Q")
    assert first.value.reason == CONTENT_STREAM_TOO_LARGE
    with pytest.raises(ReplayIndexRefusedError) as second:
        index.restore_show(streams, 0)
    assert second.value.reason == CONTENT_STREAM_TOO_LARGE


def test_within_budget_build_does_not_refuse():
    index, full, _ = _build_b(STATE_RICH)
    assert index.refusal_reason is None
    assert full.refusal_reason is None
    table = MaterializedShowTable.build(PAGE_XREF, _streams(STATE_RICH))
    assert table.refusal_reason is None


def test_build_defaults_use_the_production_budget():
    for builder in (MaterializedShowTable.build, SparseCheckpointIndex.build):
        parameters = std_inspect.signature(builder).parameters
        assert parameters["max_decoded_bytes"].default is DEFAULT_MAX_REPLAY_BYTES


# ========================================================== Part C: Shape A


def test_shape_a_build_retains_production_replay_output():
    streams = _streams(WRAPPER_CROSSED_Q)
    table = MaterializedShowTable.build(PAGE_XREF, streams)
    full = replay_page_streams(streams)
    assert table.replay.shows == full.shows
    assert table.replay.mc_wrappers == full.mc_wrappers
    assert table.replay.malformed == full.malformed
    assert table.replay.has_xobject_invocation == full.has_xobject_invocation
    assert table.replay.mc_emc_underflows == full.mc_emc_underflows
    assert table.replay.stream_xrefs == full.stream_xrefs


def test_shape_a_lookup_returns_matching_shows():
    table = MaterializedShowTable.build(PAGE_XREF, _streams(MIXED_KINDS))
    hits = table.lookup(b"K7Q")
    assert len(hits) == 3
    assert [s.string_kind for s in hits] == ["literal", "hex", "array"]
    assert table.lookup(b"absent7Q") == ()


def test_shape_a_memory_footprint_reports_accounting_keys():
    table = MaterializedShowTable.build(PAGE_XREF, _streams(STATE_RICH))
    footprint = table.memory_footprint()
    for key in ("total_bytes", "n_shows", "decoded_bytes_total", "bytes_per_show"):
        assert key in footprint
    assert footprint["n_shows"] == 4
    assert footprint["total_bytes"] > 0


# ==================================================== Part D: Shape B build


def test_shape_b_build_mirrors_production_replay():
    index, full, _ = _build_b(WRAPPER_SEED, interval=4)
    assert len(index.rows) == len(full.shows)
    for row, show in zip(index.rows, full.shows):
        assert isinstance(row, ShowRow)
        assert row.seq == show.seq
        assert row.stream_index == 0
        assert row.operator == show.operator
        assert row.string_kind == show.string_kind
        assert row.op_start == show.op_start
        assert row.op_end == show.op_end
        assert row.string_start == show.string_start
        assert row.string_end == show.string_end
        assert row.array_item_count == show.array_item_count
        assert row.decoded_len == len(show.decoded_bytes)
    assert index.mc_wrappers == full.mc_wrappers
    assert index.malformed == full.malformed
    assert index.has_xobject_invocation == full.has_xobject_invocation
    assert index.mc_emc_underflows == full.mc_emc_underflows
    assert index.stream_xrefs == full.stream_xrefs


def test_checkpoint_sites_never_inside_operand_runs():
    for fixture in (TJ_ARRAY, QUOTE_OP, STATE_RICH):
        index, full, _ = _build_b(fixture, interval=1)
        for show in full.shows:
            for checkpoint in index.checkpoints:
                if checkpoint.stream_index != 0:
                    continue
                inside = show.op_start < checkpoint.offset < show.op_end
                assert not inside, (
                    f"checkpoint at {checkpoint.offset} sits inside the "
                    f"operand run [{show.op_start}, {show.op_end}) of "
                    f"seq {show.seq}"
                )


def test_checkpoint_sites_never_inside_inline_image():
    index, _, _ = _build_b(INLINE_IMAGE, interval=1)
    zone_start = INLINE_IMAGE.index(b"BI ")
    zone_end = INLINE_IMAGE.index(b" EI ") + len(b" EI ")
    for checkpoint in index.checkpoints:
        assert not (zone_start < checkpoint.offset < zone_end), (
            f"checkpoint at {checkpoint.offset} sits inside the BI..EI "
            f"zone [{zone_start}, {zone_end})"
        )


def test_stream_start_checkpoints_always_present():
    index, _, _ = _build_b(CROSS_STREAM, interval=10_000)
    positions = {(c.stream_index, c.offset) for c in index.checkpoints}
    assert (0, 0) in positions
    assert (1, 0) in positions


# ================================================== Part E: restore parity


def test_restored_show_equals_full_replay_field_by_field():
    index, full, streams = _build_b(STATE_RICH, interval=1)
    assert len(full.shows) == 4
    for show in full.shows:
        restored = index.restore_show(streams, show.seq)
        _assert_show_identical(restored, show)


def test_gs_stack_contents_restored_not_just_depth():
    index, full, streams = _build_b(GS_NEST, interval=1)
    first_q = GS_NEST.index(b" Q ") + 1
    checkpoint = _cp_at_or_before(index, 0, first_q)
    by_text = {s.decoded_bytes: s for s in full.shows}
    for target in (b"mid7Q", b"out7Q"):
        restored = index.restore_show(
            streams, by_text[target].seq, from_checkpoint=checkpoint
        )
        _assert_show_identical(restored, by_text[target])
    assert by_text[b"mid7Q"].char_spacing == 1.0
    assert by_text[b"out7Q"].char_spacing == 0.0


def test_tlm_and_leading_carry_for_line_advances():
    index, full, streams = _build_b(STATE_RICH, interval=1)
    t_star_show = full.shows[2]  # (C7Q), positioned by T*
    tm_pos = STATE_RICH.index(b"Tm ")
    checkpoint = _cp_at_or_before(index, 0, tm_pos + 3)
    restored = index.restore_show(streams, t_star_show.seq, from_checkpoint=checkpoint)
    _assert_show_identical(restored, t_star_show)

    index2, full2, streams2 = _build_b(APOSTROPHE_OP, interval=1)
    quote_show = full2.shows[1]
    assert quote_show.operator == "'"
    restored2 = index2.restore_show(streams2, quote_show.seq)
    _assert_show_identical(restored2, quote_show)
    assert restored2.origin_reliable is True


def test_quote_operator_row_and_restore():
    index, full, streams = _build_b(QUOTE_OP, interval=1)
    quote_show = full.shows[1]
    assert quote_show.operator == '"'
    row = index.rows[1]
    assert row.op_start == quote_show.op_start
    assert quote_show.op_start < quote_show.string_start
    restored = index.restore_show(streams, quote_show.seq)
    _assert_show_identical(restored, quote_show)
    assert restored.word_spacing == 0.5
    assert restored.char_spacing == 0.25


def test_seq_continuity_including_dropped_malformed_shows():
    index, full, streams = _build_b(DROPPED_SHOW, interval=1)
    assert full.malformed  # the bare Tj records nothing and poisons the page
    assert [s.seq for s in full.shows] == [0, 1]
    assert index.malformed is True
    for show in full.shows:
        restored = index.restore_show(streams, show.seq)
        _assert_show_identical(restored, show)


def test_origin_reliable_parity_across_checkpoint_both_directions():
    index, full, streams = _build_b(RELIABLE_PAIR, interval=1)
    assert [s.origin_reliable for s in full.shows] == [True, False, True]
    for show in full.shows:
        restored = index.restore_show(streams, show.seq)
        assert restored.origin_reliable == show.origin_reliable
        _assert_show_identical(restored, show)


def test_wrapper_id_seed_after_closed_wrappers():
    index, full, streams = _build_b(WRAPPER_SEED, interval=1)
    target = full.shows[1]
    assert target.decoded_bytes == b"tgt7Q"
    assert target.mc_stack == (3,)
    l3_pos = WRAPPER_SEED.index(b"/L3")
    checkpoint = _cp_at_or_before(index, 0, l3_pos)
    assert checkpoint.wrapper_seed == 3
    restored = index.restore_show(streams, target.seq, from_checkpoint=checkpoint)
    _assert_show_identical(restored, target)
    assert restored.mc_stack == (3,)
    resolved = index.mc_wrappers[restored.mc_stack[0]]
    assert resolved == full.mc_wrappers[3]


def test_wrapper_close_after_target_served_from_retained_table():
    index, full, streams = _build_b(WRAPPER_CLOSE_AFTER, interval=1)
    target = full.shows[0]
    restored = index.restore_show(streams, target.seq)
    _assert_show_identical(restored, target)
    wrapper = index.mc_wrappers[restored.mc_stack[0]]
    assert wrapper.closed is True
    assert wrapper.close_op_start == full.mc_wrappers[0].close_op_start
    assert wrapper.close_stream_xref == full.mc_wrappers[0].close_stream_xref


def test_crossed_q_after_target_served_from_retained_table():
    index, full, streams = _build_b(WRAPPER_CROSSED_Q, interval=1)
    target = full.shows[0]
    restored = index.restore_show(streams, target.seq)
    _assert_show_identical(restored, target)
    wrapper = index.mc_wrappers[restored.mc_stack[0]]
    assert wrapper.crossed_q is True


def test_malformed_after_target_is_page_global():
    index, full, streams = _build_b(MALFORMED_AFTER, interval=1)
    assert full.malformed
    assert index.malformed is True
    restored = index.restore_show(streams, 0)
    _assert_show_identical(restored, full.shows[0])


def test_emc_underflow_after_target_is_page_global():
    index, full, _ = _build_b(UNDERFLOW_AFTER, interval=1)
    assert full.mc_emc_underflows == 1
    assert index.mc_emc_underflows == 1


def test_do_after_target_is_page_global():
    index, full, _ = _build_b(DO_AFTER, interval=1)
    assert full.has_xobject_invocation
    assert index.has_xobject_invocation is True


def test_cross_stream_restore_drops_dangling_operands():
    index, full, streams = _build_b(CROSS_STREAM, interval=1)
    assert full.malformed  # the orphaned Td in stream 2
    second = full.shows[1]
    assert second.decoded_bytes == b"s27Q"
    assert second.char_spacing == 5.0  # Tc applied within stream 1 carries
    checkpoint = _cp_at_or_before(index, 1, 0)
    assert (checkpoint.stream_index, checkpoint.offset) == (1, 0)
    restored = index.restore_show(streams, second.seq, from_checkpoint=checkpoint)
    _assert_show_identical(restored, second)
    assert index.malformed is True


def test_duplicate_targets_straddling_checkpoints():
    index, full, streams = _build_b(DUPLICATE_TARGETS, interval=1)
    seqs = index.candidate_seqs(streams, b"dup7Q")
    assert seqs == (0, 1)
    for seq in seqs:
        restored = index.restore_show(streams, seq)
        _assert_show_identical(restored, full.shows[seq])
    assert _bits(full.shows[0].origin_user) != _bits(full.shows[1].origin_user)


def test_q_underflow_before_checkpoint_is_a_noop():
    index, full, streams = _build_b(Q_UNDERFLOW, interval=1)
    assert not full.malformed
    restored = index.restore_show(streams, 0)
    _assert_show_identical(restored, full.shows[0])
    assert restored.char_spacing == 5.0
    assert restored.gs_depth == 1


def test_trm_uniform_scale_parity_near_epsilon():
    index, full, streams = _build_b(NEAR_EPSILON, interval=1)
    residual_in, residual_out = full.shows
    assert residual_in.trm_uniform_scale is not None  # |b| = 9e-7 <= eps
    assert residual_out.trm_uniform_scale is None  # |b| = 1.1e-6 > eps
    for show in full.shows:
        restored = index.restore_show(streams, show.seq)
        _assert_show_identical(restored, show)


def test_inline_image_between_checkpoint_and_target():
    index, full, streams = _build_b(INLINE_IMAGE, interval=1)
    assert [s.decoded_bytes for s in full.shows] == [b"before7Q", b"after7Q"]
    for show in full.shows:
        restored = index.restore_show(streams, show.seq)
        _assert_show_identical(restored, show)


def test_candidate_seqs_lazy_decode_matches_production():
    index, full, streams = _build_b(MIXED_KINDS, interval=4)
    expected = tuple(s.seq for s in full.shows if s.decoded_bytes == b"K7Q")
    assert expected == (0, 1, 2)
    assert index.candidate_seqs(streams, b"K7Q") == expected
    assert index.candidate_seqs(streams, b"absent7Q") == ()


def test_restores_are_isolated_and_idempotent():
    index, full, streams = _build_b(WRAPPER_CROSSED_Q, interval=1)
    before_checkpoints = copy.deepcopy(index.checkpoints)
    before_wrappers = copy.deepcopy(index.mc_wrappers)
    first = index.restore_show(streams, 0)
    second = index.restore_show(streams, 0)
    _assert_show_identical(first, full.shows[0])
    _assert_show_identical(second, first)
    assert index.checkpoints == before_checkpoints
    assert index.mc_wrappers == before_wrappers


def test_sparse_interval_default_nearest_restore_parity():
    """Review round F6: the harness restores via DEFAULT nearest-checkpoint
    selection at a sparse interval — pin field-by-field parity for every
    show without interval=1 crutches or explicit from_checkpoint."""
    for fixture in (STATE_RICH, GS_NEST, CROSS_STREAM):
        index, full, streams = _build_b(fixture, interval=8)
        assert full.shows, "fixture must produce shows"
        for show in full.shows:
            restored = index.restore_show(streams, show.seq)
            _assert_show_identical(restored, show)


def test_shape_b_memory_footprint_reports_accounting_keys():
    index, _, _ = _build_b(STATE_RICH, interval=1)
    footprint = index.memory_footprint()
    for key in (
        "total_bytes",
        "n_rows",
        "n_checkpoints",
        "rows_bytes",
        "checkpoints_bytes",
    ):
        assert key in footprint
    assert footprint["n_rows"] == 4
    assert footprint["n_checkpoints"] >= 1
    assert footprint["total_bytes"] > 0


# ========================================================= Part F: harness


def _harness():
    import scripts.benchmark_replay_index_spike as harness_mod

    return harness_mod


def test_harness_stage_and_scenario_names_are_pinned():
    harness = _harness()
    # key_validation is the pull-validation cost (re-read + digest compare)
    # the plan §4 contract charges to EVERY warm lookup — review round F3.
    assert set(harness.STAGE_NAMES) == {
        "read_streams",
        "replay",
        "bind",
        "fingerprint",
        "prepare_plan",
        "engine_prepare",
        "key_validation",
        "shape_a_build",
        "shape_a_lookup",
        "shape_b_build",
        "shape_b_lookup",
    }
    assert set(harness.SCENARIO_NAMES) == {
        "cold_first_edit",
        "warm_second_target",
        "warm_changed_replacement",
        "post_mutation_rebuild",
        "different_page",
    }


def test_harness_unbounded_flag_defaults_off():
    harness = _harness()
    parameters = std_inspect.signature(harness.measure_document).parameters
    assert parameters["unbounded"].default is False


def test_harness_report_carries_no_text_or_paths(tmp_path):
    harness = _harness()
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((72, 100), "sentinel7Q text", fontsize=11)
    marker_path = tmp_path / "secret7Qdir" / "doc7Q.pdf"
    marker_path.parent.mkdir()
    doc.save(marker_path)
    doc.close()
    reopened = fitz.open(marker_path)
    try:
        report = harness.measure_document(reopened, label="doc_probe", iterations=1)
    finally:
        reopened.close()
    assert report["label"] == "doc_probe"
    serialized = json.dumps(report)
    assert "7Q" not in serialized
    assert "secret" not in serialized
    # Review round F8: json.dumps escapes backslashes, so the raw Windows
    # path can never match — assert the JSON-ENCODED spelling (and the
    # forward-slash form) so a verbatim path embedding is actually caught.
    assert json.dumps(str(tmp_path))[1:-1] not in serialized
    assert tmp_path.as_posix() not in serialized
    for stage in harness.STAGE_NAMES:
        assert stage in report["stages"]


# ===================================================== explicit CONTROLS


def test_control_production_replay_on_state_rich_fixture():
    """CONTROL (green throughout): pins the production replay facts the
    fixtures above rely on — show counts, malformed flags, wrapper
    evidence — so a fixture drifting out from under the matrix fails
    HERE, not silently in a spike test."""
    full = replay_page_streams(_streams(STATE_RICH))
    assert not full.malformed
    assert [s.decoded_bytes for s in full.shows] == [
        b"A7Q",
        b"B7Q",
        b"C7Q",
        b"D7Q",
    ]
    assert full.shows[0].char_spacing == 1.0  # inner 3 Tc was Q-restored
    assert full.shows[0].hscale == 110.0
    assert full.shows[0].rise == 2.0
    assert full.shows[0].render_mode == 1


def test_control_wrapper_fixtures_produce_expected_evidence():
    """CONTROL (green throughout): wrapper fixtures behave as claimed."""
    seed_replay = replay_page_streams(_streams(WRAPPER_SEED))
    assert len(seed_replay.mc_wrappers) == 4
    assert seed_replay.shows[1].mc_stack == (3,)

    crossed = replay_page_streams(_streams(WRAPPER_CROSSED_Q))
    assert crossed.mc_wrappers[0].crossed_q is True

    closed = replay_page_streams(_streams(WRAPPER_CLOSE_AFTER))
    assert closed.mc_wrappers[0].closed is True

    inline = replay_page_streams(_streams(INLINE_IMAGE))
    assert not inline.malformed
    assert [s.decoded_bytes for s in inline.shows] == [
        b"before7Q",
        b"after7Q",
    ]

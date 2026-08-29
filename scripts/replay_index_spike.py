"""Task 13 P3-A spike prototypes: two replay-index shapes. NOT production.

Shape A (:class:`MaterializedShowTable`) retains the full production
``PageReplay`` per page generation; warm lookups scan the retained shows.

Shape B (:class:`SparseCheckpointIndex`) retains sparse per-show rows,
periodic interpreter-state checkpoints, and — per the 2026-08-21 analysis
round (plan ``plans/task13-p3a-replay-index-spike.md`` §7) — a page-global
evidence block (wrapper table, malformed / xobject / underflow verdicts,
refusal) that a truncated local replay structurally cannot compute: the
hybrid is mandatory, and local-replay output is NEVER served as wrapper
evidence or page verdicts.

``_replay_core`` is a PARAMETERIZED COPY of the production operator loop
(``model/text_commit/replay.py`` — which has no initial-state or
start-offset parameters, and P3-A must not touch ``model/``).  Every
helper (``_State``, ``_Operand``, ``_McRecord``, ``_parse_mc_operands``,
matrix math, string decoding) is imported from the production module so
only the loop body is duplicated; the red matrix in
``test_scripts/test_replay_index_spike.py`` pins build-equals-production
and field-by-field restore equivalence as the drift net.  A production
P3-B implementation must parameterize the production loop instead.

Checkpoint placement (analysis-round contract): only where the operand
list is empty (immediately after an operator dispatch, or a stream
start), never after ``BI``/``ID``/``EI`` (conservative BI..EI exclusion —
after ``ID`` the operands ARE empty but a restart would lex the binary
payload), at token-boundary offsets captured during the build lex.

Budget: builds refuse over-``max_decoded_bytes`` input BEFORE any
tokenization with the frozen verbatim reason
``content_stream_too_large_for_safe_replay``; warm lookups on a refused
index raise :class:`ReplayIndexRefusedError` carrying it — the refusal is
never collapsed into an empty result.
"""

from __future__ import annotations

import hashlib
import logging
import sys
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Callable

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.pdf_lexer import (  # noqa: E402
    TokenKind,
    lex_content_stream,
)
from model.text_commit.replay import (  # noqa: E402
    DEFAULT_MAX_REPLAY_BYTES,
    Matrix,
    McWrapper,
    PageReplay,
    ShowOp,
    _decode_operand_string,
    _mat_apply,
    _mat_mul,
    _McRecord,
    _Operand,
    _State,
    _translate,
    _uniform_scale,
    replay_page_streams,
)
from model.text_commit.replay import (  # noqa: E402
    _parse_mc_operands as _production_parse_mc_operands,
)
from model.text_commit.replay import (  # noqa: E402
    _STRING_KINDS,
    _TRIVIA,
)

logger = logging.getLogger(__name__)

_IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# Operators after which a checkpoint must NOT be emitted: the conservative
# BI..EI exclusion from the placement contract.
_NO_CHECKPOINT_AFTER = (b"BI", b"ID", b"EI")


class ReplayIndexRefusedError(RuntimeError):
    """A warm lookup against an index whose build refused (resource guard).

    ``reason`` carries the retained refusal verbatim so callers surface it
    exactly as the cold path would — never collapsed into a miss.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class IndexKey:
    """Pull-validation identity: ordered stream xrefs + per-stream digests."""

    page_xref: int
    stream_xrefs: tuple[int, ...]
    stream_digests: tuple[str, ...]


def index_key_for_streams(page_xref: int, streams: list[tuple[int, bytes]]) -> IndexKey:
    return IndexKey(
        page_xref=page_xref,
        stream_xrefs=tuple(xref for xref, _ in streams),
        stream_digests=tuple(hashlib.sha256(data).hexdigest() for _, data in streams),
    )


@dataclass(frozen=True)
class ShowRow:
    """Sparse per-show row: offsets and identity, no interpreter state."""

    seq: int
    stream_index: int
    operator: str
    string_kind: str
    op_start: int
    op_end: int
    string_start: int
    string_end: int
    array_item_count: int
    decoded_len: int


@dataclass(frozen=True)
class Checkpoint:
    """Complete interpreter state at a legal resume site (contract §7)."""

    stream_index: int
    offset: int
    state: tuple  # _State.snapshot() 9-tuple
    gs_stack: tuple[tuple, ...]  # FULL stack contents, not depth
    tm: Matrix
    tlm: Matrix
    in_bt: bool
    mc_depth: int
    mc_open: tuple[int, ...]
    open_wrapper_gs_depths: tuple[int, ...]  # parallel to mc_open
    wrapper_seed: int  # len(mc_records) at capture — id continuity
    show_seed: int  # len(shows) at capture — seq continuity
    advance_pending: bool


@dataclass
class _CoreResult:
    shows: list[ShowOp]
    show_stream_indices: list[int]
    malformed: bool
    has_xobject: bool
    mc_emc_underflows: int
    mc_records: dict[int, _McRecord]
    next_wrapper_id: int


def _replay_core(
    streams: list[tuple[int, bytes]],
    *,
    start_stream: int = 0,
    start_offset: int = 0,
    state: _State | None = None,
    gs_stack: list[tuple] | None = None,
    tm: Matrix = _IDENTITY,
    tlm: Matrix = _IDENTITY,
    in_bt: bool = False,
    mc_depth: int = 0,
    mc_open: list[int] | None = None,
    mc_records: dict[int, _McRecord] | None = None,
    next_wrapper_id: int = 0,
    next_seq: int = 0,
    advance_pending: bool = False,
    stop_after_seq: int | None = None,
    on_site: Callable[[int, int, int], None] | None = None,
    scalar_mirror: dict[str, object] | None = None,
) -> _CoreResult:
    """The production replay loop, parameterized for build and resume.

    Semantics are transcribed 1:1 from ``replay_page_streams`` (the red
    matrix pins the equivalence); the only additions are the start
    position, the seeded counters, the ``stop_after_seq`` early return,
    and the build-instrumentation seam: ``on_site(stream_index, offset,
    dispatched_ops)`` fires at every legal checkpoint site, with the
    loop's scalar locals (tm/tlm/in_bt/mc_depth/advance_pending/show
    count) mirrored into ``scalar_mirror`` immediately before each call
    so the capture closure can snapshot them synchronously.
    """
    state = state if state is not None else _State()
    gs_stack = gs_stack if gs_stack is not None else []
    mc_open = mc_open if mc_open is not None else []
    mc_records = mc_records if mc_records is not None else {}

    shows: list[ShowOp] = []
    show_stream_indices: list[int] = []
    malformed = False
    has_xobject = False
    mc_emc_underflows = 0
    dispatched = 0

    def _mirror_scalars() -> None:
        if scalar_mirror is None:
            return
        scalar_mirror["tm"] = tm
        scalar_mirror["tlm"] = tlm
        scalar_mirror["in_bt"] = in_bt
        scalar_mirror["mc_depth"] = mc_depth
        scalar_mirror["advance_pending"] = advance_pending
        scalar_mirror["show_count"] = len(shows)

    def _numbers(operands: list[_Operand], count: int) -> list[float] | None:
        if len(operands) < count:
            return None
        tail = operands[-count:]
        if any(op.kind != "number" for op in tail):
            return None
        return [float(op.value) for op in tail]  # type: ignore[arg-type]

    def _line_advance() -> None:
        nonlocal tm, tlm, advance_pending
        tlm = _mat_mul(_translate(0.0, -state.leading), tlm)
        tm = tlm
        advance_pending = False

    def _record_show(
        operator: str,
        stream_index: int,
        stream_xref: int,
        string_op: _Operand,
        decoded: bytes,
        string_kind: str,
        item_count: int,
        op_start: int,
        op_end: int,
    ) -> None:
        nonlocal advance_pending, next_seq
        trm = _mat_mul(tm, state.ctm)
        shows.append(
            ShowOp(
                seq=next_seq,
                operator=operator,
                stream_xref=stream_xref,
                op_start=op_start,
                op_end=op_end,
                string_start=string_op.start,
                string_end=string_op.end,
                string_kind=string_kind,
                array_item_count=item_count,
                decoded_bytes=decoded,
                font_resource=state.font_resource,
                font_size=state.font_size,
                tm=tm,
                ctm=state.ctm,
                trm_uniform_scale=_uniform_scale(trm),
                origin_user=_mat_apply(trm, 0.0, state.rise),
                origin_reliable=not advance_pending,
                char_spacing=state.char_spacing,
                word_spacing=state.word_spacing,
                hscale=state.hscale,
                leading=state.leading,
                rise=state.rise,
                render_mode=state.render_mode,
                in_bt=in_bt,
                gs_depth=len(gs_stack),
                mc_depth=mc_depth,
                mc_stack=tuple(mc_open),
            )
        )
        show_stream_indices.append(stream_index)
        next_seq += 1
        advance_pending = True

    for stream_index in range(start_stream, len(streams)):
        stream_xref, data = streams[stream_index]
        base = start_offset if stream_index == start_stream else 0
        if on_site is not None:
            _mirror_scalars()
            on_site(stream_index, base, dispatched)
        tokens = lex_content_stream(data[base:] if base else data)
        operands: list[_Operand] = []

        for token in tokens:
            t_start = token.start + base
            t_end = token.end + base
            if token.kind in _TRIVIA:
                continue
            if token.kind == TokenKind.MALFORMED:
                malformed = True
                continue
            if token.kind == TokenKind.INLINE_IMAGE_DATA:
                operands.clear()
                continue
            raw = data[t_start:t_end]

            if token.kind == TokenKind.NUMBER:
                operands.append(_Operand("number", float(raw), t_start, t_end))
                continue
            if token.kind == TokenKind.NAME:
                operands.append(
                    _Operand("name", raw[1:].decode("latin-1"), t_start, t_end)
                )
                continue
            if token.kind in _STRING_KINDS:
                kind = "string" if token.kind == TokenKind.STRING else "hex"
                operands.append(_Operand(kind, raw, t_start, t_end))
                continue
            if token.kind == TokenKind.ARRAY_OPEN:
                operands.append(_Operand("array_open", None, t_start, t_end))
                continue
            if token.kind == TokenKind.ARRAY_CLOSE:
                items: list[_Operand] = []
                while operands and operands[-1].kind != "array_open":
                    items.append(operands.pop())
                if not operands:
                    malformed = True
                    continue
                marker = operands.pop()
                items.reverse()
                operands.append(_Operand("array", items, marker.start, t_end))
                continue
            if token.kind in (
                TokenKind.DICT_OPEN,
                TokenKind.DICT_CLOSE,
                TokenKind.BRACE_OPEN,
                TokenKind.BRACE_CLOSE,
            ):
                operands.append(_Operand("other", None, t_start, t_end))
                continue

            # OPERATOR
            op = raw
            if op in (b"true", b"false", b"null"):
                operands.append(_Operand("keyword", None, t_start, t_end))
                continue
            try:
                if op == b"q":
                    gs_stack.append(state.snapshot())
                elif op == b"Q":
                    if gs_stack:
                        state.restore(gs_stack.pop())
                        for wrapper_id in mc_open:
                            wrapper = mc_records[wrapper_id]
                            if wrapper.open_gs_depth > len(gs_stack):
                                wrapper.crossed_q = True
                elif op == b"cm":
                    nums = _numbers(operands, 6)
                    if nums is None:
                        malformed = True
                    else:
                        state.ctm = _mat_mul(tuple(nums), state.ctm)  # type: ignore[arg-type]
                elif op == b"BT":
                    in_bt = True
                    tm = tlm = _IDENTITY
                    advance_pending = False
                elif op == b"ET":
                    in_bt = False
                elif op == b"Tf":
                    nums = _numbers(operands, 1)
                    name_op = operands[-2] if len(operands) >= 2 else None
                    if nums is None or name_op is None or name_op.kind != "name":
                        malformed = True
                    else:
                        state.font_resource = str(name_op.value)
                        state.font_size = nums[0]
                elif op == b"Tm":
                    nums = _numbers(operands, 6)
                    if nums is None:
                        malformed = True
                    else:
                        tm = tlm = tuple(nums)  # type: ignore[assignment]
                        advance_pending = False
                elif op == b"Td":
                    nums = _numbers(operands, 2)
                    if nums is None:
                        malformed = True
                    else:
                        tlm = _mat_mul(_translate(nums[0], nums[1]), tlm)
                        tm = tlm
                        advance_pending = False
                elif op == b"TD":
                    nums = _numbers(operands, 2)
                    if nums is None:
                        malformed = True
                    else:
                        state.leading = -nums[1]
                        tlm = _mat_mul(_translate(nums[0], nums[1]), tlm)
                        tm = tlm
                        advance_pending = False
                elif op == b"T*":
                    _line_advance()
                elif op == b"TL":
                    nums = _numbers(operands, 1)
                    if nums is None:
                        malformed = True
                    else:
                        state.leading = nums[0]
                elif op == b"Tc":
                    nums = _numbers(operands, 1)
                    if nums is None:
                        malformed = True
                    else:
                        state.char_spacing = nums[0]
                elif op == b"Tw":
                    nums = _numbers(operands, 1)
                    if nums is None:
                        malformed = True
                    else:
                        state.word_spacing = nums[0]
                elif op == b"Tz":
                    nums = _numbers(operands, 1)
                    if nums is None:
                        malformed = True
                    else:
                        state.hscale = nums[0]
                elif op == b"Ts":
                    nums = _numbers(operands, 1)
                    if nums is None:
                        malformed = True
                    else:
                        state.rise = nums[0]
                elif op == b"Tr":
                    nums = _numbers(operands, 1)
                    if nums is None:
                        malformed = True
                    else:
                        state.render_mode = int(nums[0])
                elif op == b"Tj":
                    if operands and operands[-1].kind in ("string", "hex"):
                        string_op = operands[-1]
                        decoded = _decode_operand_string(string_op)
                        _record_show(
                            "Tj",
                            stream_index,
                            stream_xref,
                            string_op,
                            decoded,
                            "literal" if string_op.kind == "string" else "hex",
                            1,
                            string_op.start,
                            t_end,
                        )
                    else:
                        malformed = True
                elif op == b"'":
                    if operands and operands[-1].kind in ("string", "hex"):
                        string_op = operands[-1]
                        _line_advance()
                        decoded = _decode_operand_string(string_op)
                        _record_show(
                            "'",
                            stream_index,
                            stream_xref,
                            string_op,
                            decoded,
                            "literal" if string_op.kind == "string" else "hex",
                            1,
                            string_op.start,
                            t_end,
                        )
                    else:
                        malformed = True
                elif op == b'"':
                    nums = (
                        _numbers(operands[:-1], 2)
                        if operands and operands[-1].kind in ("string", "hex")
                        else None
                    )
                    if nums is None:
                        malformed = True
                    else:
                        string_op = operands[-1]
                        state.word_spacing = nums[0]
                        state.char_spacing = nums[1]
                        _line_advance()
                        decoded = _decode_operand_string(string_op)
                        _record_show(
                            '"',
                            stream_index,
                            stream_xref,
                            string_op,
                            decoded,
                            "literal" if string_op.kind == "string" else "hex",
                            1,
                            operands[-3].start,
                            t_end,
                        )
                elif op == b"TJ":
                    if operands and operands[-1].kind == "array":
                        array_op = operands[-1]
                        array_items = array_op.value
                        parts: list[bytes] = []
                        item_count = 0
                        bad = False
                        for item in array_items:  # type: ignore[union-attr]
                            if item.kind in ("string", "hex"):
                                parts.append(_decode_operand_string(item))
                                item_count += 1
                            elif item.kind != "number":
                                bad = True
                        if bad:
                            malformed = True
                        else:
                            _record_show(
                                "TJ",
                                stream_index,
                                stream_xref,
                                array_op,
                                b"".join(parts),
                                "array",
                                item_count,
                                array_op.start,
                                t_end,
                            )
                    else:
                        malformed = True
                elif op == b"Do":
                    has_xobject = True
                elif op in (b"BDC", b"BMC"):
                    mc_depth += 1
                    record = _McRecord(
                        wrapper_id=next_wrapper_id,
                        stream_xref=stream_xref,
                        operator="BDC" if op == b"BDC" else "BMC",
                        open_gs_depth=len(gs_stack),
                        open_op_end=t_end,
                    )
                    _production_parse_mc_operands(op, operands, data, record)
                    mc_records[next_wrapper_id] = record
                    mc_open.append(next_wrapper_id)
                    next_wrapper_id += 1
                elif op == b"EMC":
                    mc_depth = max(0, mc_depth - 1)
                    if mc_open:
                        wrapper = mc_records[mc_open.pop()]
                        wrapper.closed = True
                        wrapper.close_stream_xref = stream_xref
                        wrapper.close_op_start = t_start
                        if len(gs_stack) != wrapper.open_gs_depth:
                            wrapper.crossed_q = True
                    else:
                        mc_emc_underflows += 1
                elif op in (b"BI", b"ID", b"EI"):
                    pass  # inline image structure; payload token already skipped
                # every other operator: no tracked state effect
            except ValueError:
                logger.debug("spike replay: undecodable operand for %r", op)
                malformed = True
            operands.clear()
            dispatched += 1
            if stop_after_seq is not None and shows and shows[-1].seq == stop_after_seq:
                return _CoreResult(
                    shows=shows,
                    show_stream_indices=show_stream_indices,
                    malformed=malformed,
                    has_xobject=has_xobject,
                    mc_emc_underflows=mc_emc_underflows,
                    mc_records=mc_records,
                    next_wrapper_id=next_wrapper_id,
                )
            if on_site is not None and op not in _NO_CHECKPOINT_AFTER:
                _mirror_scalars()
                on_site(stream_index, t_end, dispatched)

    return _CoreResult(
        shows=shows,
        show_stream_indices=show_stream_indices,
        malformed=malformed,
        has_xobject=has_xobject,
        mc_emc_underflows=mc_emc_underflows,
        mc_records=mc_records,
        next_wrapper_id=next_wrapper_id,
    )


# ------------------------------------------------------------ deep sizing


def _deep_size(obj: object, seen: set[int] | None = None) -> int:
    """Approximate retained bytes: sys.getsizeof, shared objects once."""
    seen = seen if seen is not None else set()
    if id(obj) in seen:
        return 0
    seen.add(id(obj))
    size = sys.getsizeof(obj)
    if isinstance(obj, dict):
        for key, value in obj.items():
            size += _deep_size(key, seen) + _deep_size(value, seen)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for item in obj:
            size += _deep_size(item, seen)
    elif is_dataclass(obj) and not isinstance(obj, type):
        # A slotless dataclass instance (ShowOp, McWrapper, …) keeps its
        # fields in a per-instance __dict__ whose container cost DOMINATES
        # bytes/ShowOp (analysis-round memory driver #1) — size the dict
        # itself, not just the field values.
        instance_dict = getattr(obj, "__dict__", None)
        if instance_dict is not None:
            size += _deep_size(instance_dict, seen)
        else:  # __slots__ dataclass: field values only
            for field in fields(obj):
                size += _deep_size(getattr(obj, field.name), seen)
    return size


# ---------------------------------------------------------------- Shape A


class MaterializedShowTable:
    """Shape A: retain the full production PageReplay; lookups scan it."""

    def __init__(self, key: IndexKey, replay: PageReplay) -> None:
        self.key = key
        self.replay = replay

    @classmethod
    def build(
        cls,
        page_xref: int,
        streams: list[tuple[int, bytes]],
        *,
        max_decoded_bytes: int | None = DEFAULT_MAX_REPLAY_BYTES,
    ) -> MaterializedShowTable:
        key = index_key_for_streams(page_xref, streams)
        replay = replay_page_streams(streams, max_decoded_bytes=max_decoded_bytes)
        return cls(key, replay)

    @property
    def refusal_reason(self) -> str | None:
        return self.replay.refusal_reason

    def lookup(self, target_bytes: bytes) -> tuple[ShowOp, ...]:
        if self.replay.refusal_reason is not None:
            raise ReplayIndexRefusedError(self.replay.refusal_reason)
        return tuple(
            show for show in self.replay.shows if show.decoded_bytes == target_bytes
        )

    def memory_footprint(self) -> dict[str, object]:
        n_shows = len(self.replay.shows)
        total = _deep_size(self.replay)
        return {
            "total_bytes": total,
            "n_shows": n_shows,
            "decoded_bytes_total": sum(
                len(show.decoded_bytes) for show in self.replay.shows
            ),
            "bytes_per_show": (total / n_shows) if n_shows else 0.0,
        }


# ---------------------------------------------------------------- Shape B


class SparseCheckpointIndex:
    """Shape B: sparse rows + checkpoints + retained page-global evidence."""

    def __init__(
        self,
        *,
        key: IndexKey,
        refusal_reason: str | None,
        malformed: bool,
        has_xobject_invocation: bool,
        stream_xrefs: tuple[int, ...],
        mc_wrappers: tuple[McWrapper, ...],
        mc_emc_underflows: int,
        rows: tuple[ShowRow, ...],
        checkpoints: tuple[Checkpoint, ...],
    ) -> None:
        self.key = key
        self.refusal_reason = refusal_reason
        self.malformed = malformed
        self.has_xobject_invocation = has_xobject_invocation
        self.stream_xrefs = stream_xrefs
        self.mc_wrappers = mc_wrappers
        self.mc_emc_underflows = mc_emc_underflows
        self.rows = rows
        self.checkpoints = checkpoints

    @classmethod
    def build(
        cls,
        page_xref: int,
        streams: list[tuple[int, bytes]],
        *,
        checkpoint_interval_ops: int = 64,
        max_decoded_bytes: int | None = DEFAULT_MAX_REPLAY_BYTES,
    ) -> SparseCheckpointIndex:
        key = index_key_for_streams(page_xref, streams)
        if max_decoded_bytes is not None:
            total = sum(len(data) for _, data in streams)
            if total > max_decoded_bytes:
                return cls(
                    key=key,
                    refusal_reason=RejectReason.CONTENT_STREAM_TOO_LARGE,
                    malformed=False,
                    has_xobject_invocation=False,
                    stream_xrefs=tuple(x for x, _ in streams),
                    mc_wrappers=(),
                    mc_emc_underflows=0,
                    rows=(),
                    checkpoints=(),
                )

        checkpoints: list[Checkpoint] = []
        state = _State()
        gs_stack: list[tuple] = []
        mc_open: list[int] = []
        mc_records: dict[int, _McRecord] = {}
        core_box: dict[str, object] = {}
        last_emit_ops = [-checkpoint_interval_ops]

        def _capture(stream_index: int, offset: int, dispatched: int) -> None:
            # Stream starts (offset 0 with no ops yet counted for this
            # position) are always legal; interior sites are rate-limited
            # by the interval.
            is_stream_start = offset == 0
            due = dispatched - last_emit_ops[0] >= checkpoint_interval_ops
            if not (is_stream_start or due):
                return
            last_emit_ops[0] = dispatched
            checkpoints.append(
                Checkpoint(
                    stream_index=stream_index,
                    offset=offset,
                    state=state.snapshot(),
                    gs_stack=tuple(gs_stack),
                    tm=core_box.get("tm", _IDENTITY),  # type: ignore[arg-type]
                    tlm=core_box.get("tlm", _IDENTITY),  # type: ignore[arg-type]
                    in_bt=bool(core_box.get("in_bt", False)),
                    mc_depth=int(core_box.get("mc_depth", 0)),
                    mc_open=tuple(mc_open),
                    open_wrapper_gs_depths=tuple(
                        mc_records[i].open_gs_depth for i in mc_open
                    ),
                    wrapper_seed=len(mc_records),
                    show_seed=int(core_box.get("show_count", 0)),
                    advance_pending=bool(core_box.get("advance_pending", False)),
                )
            )

        result = _run_instrumented_build(
            streams,
            state=state,
            gs_stack=gs_stack,
            mc_open=mc_open,
            mc_records=mc_records,
            core_box=core_box,
            capture=_capture,
        )

        rows = tuple(
            ShowRow(
                seq=show.seq,
                stream_index=stream_index,
                operator=show.operator,
                string_kind=show.string_kind,
                op_start=show.op_start,
                op_end=show.op_end,
                string_start=show.string_start,
                string_end=show.string_end,
                array_item_count=show.array_item_count,
                decoded_len=len(show.decoded_bytes),
            )
            for show, stream_index in zip(result.shows, result.show_stream_indices)
        )
        wrappers = tuple(
            result.mc_records[i].freeze() for i in sorted(result.mc_records)
        )
        return cls(
            key=key,
            refusal_reason=None,
            malformed=result.malformed,
            has_xobject_invocation=result.has_xobject,
            stream_xrefs=tuple(x for x, _ in streams),
            mc_wrappers=wrappers,
            mc_emc_underflows=result.mc_emc_underflows,
            rows=rows,
            checkpoints=tuple(checkpoints),
        )

    # ------------------------------------------------------- warm lookups

    def _refuse_if_needed(self) -> None:
        if self.refusal_reason is not None:
            raise ReplayIndexRefusedError(self.refusal_reason)

    def candidate_seqs(
        self, streams: list[tuple[int, bytes]], target_bytes: bytes
    ) -> tuple[int, ...]:
        """Rows whose lazily-decoded string operand equals ``target_bytes``.

        Decoding is offset-local: literal/hex slices decode directly; a TJ
        array re-lexes only its own ``[ ... ]`` span.
        """
        self._refuse_if_needed()
        hits: list[int] = []
        for row in self.rows:
            if row.decoded_len != len(target_bytes):
                continue
            if self._decode_row(streams, row) == target_bytes:
                hits.append(row.seq)
        return tuple(hits)

    def _decode_row(self, streams: list[tuple[int, bytes]], row: ShowRow) -> bytes:
        _, data = streams[row.stream_index]
        raw = data[row.string_start : row.string_end]
        if row.string_kind == "literal":
            return _decode_operand_string(
                _Operand("string", raw, row.string_start, row.string_end)
            )
        if row.string_kind == "hex":
            return _decode_operand_string(
                _Operand("hex", raw, row.string_start, row.string_end)
            )
        # TJ array: local lex of the bracketed span only.
        parts: list[bytes] = []
        for token in lex_content_stream(raw):
            if token.kind in _STRING_KINDS:
                kind = "string" if token.kind == TokenKind.STRING else "hex"
                parts.append(
                    _decode_operand_string(
                        _Operand(kind, raw[token.start : token.end], 0, 0)
                    )
                )
        return b"".join(parts)

    def restore_show(
        self,
        streams: list[tuple[int, bytes]],
        seq: int,
        *,
        from_checkpoint: Checkpoint | None = None,
    ) -> ShowOp:
        """Checkpoint restore + local replay to the target show.

        The returned ShowOp is interpreter output only; wrapper evidence
        and page verdicts must be read from the retained attributes
        (``mc_wrappers``, ``malformed``, …), never recomputed locally.
        """
        self._refuse_if_needed()
        row = self.rows[seq]
        assert row.seq == seq
        checkpoint = (
            from_checkpoint
            if from_checkpoint is not None
            else self._nearest_checkpoint(row)
        )
        state = _State()
        state.restore(checkpoint.state)
        scratch_records = {
            wrapper_id: _McRecord(
                wrapper_id=wrapper_id,
                stream_xref=-1,  # scratch stand-in; never served as evidence
                operator="BDC",
                open_gs_depth=open_depth,
            )
            for wrapper_id, open_depth in zip(
                checkpoint.mc_open, checkpoint.open_wrapper_gs_depths
            )
        }
        result = _replay_core(
            streams,
            start_stream=checkpoint.stream_index,
            start_offset=checkpoint.offset,
            state=state,
            gs_stack=list(checkpoint.gs_stack),
            tm=checkpoint.tm,
            tlm=checkpoint.tlm,
            in_bt=checkpoint.in_bt,
            mc_depth=checkpoint.mc_depth,
            mc_open=list(checkpoint.mc_open),
            mc_records=scratch_records,
            next_wrapper_id=checkpoint.wrapper_seed,
            next_seq=checkpoint.show_seed,
            advance_pending=checkpoint.advance_pending,
            stop_after_seq=seq,
        )
        if not result.shows or result.shows[-1].seq != seq:
            raise LookupError(f"restore did not reach show seq {seq}")
        return result.shows[-1]

    def _nearest_checkpoint(self, row: ShowRow) -> Checkpoint:
        eligible = [
            c
            for c in self.checkpoints
            if (c.stream_index, c.offset) <= (row.stream_index, row.op_start)
        ]
        if not eligible:  # stream-start checkpoints make this unreachable
            raise LookupError("no checkpoint at or before the target row")
        return max(eligible, key=lambda c: (c.stream_index, c.offset))

    def memory_footprint(self) -> dict[str, object]:
        rows_bytes = _deep_size(self.rows)
        checkpoints_bytes = _deep_size(self.checkpoints)
        total = (
            rows_bytes
            + checkpoints_bytes
            + _deep_size(self.mc_wrappers)
            + _deep_size(self.key)
        )
        return {
            "total_bytes": total,
            "n_rows": len(self.rows),
            "n_checkpoints": len(self.checkpoints),
            "rows_bytes": rows_bytes,
            "checkpoints_bytes": checkpoints_bytes,
        }


def _run_instrumented_build(
    streams: list[tuple[int, bytes]],
    *,
    state: _State,
    gs_stack: list[tuple],
    mc_open: list[int],
    mc_records: dict[int, _McRecord],
    core_box: dict[str, object],
    capture: Callable[[int, int, int], None],
) -> _CoreResult:
    """Run ``_replay_core`` sharing mutable state with the capture closure.

    The capture closure reads the shared mutable containers (``state``,
    ``gs_stack``, ``mc_open``, ``mc_records``) directly; the loop's
    scalar locals (tm/tlm/in_bt/mc_depth/advance_pending/show count) are
    mirrored into ``core_box`` by ``_replay_core`` immediately before
    each ``on_site`` call.
    """
    return _replay_core(
        streams,
        state=state,
        gs_stack=gs_stack,
        mc_open=mc_open,
        mc_records=mc_records,
        on_site=capture,
        scalar_mirror=core_box,
    )

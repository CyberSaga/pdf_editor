"""PDF graphics/text-state replay over a page's ordered content streams.

Interprets exactly the operators the V2 engine supports (q/Q, cm, BT/ET,
Tf, Tm, Td, TD, T*, TL, Tc, Tw, Tz, Ts, Tr, Tj, TJ, ', ") and records each
text-show operation with its resolved state and exact per-stream byte
ranges.  Anything the interpreter cannot account for is *flagged* — shows
carry ``origin_reliable``/``in_bt``/``trm_uniform_scale`` and the replay
carries ``malformed`` — so downstream binding/planning can refuse instead
of guessing (plan Task 3).

State carries across the page's stream sequence (the spec allows tokens to
be split only *between* streams); per PDF spec, q/Q save and restore the
text-state parameters (Tc, Tw, Tz, TL, Tf, Tr, Ts) along with the CTM.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from model.text_commit.dto import RejectReason
from model.text_commit.pdf_lexer import (
    TokenKind,
    decode_hex_string,
    decode_literal_string,
    lex_content_stream,
)

logger = logging.getLogger(__name__)

# Task 12 P0-A: replay is the ONLY production path into lex_content_stream,
# which materializes ~0.77 tokens/byte at ~133x RSS amplification (a measured
# 72 MB decoded page peaked near 10 GB).  4 MiB caps the transient at roughly
# half a GB and the lex walk at a few seconds; an over-budget page refuses
# here and falls to the legacy engine, which never lexes.  Revisit as a
# latency budget once the streaming lexer (P0-B) lands.
DEFAULT_MAX_REPLAY_BYTES = 4 * 1024 * 1024

Matrix = tuple[float, float, float, float, float, float]

_IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
_EPS = 1e-6

_TRIVIA = (TokenKind.WHITESPACE, TokenKind.COMMENT)
_STRING_KINDS = (TokenKind.STRING, TokenKind.HEXSTRING)


def _mat_mul(first: Matrix, second: Matrix) -> Matrix:
    """Row-vector convention: applying the result == first, then second."""
    a1, b1, c1, d1, e1, f1 = first
    a2, b2, c2, d2, e2, f2 = second
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def _mat_apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def _translate(tx: float, ty: float) -> Matrix:
    return (1.0, 0.0, 0.0, 1.0, tx, ty)


def _uniform_scale(m: Matrix) -> float | None:
    """``m``'s uniform positive scale factor, or ``None`` when it has none.

    Accepts translation (factor 1.0) and the axis-aligned uniform positive
    scale the TeX/dvips idiom produces (``/F1 1 Tf`` with ``10 0 0 10 … Tm``):
    both preserve the ratio between any two advances, so the equal-advance
    proof carries over unchanged and only page-space *geometry* has to be
    multiplied by the factor.  Rotation and shear (``b``/``c`` set) and
    reflection or a degenerate scale (``a <= 0``, or ``a != d`` as in a
    mirror) all return ``None``: each needs layout work Tier 0 does not do.
    """
    a, b, c, d, _, _ = m
    if abs(b) > _EPS or abs(c) > _EPS:
        return None  # rotated or sheared
    if a <= _EPS or abs(a - d) > _EPS:
        return None  # reflected, mirrored, or degenerate
    return a


@dataclass(frozen=True)
class ShowOp:
    """One text-showing operator with its resolved state at execution."""

    seq: int
    operator: str  # "Tj" | "TJ" | "'" | '"'
    stream_xref: int
    op_start: int  # byte offset of the first operand token (in its stream)
    op_end: int  # byte offset just past the operator keyword
    string_start: int  # byte range of the string/array operand
    string_end: int
    string_kind: str  # "literal" | "hex" | "array"
    array_item_count: int  # string items in a TJ array; 1 otherwise
    decoded_bytes: bytes  # encoding-level string bytes (kern numbers dropped)
    font_resource: str | None
    font_size: float
    tm: Matrix
    ctm: Matrix
    trm_uniform_scale: float | None  # None: rotated, sheared, or reflected
    origin_user: tuple[float, float]  # PDF user space, rise applied
    origin_reliable: bool  # False if a prior show's advance was not tracked
    char_spacing: float
    word_spacing: float
    hscale: float
    leading: float
    rise: float
    render_mode: int
    in_bt: bool
    gs_depth: int
    mc_depth: int
    # ids into PageReplay.mc_wrappers for every wrapper open at this show,
    # outermost-first; () outside any wrapper
    mc_stack: tuple[int, ...] = ()

    @property
    def trm_uniform_scaled(self) -> bool:
        """The TRM is a translation plus a uniform positive scale."""
        return self.trm_uniform_scale is not None


@dataclass(frozen=True)
class McWrapper:
    """Evidence for one BDC/BMC..EMC marked-content wrapper.

    Pure capture for the Task 13 census and the future admission
    fingerprint: no admission logic lives here, and ``mc_depth``'s
    existing clamp semantics are untouched.  ``props_dict_keys`` holds
    top-level inline-dict KEYS only — property values (e.g. an
    ``/ActualText`` string) are never retained.
    """

    wrapper_id: int
    stream_xref: int
    operator: str  # "BDC" | "BMC"
    tag: str | None  # None when the operand shape is unparseable
    props_kind: str  # "none" | "name" | "dict" | "unparsed"
    props_name: str | None  # named /Properties resource, for BDC /Tag /Name
    props_dict_keys: tuple[str, ...]
    open_gs_depth: int
    closed: bool
    crossed_q: bool
    # Byte spans for the splice boundary guard (Task 13 P1 obligation 4):
    # end of the opening BDC/BMC operator token, and the stream/offset of
    # the EMC that closed this wrapper (None while unclosed).
    open_op_end: int = 0
    close_stream_xref: int | None = None
    close_op_start: int | None = None


@dataclass
class _McRecord:
    """Mutable in-flight form of :class:`McWrapper`."""

    wrapper_id: int
    stream_xref: int
    operator: str
    open_gs_depth: int
    tag: str | None = None
    props_kind: str = "unparsed"
    props_name: str | None = None
    props_dict_keys: tuple[str, ...] = ()
    closed: bool = False
    crossed_q: bool = False
    open_op_end: int = 0
    close_stream_xref: int | None = None
    close_op_start: int | None = None

    def freeze(self) -> McWrapper:
        return McWrapper(
            wrapper_id=self.wrapper_id,
            stream_xref=self.stream_xref,
            operator=self.operator,
            tag=self.tag,
            props_kind=self.props_kind,
            props_name=self.props_name,
            props_dict_keys=self.props_dict_keys,
            open_gs_depth=self.open_gs_depth,
            closed=self.closed,
            crossed_q=self.crossed_q,
            open_op_end=self.open_op_end,
            close_stream_xref=self.close_stream_xref,
            close_op_start=self.close_op_start,
        )


@dataclass(frozen=True)
class PageReplay:
    shows: tuple[ShowOp, ...]
    malformed: bool
    has_xobject_invocation: bool
    stream_xrefs: tuple[int, ...]
    # Set when replay refused to run at all (resource guard) -- a distinct
    # channel from ``malformed`` on purpose: callers must surface it
    # verbatim, never collapse it into MALFORMED_STREAM/NO_MATCH.
    refusal_reason: str | None = None
    mc_wrappers: tuple[McWrapper, ...] = ()
    mc_emc_underflows: int = 0
    # The decoded-byte budget this replay actually ran under (P3-B
    # review F3): ``None`` marks the diagnostic-unbounded path, which
    # ``evidence.ReplayEvidence`` refuses to retain -- an unbounded
    # replay of an over-budget page has no ``refusal_reason``, and
    # without this attestation it would be indistinguishable from a
    # legitimately admitted one.
    # ``compare=False``: the attestation is provenance metadata, not
    # replay semantics -- two replays of the same bytes are equal
    # regardless of which admitted budget ran them.
    max_decoded_bytes: int | None = field(
        default=DEFAULT_MAX_REPLAY_BYTES, compare=False
    )


@dataclass
class _Operand:
    kind: str  # "number" | "name" | "string" | "hex" | "array" | "array_open" | "keyword" | "other"
    value: object
    start: int
    end: int


@dataclass
class _State:
    ctm: Matrix = _IDENTITY
    char_spacing: float = 0.0
    word_spacing: float = 0.0
    hscale: float = 100.0
    leading: float = 0.0
    font_resource: str | None = None
    font_size: float = 0.0
    render_mode: int = 0
    rise: float = 0.0

    def snapshot(self) -> tuple:
        return (
            self.ctm,
            self.char_spacing,
            self.word_spacing,
            self.hscale,
            self.leading,
            self.font_resource,
            self.font_size,
            self.render_mode,
            self.rise,
        )

    def restore(self, snap: tuple) -> None:
        (
            self.ctm,
            self.char_spacing,
            self.word_spacing,
            self.hscale,
            self.leading,
            self.font_resource,
            self.font_size,
            self.render_mode,
            self.rise,
        ) = snap


def _inline_dict_keys(
    items: list[_Operand], data: bytes
) -> tuple[str, ...] | None:
    """Top-level keys of a flat-lexed inline dict body, or None when the
    shape is not a well-formed key/value alternation.  Nested dicts and
    arrays are skipped as single values; their contents are never read."""
    keys: list[str] = []
    depth = 1
    expecting_key = True
    for item in items:
        if item.kind == "other":
            raw = data[item.start : item.end]
            if raw == b"<<":
                if depth == 1 and expecting_key:
                    return None
                depth += 1
                continue
            if raw == b">>":
                depth -= 1
                if depth < 1:
                    return None
                if depth == 1:
                    expecting_key = True
                continue
            return None  # brace tokens etc.
        if depth > 1:
            continue
        if expecting_key:
            if item.kind != "name":
                return None
            keys.append(str(item.value))
            expecting_key = False
        else:
            expecting_key = True
    if not expecting_key:
        return None  # dangling key with no value
    return tuple(keys)


def _parse_mc_operands(
    op: bytes, operands: list[_Operand], data: bytes, record: _McRecord
) -> None:
    """Fill ``record`` from a BMC/BDC operand list.  Never raises and never
    marks the stream malformed: BDC/BMC have always been state-only for
    replay, so operand oddities stay evidence (``props_kind="unparsed"``).

    Fail-closed shape check (Codex review): the operand list must be
    EXACTLY ``/Tag`` (BMC), ``/Tag /Name`` or ``/Tag <<...>>`` (BDC) — a
    valid-looking tail preceded by garbage must not classify, or junk like
    ``42 /OC /P0 BDC`` would masquerade as a provable layer wrapper."""
    if op == b"BMC":
        if len(operands) == 1 and operands[0].kind == "name":
            record.tag = str(operands[0].value)
            record.props_kind = "none"
        return
    if (
        len(operands) == 2
        and operands[0].kind == "name"
        and operands[1].kind == "name"
    ):
        record.tag = str(operands[0].value)
        record.props_kind = "name"
        record.props_name = str(operands[1].value)
        return
    if (
        len(operands) >= 3
        and operands[0].kind == "name"
        and operands[1].kind == "other"
        and data[operands[1].start : operands[1].end] == b"<<"
        and operands[-1].kind == "other"
        and data[operands[-1].start : operands[-1].end] == b">>"
    ):
        depth = 0
        open_index = None
        for index in range(len(operands) - 1, 0, -1):
            item = operands[index]
            if item.kind != "other":
                continue
            raw = data[item.start : item.end]
            if raw == b">>":
                depth += 1
            elif raw == b"<<":
                depth -= 1
                if depth == 0:
                    open_index = index
                    break
        if open_index != 1:
            return  # the dict does not span the whole properties operand
        keys = _inline_dict_keys(operands[2:-1], data)
        if keys is None:
            return
        record.tag = str(operands[0].value)
        record.props_kind = "dict"
        record.props_dict_keys = keys


def _decode_operand_string(op: _Operand) -> bytes:
    raw = op.value
    if not isinstance(raw, bytes):
        raise ValueError("string operand carries no raw bytes")
    if op.kind == "string":
        return decode_literal_string(raw)
    return decode_hex_string(raw)


def replay_page_streams(
    streams: list[tuple[int, bytes]],
    *,
    max_decoded_bytes: int | None = DEFAULT_MAX_REPLAY_BYTES,
) -> PageReplay:
    """Replay ``[(stream_xref, decoded_bytes), ...]`` in order.

    ``max_decoded_bytes`` bounds the SUM of the decoded stream sizes (state
    carries across the page's stream sequence, so the lexer walks all of
    them).  Over budget, the replay refuses before any tokenization and
    returns a ``PageReplay`` whose ``refusal_reason`` is
    ``RejectReason.CONTENT_STREAM_TOO_LARGE``.  ``None`` disables the guard
    (diagnostic use only).  ``read_page_streams`` and the commit verifier
    stay deliberately unguarded: verification must still hash oversized
    streams, or a perf limit becomes a correctness failure.
    """
    if max_decoded_bytes is not None:
        total = sum(len(data) for _, data in streams)
        if total > max_decoded_bytes:
            logger.info(
                "replay refused: %d decoded bytes over the %d-byte budget",
                total,
                max_decoded_bytes,
            )
            return PageReplay(
                shows=(),
                malformed=False,
                has_xobject_invocation=False,
                stream_xrefs=tuple(x for x, _ in streams),
                refusal_reason=RejectReason.CONTENT_STREAM_TOO_LARGE,
                max_decoded_bytes=max_decoded_bytes,
            )

    shows: list[ShowOp] = []
    malformed = False
    has_xobject = False

    state = _State()
    gs_stack: list[tuple] = []
    tm: Matrix = _IDENTITY
    tlm: Matrix = _IDENTITY
    in_bt = False
    mc_depth = 0
    mc_records: list[_McRecord] = []  # every wrapper ever opened, by id
    mc_open: list[int] = []  # ids of wrappers currently open, outermost-first
    mc_emc_underflows = 0
    advance_pending = False  # a show ran since the last repositioning op

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
        stream_xref: int,
        string_op: _Operand,
        decoded: bytes,
        string_kind: str,
        item_count: int,
        op_start: int,
        op_end: int,
    ) -> None:
        nonlocal advance_pending
        trm = _mat_mul(tm, state.ctm)
        shows.append(
            ShowOp(
                seq=len(shows),
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
        advance_pending = True

    for stream_xref, data in streams:
        tokens = lex_content_stream(data)
        operands: list[_Operand] = []

        for token in tokens:
            if token.kind in _TRIVIA:
                continue
            if token.kind == TokenKind.MALFORMED:
                malformed = True
                continue
            if token.kind == TokenKind.INLINE_IMAGE_DATA:
                operands.clear()
                continue
            raw = data[token.start : token.end]

            if token.kind == TokenKind.NUMBER:
                operands.append(_Operand("number", float(raw), token.start, token.end))
                continue
            if token.kind == TokenKind.NAME:
                operands.append(
                    _Operand(
                        "name", raw[1:].decode("latin-1"), token.start, token.end
                    )
                )
                continue
            if token.kind in _STRING_KINDS:
                kind = "string" if token.kind == TokenKind.STRING else "hex"
                operands.append(_Operand(kind, raw, token.start, token.end))
                continue
            if token.kind == TokenKind.ARRAY_OPEN:
                operands.append(_Operand("array_open", None, token.start, token.end))
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
                operands.append(
                    _Operand("array", items, marker.start, token.end)
                )
                continue
            if token.kind in (
                TokenKind.DICT_OPEN,
                TokenKind.DICT_CLOSE,
                TokenKind.BRACE_OPEN,
                TokenKind.BRACE_CLOSE,
            ):
                operands.append(_Operand("other", None, token.start, token.end))
                continue

            # OPERATOR
            op = raw
            if op in (b"true", b"false", b"null"):
                # bare object keywords are inline-dict VALUES (e.g.
                # ``<</ActualText null>>``), never graphics operators —
                # retain them as operands instead of clearing the list
                operands.append(
                    _Operand("keyword", None, token.start, token.end)
                )
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
                            stream_xref,
                            string_op,
                            decoded,
                            "literal" if string_op.kind == "string" else "hex",
                            1,
                            string_op.start,
                            token.end,
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
                            stream_xref,
                            string_op,
                            decoded,
                            "literal" if string_op.kind == "string" else "hex",
                            1,
                            string_op.start,
                            token.end,
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
                            stream_xref,
                            string_op,
                            decoded,
                            "literal" if string_op.kind == "string" else "hex",
                            1,
                            operands[-3].start,
                            token.end,
                        )
                elif op == b"TJ":
                    if operands and operands[-1].kind == "array":
                        array_op = operands[-1]
                        items = array_op.value  # type: ignore[assignment]
                        parts: list[bytes] = []
                        item_count = 0
                        bad = False
                        for item in items:  # type: ignore[union-attr]
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
                                stream_xref,
                                array_op,
                                b"".join(parts),
                                "array",
                                item_count,
                                array_op.start,
                                token.end,
                            )
                    else:
                        malformed = True
                elif op == b"Do":
                    has_xobject = True
                elif op in (b"BDC", b"BMC"):
                    mc_depth += 1
                    record = _McRecord(
                        wrapper_id=len(mc_records),
                        stream_xref=stream_xref,
                        operator="BDC" if op == b"BDC" else "BMC",
                        open_gs_depth=len(gs_stack),
                        open_op_end=token.end,
                    )
                    _parse_mc_operands(op, operands, data, record)
                    mc_records.append(record)
                    mc_open.append(record.wrapper_id)
                elif op == b"EMC":
                    mc_depth = max(0, mc_depth - 1)
                    if mc_open:
                        wrapper = mc_records[mc_open.pop()]
                        wrapper.closed = True
                        wrapper.close_stream_xref = stream_xref
                        wrapper.close_op_start = token.start
                        if len(gs_stack) != wrapper.open_gs_depth:
                            wrapper.crossed_q = True
                    else:
                        mc_emc_underflows += 1
                elif op in (b"BI", b"ID", b"EI"):
                    pass  # inline image structure; payload token already skipped
                # every other operator: no tracked state effect
            except ValueError:
                logger.debug("replay: undecodable operand for %r", op)
                malformed = True
            operands.clear()

    return PageReplay(
        shows=tuple(shows),
        malformed=malformed,
        has_xobject_invocation=has_xobject,
        stream_xrefs=tuple(x for x, _ in streams),
        mc_wrappers=tuple(record.freeze() for record in mc_records),
        mc_emc_underflows=mc_emc_underflows,
        max_decoded_bytes=max_decoded_bytes,
    )

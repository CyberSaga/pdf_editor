"""WS-A red-light tests: preview↔commit candidate identity.

These prove that a commit reuses the *same* verified PreparedEdit that
the preview computed, rather than independently preparing a fresh one.

Fixture: hand-authored single-page PDF with one Helvetica ``(iii) Tj``
as the first show after ``Td``, the same setup the Slice 1 suite uses.

Signal chain under test (production path):
  View→Controller: EditTextRequest(plan_token=<preview token>)
  Controller→Command: EditTextCommand(plan_token=...)
  Command→Model: model.edit_text(..., plan_token=...)
  Model→Engine: _attempt_tiered_commit(..., plan_token=...)

Currently red because:
  1. finalize_text_edit_impl reads the token AFTER clearing the editor
  2. EditTextCommand.execute() does not pass plan_token to model.edit_text()
  3. model.edit_text() has no plan_token parameter
  4. No VerifiedPreparedEdit cache exists
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model.pdf_text_edit as pdf_text_edit_module  # noqa: E402
from model.edit_commands import EditTextResult  # noqa: E402
from model.edit_requests import StyleOverrides  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.pdf_text_edit import _attempt_tiered_commit  # noqa: E402
from model.text_block import EditableSpan  # noqa: E402
from model.text_commit.dto import (  # noqa: E402
    CommitStatus,
    CommitTier,
    RejectReason,
    TextCommitSettings,
)
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.plan import PreparedEdit  # noqa: E402
from model.text_commit.preview import (  # noqa: E402
    PlanPreviewRenderer,
    PlanPreviewRequest,
    open_preview_session,
)

TARGET = "iii"
REPLACEMENT = "iij"  # advance-neutral: same-width glyphs for Tier 0 eligibility


_FONT_OBJECT = (
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
    "/Encoding /WinAnsiEncoding >>"
)


def _stream_doc() -> fitz.Document:
    """One-page doc with a single ``(iii) Tj`` after ``Td``."""
    stream = (
        b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET"
    )
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(font_xref, _FONT_OBJECT)
    doc.xref_set_key(
        page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>"
    )
    return doc


def _first_char_origin(page: fitz.Page, probe: str) -> tuple[float, float]:
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                chars = span["chars"]
                text = "".join(ch["c"] for ch in chars)
                idx = text.find(probe)
                if idx != -1:
                    return tuple(chars[idx]["origin"])
    raise AssertionError(f"{probe!r} not found")


def _target_bbox(page: fitz.Page, probe: str) -> tuple[float, float, float, float]:
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                chars = span["chars"]
                text = "".join(ch["c"] for ch in chars)
                if probe in text:
                    bbox = fitz.Rect()
                    for ch in chars:
                        if ch["c"] in probe:
                            bbox |= fitz.Rect(ch["bbox"])
                    return tuple(bbox)
    raise AssertionError(f"{probe!r} not found")


def _make_resolve_result(page: fitz.Page, probe: str) -> SimpleNamespace:
    """A minimal ``_EditTextResolveResult``-shaped stand-in built from the
    live page's own rawdict span, for driving ``_attempt_tiered_commit``
    directly (mirrors the pattern in test_text_commit_preview_parity.py)."""
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = "".join(ch["c"] for ch in span["chars"])
                if probe in text:
                    editable = EditableSpan(
                        span_id="cached-candidate-target",
                        page_idx=0,
                        block_idx=0,
                        line_idx=0,
                        span_idx=0,
                        bbox=fitz.Rect(span["bbox"]),
                        origin=fitz.Point(*span["origin"]),
                        text=probe,
                        font="Helvetica",
                        size=float(span["size"]),
                        color=(0.0, 0.0, 0.0),
                        dir_vec=(1.0, 0.0),
                        rotation=0,
                    )
                    return SimpleNamespace(
                        overlap_cluster=[editable],
                        target_member_span_ids={editable.span_id},
                    )
    raise AssertionError(f"{probe!r} not found")


class TestPreviewCommitCandidateIdentity:
    """The preview and commit paths must consume the same PreparedEdit."""

    def test_preview_token_threaded_to_model_edit_text(self, tmp_path):
        """model.edit_text(plan_token=...) actually reaches
        ``_attempt_tiered_commit`` with the SAME token the preview produced,
        and the cached candidate is what gets committed.

        This is the real signal chain, not a signature inspection: it opens
        a real ``PDFModel``, runs the preview path to get a token, caches
        the resulting candidate exactly as the controller does, spies on
        the module-level ``_attempt_tiered_commit`` to prove the spy is
        actually invoked with that token, and asserts the edit committed.
        """
        pdf_path = tmp_path / "identity.pdf"
        seed = _stream_doc()
        seed.save(str(pdf_path), garbage=0)
        seed.close()

        model = PDFModel(
            text_commit_settings=TextCommitSettings(
                engine="tiered", preview="plan", max_tier=0
            )
        )
        model.open_pdf(str(pdf_path))
        model.ensure_page_index_built(1)
        try:
            page = model.doc[0]
            origin = _first_char_origin(page, TARGET)
            bbox = _target_bbox(page, TARGET)

            # Preview path: compute the token exactly as the controller does.
            session = open_preview_session(model.doc, 0, "test-session")
            assert session is not None
            renderer = PlanPreviewRenderer(session)
            result = renderer.render(
                PlanPreviewRequest(
                    session_key="test-session",
                    generation=1,
                    target_text=TARGET,
                    replacement_text=REPLACEMENT,
                    expected_origin=origin,
                    target_bbox=bbox,
                    clip_rect=bbox,
                    render_scale=2.0,
                )
            )
            renderer.close()
            preview_token = result.plan_token
            assert preview_token is not None, "preview must produce a Tier 0 token"
            assert isinstance(result.prepared, PreparedEdit)
            model.cache_verified_candidate(preview_token, result.prepared)

            captured_tokens: list[str | None] = []
            original_attempt = pdf_text_edit_module._attempt_tiered_commit

            def _spy_attempt(model_arg, page_arg, page_idx, new_text,
                              resolve_result, style_overrides, new_rect,
                              plan_token=None):
                captured_tokens.append(plan_token)
                return original_attempt(
                    model_arg, page_arg, page_idx, new_text, resolve_result,
                    style_overrides, new_rect, plan_token=plan_token,
                )

            # Poison prepare() on the SAME engine model.edit_text() will use:
            # if the token merely gets threaded down to _attempt_tiered_commit
            # without the cached candidate actually being reused, the commit
            # would fall through to a fresh prepare() and this raises --
            # proving cache-HIT, not just token-threading.
            def _fail_prepare(*_args, **_kwargs):
                raise AssertionError("cached candidate must bypass prepare()")

            engine = model.get_tiered_commit_engine()
            engine.prepare = _fail_prepare  # type: ignore[method-assign]

            with patch.object(
                pdf_text_edit_module, "_attempt_tiered_commit", _spy_attempt
            ):
                block = next(
                    b for b in model.block_manager.get_blocks(0)
                    if TARGET in (b.text or "")
                )
                outcome = model.edit_text(
                    1,
                    fitz.Rect(block.layout_rect),
                    REPLACEMENT,
                    original_text=block.text,
                    plan_token=preview_token,
                )

            assert captured_tokens, "_attempt_tiered_commit must actually fire"
            assert captured_tokens[-1] == preview_token, (
                "the preview token must reach _attempt_tiered_commit"
            )
            assert outcome is EditTextResult.SUCCESS
            assert REPLACEMENT in model.doc[0].get_text()
        finally:
            model.close()

    def test_commit_reuses_cached_verified_candidate(self):
        """When plan_token matches a cached VerifiedPreparedEdit, the engine
        skips prepare() and commits the cached candidate directly.

        Validates the cache_verified_candidate / get_verified_candidate API.
        """
        doc = _stream_doc()
        page = doc[0]
        origin = _first_char_origin(page, TARGET)
        bbox = _target_bbox(page, TARGET)

        engine = TieredCommitEngine(doc, max_tier=0)

        # Step 1: prepare produces a PreparedEdit (also auto-caches)
        prepared = engine.prepare(
            page,
            target_text=TARGET,
            replacement_text=REPLACEMENT,
            expected_origin=origin,
            target_bbox=bbox,
        )
        assert isinstance(prepared, PreparedEdit)
        preview_token = prepared.token

        # Step 2: verify the cache API exists and the candidate was cached
        assert hasattr(engine, "cache_verified_candidate"), (
            "TieredCommitEngine must expose cache_verified_candidate()"
        )
        assert hasattr(engine, "get_verified_candidate"), (
            "TieredCommitEngine must expose get_verified_candidate()"
        )
        cached = engine.get_verified_candidate(preview_token)
        assert cached is prepared, (
            "prepare() must auto-cache verified candidates"
        )

        # Step 3: commit the cached candidate directly
        outcome = engine.commit(prepared)
        assert outcome.status is CommitStatus.COMMITTED
        assert outcome.tier is CommitTier.TIER0_LOSSLESS_STREAM_PATCH

    def test_token_preimage_includes_candidate_semantics(self):
        """The token preimage must include target bbox, advances, font
        identity -- not just page fingerprint and splice bytes.

        Proves that two candidates with identical splice bytes but different
        target bboxes produce different tokens.
        """
        doc = _stream_doc()
        page = doc[0]
        origin = _first_char_origin(page, TARGET)
        bbox = _target_bbox(page, TARGET)

        engine = TieredCommitEngine(doc, max_tier=0)
        prepared = engine.prepare(
            page,
            target_text=TARGET,
            replacement_text=REPLACEMENT,
            expected_origin=origin,
            target_bbox=bbox,
        )
        assert isinstance(prepared, PreparedEdit)

        # Compute a narrow-only token (just fingerprint + splice, no bbox/font)
        import hashlib

        narrow_token = hashlib.sha256(
            "|".join(
                (
                    prepared.page_fingerprint,
                    str(prepared.replacement.stream_xref),
                    str(prepared.replacement.start),
                    str(prepared.replacement.end),
                    prepared.replacement.replacement_bytes.hex(),
                )
            ).encode("ascii")
        ).hexdigest()

        assert prepared.token != narrow_token, (
            "PreparedEdit.token must include wider candidate semantics "
            "than just page_fingerprint + splice bytes"
        )

    def test_edit_text_command_passes_plan_token_to_model(self):
        """EditTextCommand.execute() must pass plan_token to model.edit_text().

        Currently RED: EditTextCommand stores plan_token but never passes it.
        """
        from model.edit_commands import EditTextCommand

        captured_kwargs = {}

        class FakeModel:
            fidelity_protected_pages = set()
            doc = _stream_doc()
            last_commit_outcome = None
            block_manager = MagicMock()

            def edit_text(self, *args, **kwargs):
                captured_kwargs.update(kwargs)
                from model.edit_commands import EditTextResult
                return EditTextResult.SUCCESS

        model = FakeModel()
        snapshot = model.doc.tobytes()

        cmd = EditTextCommand(
            model=model,
            page_num=1,
            rect=fitz.Rect(72, 688, 90, 712),
            new_text=REPLACEMENT,
            font="helv",
            size=12.0,
            color=(0.0, 0.0, 0.0),
            original_text=TARGET,
            vertical_shift_left=True,
            page_snapshot_bytes=snapshot,
            old_block_id=None,
            old_block_text=TARGET,
            plan_token="test-preview-token-abc123",
        )
        cmd.execute()

        assert "plan_token" in captured_kwargs, (
            "EditTextCommand.execute() must pass plan_token= to model.edit_text()"
        )
        assert captured_kwargs["plan_token"] == "test-preview-token-abc123"


def _two_page_stream_doc() -> tuple[fitz.Document, int]:
    """Two-page doc; each page starts with its OWN ``/Contents`` stream, so
    ``prepare()``'s shared-content-stream scan passes cleanly at prepare
    time.  Returns ``(doc, page0_content_xref)`` so a test can later make
    page 1 start sharing page 0's stream, after the candidate is cached."""
    doc = fitz.open()
    page0 = doc.new_page(width=595, height=842)
    stream0 = b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj ET"
    content_xref0 = doc.get_new_xref()
    doc.update_object(content_xref0, "<<>>")
    doc.update_stream(content_xref0, stream0)
    doc.xref_set_key(page0.xref, "Contents", f"{content_xref0} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(font_xref, _FONT_OBJECT)
    doc.xref_set_key(
        page0.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>"
    )

    page1 = doc.new_page(width=595, height=842)
    stream1 = b"BT /F1 12 Tf 72 700 Td (unrelated) Tj ET"
    content_xref1 = doc.get_new_xref()
    doc.update_object(content_xref1, "<<>>")
    doc.update_stream(content_xref1, stream1)
    doc.xref_set_key(page1.xref, "Contents", f"{content_xref1} 0 R")
    doc.xref_set_key(
        page1.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>"
    )
    return doc, content_xref0


class TestCachedCandidateBypassesPolicyGates:
    """F2: a cached ``VerifiedPreparedEdit`` must not skip the gates a fresh
    prepare() would enforce.  Each test reproduces one attack: prepare and
    cache a token under conditions where NO override/sharing was present,
    then commit with that token under conditions where the SAME check --
    run fresh -- would refuse.  Before the fix, the cached branch never
    re-runs the gate and the attack commits; after the fix it must refuse
    with the same reason a fresh prepare would report.
    """

    def _prepare_and_cache(
        self, doc: fitz.Document
    ) -> tuple[PDFModel, str, SimpleNamespace]:
        model = PDFModel(
            text_commit_settings=TextCommitSettings(engine="tiered", max_tier=0)
        )
        model.doc = doc
        page = doc[0]
        origin = _first_char_origin(page, TARGET)
        bbox = _target_bbox(page, TARGET)
        engine = model.get_tiered_commit_engine()
        prepared = engine.prepare(
            page,
            target_text=TARGET,
            replacement_text=REPLACEMENT,
            expected_origin=origin,
            target_bbox=bbox,
        )
        assert isinstance(prepared, PreparedEdit)
        resolve_result = _make_resolve_result(page, TARGET)
        return model, prepared.token, resolve_result

    def test_cached_candidate_with_dragged_rect_is_refused_not_committed(self):
        """Attack (a): a cached token plus a user-dragged ``new_rect`` must
        refuse geometry_override_present, not silently commit and discard
        the drag -- exactly as a fresh prepare() would refuse it.
        """
        doc = _stream_doc()
        model, token, resolve_result = self._prepare_and_cache(doc)
        page = doc[0]
        bbox = _target_bbox(page, TARGET)
        dragged_rect = fitz.Rect(
            bbox[0] + 40, bbox[1] + 40, bbox[2] + 40, bbox[3] + 40
        )

        outcome, reason = _attempt_tiered_commit(
            model, page, 0, REPLACEMENT, resolve_result, None, dragged_rect,
            plan_token=token,
        )

        assert outcome is None, (
            "a cached candidate plus a dragged new_rect must not commit"
        )
        assert reason == RejectReason.GEOMETRY_OVERRIDE_PRESENT
        assert TARGET in page.get_text(), (
            "the drag must not silently mutate the page"
        )

    def test_cached_candidate_with_style_override_is_refused_not_committed(self):
        """Attack (b): a cached token plus an explicit restyle must refuse
        style_override_present, not silently commit and discard the
        restyle -- exactly as a fresh prepare() would refuse it.
        """
        doc = _stream_doc()
        model, token, resolve_result = self._prepare_and_cache(doc)
        page = doc[0]
        style = StyleOverrides(font_family="courier", font_size=14.0)

        outcome, reason = _attempt_tiered_commit(
            model, page, 0, REPLACEMENT, resolve_result, style, None,
            plan_token=token,
        )

        assert outcome is None, (
            "a cached candidate plus a style override must not commit"
        )
        assert reason == RejectReason.STYLE_OVERRIDE_PRESENT
        assert TARGET in page.get_text(), (
            "the restyle must not silently mutate the page"
        )

    def test_cached_candidate_refused_when_another_page_starts_sharing_the_stream(
        self,
    ):
        """The verifier's shared-content-stream scenario: prepare and cache
        a candidate while the target stream is exclusive to its page, then
        -- before committing -- another page starts referencing that same
        stream as its own ``/Contents``.  Committing the stale cached
        candidate must refuse SHARED_CONTENT_STREAM rather than silently
        rewriting the other page's content too.
        """
        doc, content_xref0 = _two_page_stream_doc()
        model, token, resolve_result = self._prepare_and_cache(doc)
        page0 = doc[0]
        stream_before = doc.xref_stream(content_xref0)

        # Another page starts sharing the target's content stream -- this
        # alone changes what page 1 renders (it now shows page 0's "iii"
        # instead of its own former "unrelated"); that repoint is not
        # itself the attack. The attack is a *commit* of the stale cached
        # candidate silently rewriting the now-shared stream underneath
        # both pages.
        page1_xref = doc.page_xref(1)
        doc.xref_set_key(page1_xref, "Contents", f"{content_xref0} 0 R")

        outcome, reason = _attempt_tiered_commit(
            model, page0, 0, REPLACEMENT, resolve_result, None, None,
            plan_token=token,
        )

        assert outcome is None, (
            "a cached candidate whose stream is now shared must not commit"
        )
        assert reason == RejectReason.SHARED_CONTENT_STREAM
        assert TARGET in page0.get_text()
        assert doc.xref_stream(content_xref0) == stream_before, (
            "the shared content stream must not be mutated by a refused commit"
        )

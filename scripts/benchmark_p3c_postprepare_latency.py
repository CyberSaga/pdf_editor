"""Task 13 P3-C acceptance harness — preview post-prepare latency.

Measures the production preview path (``PlanPreviewRenderer.render``) on a
deterministic synthetic dense page and verifies the slice's acceptance
contract in UPDATE_STREAM COMPRESS COUNTS, not milliseconds:

    every preview keystroke        -> 0 compressed update_stream calls
    every preview keystroke        -> 2 uncompressed calls (apply + revert)
    every live TieredCommitEngine
        .commit()                  -> >=1 compressed call, 0 uncompressed

plus a structural (not tracemalloc -- see plans/task13-p3c-... .md §4-E and
the F2 review finding) memory-bound check, and informational latency
percentiles with the span-resolution artifact the P3-B review flagged
(finding #2) hoisted out of every timed section.

Synthetic corpus only -- deterministic, privacy-free, reproducible by any
reviewer; no document text or paths beyond this script appear in the
report. The report is aggregate-only JSON under the gitignored
``benchmarks/``.

Run:  .venv\\Scripts\\python.exe scripts/benchmark_p3c_postprepare_latency.py
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz  # noqa: E402

from model.text_commit.dto import CommitStatus  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.plan import PreparedEdit, prepare_plan  # noqa: E402
from model.text_commit.preview import (  # noqa: E402
    PlanPreviewRenderer,
    PlanPreviewRequest,
    open_preview_session,
)

TARGET = "Price 2024"
WARM_KEYSTROKES = 30
MEMORY_KEYSTROKES = 100


class UpdateStreamCounter:
    """Counts fitz.Document.update_stream calls, split by resolved compress."""

    def __init__(self) -> None:
        self.compressed = 0
        self.uncompressed = 0
        self._orig = None

    def install(self) -> None:
        self._orig = fitz.Document.update_stream
        counter = self
        orig = self._orig

        def counting(doc_self, xref=0, stream=None, new=1, compress=1):
            if compress:
                counter.compressed += 1
            else:
                counter.uncompressed += 1
            return orig(doc_self, xref, stream, new, compress)

        fitz.Document.update_stream = counting

    def uninstall(self) -> None:
        if self._orig is not None:
            fitz.Document.update_stream = self._orig
            self._orig = None

    def take(self) -> tuple[int, int]:
        c, u = self.compressed, self.uncompressed
        self.compressed = 0
        self.uncompressed = 0
        return c, u


def _build_doc(*, dense: bool) -> fitz.Document:
    """One-page synthetic doc: Helvetica/WinAnsi literal-Tj shows.

    Matches ``scripts/benchmark_p3b_preview_reuse.py``'s corpus shape (same
    ~2.5 MiB token-dense, raster-free padding) so the two slices' numbers
    are directly comparable.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    parts = [b"BT /F1 12 Tf 72 700 Td (" + TARGET.encode() + b") Tj "]
    n_rows = 400 if dense else 8
    for i in range(n_rows):
        parts.append(b"0 -1.5 Td (Row %04d) Tj " % i)
    parts.append(b"ET\n")
    if dense:
        pad_target = int(2.5 * 1024 * 1024)
        line = bytearray()
        i = 0
        while len(line) < pad_target:
            a = (i % 89) + 1
            b = (i % 97) + 1
            line += b"q 1 0 0 1 %d %d cm Q\n" % (a, b)
            i += 1
        parts.append(bytes(line))
    stream = b"".join(parts)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    font_xref = doc.get_new_xref()
    doc.update_object(
        font_xref,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        "/Encoding /WinAnsiEncoding >>",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font_xref} 0 R >> >>")
    return doc


def _span(page: fitz.Page, probe: str) -> dict:
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = "".join(ch["c"] for ch in span["chars"])
                if probe in text:
                    return span
    raise AssertionError(f"span {probe!r} not found")


def _request(doc: fitz.Document, generation: int, replacement: str, span: dict) -> PlanPreviewRequest:
    bbox = tuple(span["bbox"])
    clip = (bbox[0] - 4.0, bbox[1] - 4.0, bbox[2] + 4.0, bbox[3] + 4.0)
    return PlanPreviewRequest(
        session_key="p3c-acceptance",
        generation=generation,
        target_text=TARGET,
        replacement_text=replacement,
        expected_origin=tuple(span["origin"]),
        target_bbox=bbox,
        clip_rect=clip,
        render_scale=2.0,
    )


def _percentiles(samples_ms: list[float]) -> dict:
    ordered = sorted(samples_ms)
    n = len(ordered)
    return {
        "n": n,
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[min(n - 1, max(0, round(n * 0.95) - 1))], 3),
        "min_ms": round(ordered[0], 3),
        "max_ms": round(ordered[-1], 3),
    }


def run_gate_and_latency(counter: UpdateStreamCounter) -> tuple[dict, list[str]]:
    """Dense-page renderer scenarios: cold, warm keystrokes -- compress-call
    counts are the acceptance gate; timings are informational only.

    Span resolution is computed ONCE outside every timed section (closing
    the P3-B review's finding #2: the prior benchmark's ``_request`` did a
    full-page ``get_text("rawdict")`` scan inside the timed window, which
    production's real caller never pays -- it already knows the target
    bbox from its own index).
    """
    failures: list[str] = []
    doc = _build_doc(dense=True)
    span = _span(doc[0], TARGET)

    session = open_preview_session(doc, 0, "p3c-acceptance")
    assert session is not None
    renderer = PlanPreviewRenderer(session)

    counter.take()
    t0 = time.perf_counter()
    cold = renderer.render(_request(doc, 1, "Price 2025", span))
    cold_ms = (time.perf_counter() - t0) * 1000.0
    cold_compressed, cold_uncompressed = counter.take()
    if not cold.plan_token:
        failures.append(f"cold render rejected: {cold.reject_reason}")
    if cold_compressed != 0:
        failures.append(f"cold render made {cold_compressed} compressed update_stream calls != 0")
    if cold_uncompressed != 2:
        failures.append(f"cold render made {cold_uncompressed} uncompressed calls != 2")

    warm_ms: list[float] = []
    warm_compressed_total = 0
    warm_uncompressed_total = 0
    warm_tokens = 0
    for i in range(WARM_KEYSTROKES):
        replacement = f"Price 2{i % 10}25"
        span = _span(doc[0], TARGET)  # hoisted out of the timed section
        t0 = time.perf_counter()
        result = renderer.render(_request(doc, 2 + i, replacement, span))
        warm_ms.append((time.perf_counter() - t0) * 1000.0)
        c, u = counter.take()
        warm_compressed_total += c
        warm_uncompressed_total += u
        if result.plan_token:
            warm_tokens += 1
    if warm_compressed_total != 0:
        failures.append(f"warm keystrokes made {warm_compressed_total} compressed calls != 0")
    if warm_uncompressed_total != 2 * WARM_KEYSTROKES:
        failures.append(
            f"warm keystrokes made {warm_uncompressed_total} uncompressed calls "
            f"!= {2 * WARM_KEYSTROKES}"
        )
    if warm_tokens != WARM_KEYSTROKES:
        failures.append(f"warm accepted {warm_tokens}/{WARM_KEYSTROKES}")

    renderer.close()
    doc.close()

    # Live commit path: regression guard -- must be completely unaffected.
    live_doc = _build_doc(dense=False)
    engine = TieredCommitEngine(live_doc)
    live_page = live_doc[0]
    live_span = _span(live_page, TARGET)
    plan = prepare_plan(
        live_doc, live_page,
        target_text=TARGET, replacement_text="Price 2025",
        expected_origin=tuple(live_span["origin"]), target_bbox=None,
        registry=engine.registry,
    )
    assert isinstance(plan, PreparedEdit), plan
    counter.take()
    outcome = engine.commit(plan)
    commit_compressed, commit_uncompressed = counter.take()
    if outcome.status != CommitStatus.COMMITTED:
        failures.append(f"live commit did not succeed: {outcome.status}")
    if commit_compressed < 1:
        failures.append(f"live commit made {commit_compressed} compressed calls, expected >=1")
    if commit_uncompressed != 0:
        failures.append(f"live commit made {commit_uncompressed} uncompressed calls, expected 0")
    live_doc.close()

    report = {
        "cold_render": {
            "ms": round(cold_ms, 3),
            "compressed_calls": cold_compressed,
            "uncompressed_calls": cold_uncompressed,
        },
        "warm_renders": {
            **_percentiles(warm_ms),
            "compressed_calls_total": warm_compressed_total,
            "uncompressed_calls_total": warm_uncompressed_total,
            "accepted": warm_tokens,
        },
        "live_commit": {
            "status": outcome.status.value,
            "compressed_calls": commit_compressed,
            "uncompressed_calls": commit_uncompressed,
        },
    }
    return report, failures


def run_memory(counter: UpdateStreamCounter) -> tuple[dict, list[str]]:
    """Structural memory-bound loop: the scratch's stored content-stream
    representation must be IDENTICAL after every keystroke (a one-time
    expansion, never an accumulation) -- see the F2 review finding for why
    this is asserted on ``xref_stream_raw`` and not ``tracemalloc``."""
    failures: list[str] = []
    doc = _build_doc(dense=False)
    session = open_preview_session(doc, 0, "p3c-acceptance")
    assert session is not None
    renderer = PlanPreviewRenderer(session)

    span = _span(doc[0], TARGET)
    result = renderer.render(_request(doc, 0, "Price 2025", span))
    if not result.plan_token:
        failures.append(f"keystroke 0 rejected: {result.reject_reason}")
    scratch = renderer._scratch
    content_xref = scratch[0].get_contents()[0]
    raw_lens: set[int] = {len(scratch.xref_stream_raw(content_xref))}

    for i in range(1, MEMORY_KEYSTROKES):
        span = _span(doc[0], TARGET)
        result = renderer.render(_request(doc, i, f"Price 2{i % 10}25", span))
        if not result.plan_token:
            failures.append(f"keystroke {i} rejected: {result.reject_reason}")
            break
        raw_lens.add(len(scratch.xref_stream_raw(content_xref)))

    if len(raw_lens) != 1:
        failures.append(f"stored representation size drifted across keystrokes: {sorted(raw_lens)}")
    counter.take()
    renderer.close()
    doc.close()
    return {
        "keystrokes": MEMORY_KEYSTROKES,
        "distinct_stored_representation_sizes": sorted(raw_lens),
    }, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json-out",
        type=Path,
        default=ROOT / "benchmarks" / "p3c-acceptance-2026-08-23.json",
        help="aggregate-only report path (gitignored benchmarks/ by default)",
    )
    args = parser.parse_args(argv)

    counter = UpdateStreamCounter()
    counter.install()
    try:
        gate_latency, fail_a = run_gate_and_latency(counter)
        memory, fail_b = run_memory(counter)
    finally:
        counter.uninstall()
    failures = fail_a + fail_b
    report = {
        "harness": "p3c-preview-postprepare-latency-acceptance",
        "corpus": "synthetic-deterministic (this script)",
        "acceptance": {
            "passed": not failures,
            "failures": failures,
            "contract": {
                "preview_compressed_calls": 0,
                "preview_uncompressed_calls_per_keystroke": 2,
                "live_commit_compressed_calls_min": 1,
                "live_commit_uncompressed_calls": 0,
                "memory_distinct_representation_sizes": 1,
            },
        },
        "gate_and_latency": gate_latency,
        "memory": memory,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["acceptance"], indent=2))
    print(
        f"cold {gate_latency['cold_render']['ms']} ms / warm p50 "
        f"{gate_latency['warm_renders']['p50_ms']} ms (report: {args.json_out})"
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

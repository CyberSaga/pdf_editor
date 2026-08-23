"""Task 13 P3-C bridge — committed stage-decomposition census, dual-mode.

The original P3-C census (plans/task13-p3c-preview-postprepare-latency.md
§3.2) was ad-hoc instrumentation that never landed in the tree.  This
harness is the committed, reproducible version, and it closes the
remaining acceptance-report gaps in one run:

  * per-stage p50/p95 for BOTH the shipped code (``compress=False`` on
    the preview scratch) and a compress=True control mode — the honest
    "old vs new per-stage" comparison, measured in the same process on
    the same corpus;
  * a full per-keystroke primitive counter table (``get_pixmap`` full vs
    clipped, ``get_text``, ``get_textpage``, ``get_displaylist``,
    ``get_fonts``, ``xref_stream``/``xref_stream_raw`` reads,
    ``update_stream`` by resolved compress, ``page_fingerprint`` calls,
    replay executions) — the evidence base for the deferred
    DisplayList/baseline-reuse design (P3-D candidate);
  * a small-page control corpus next to the dense page (regression
    check: the optimization must not have made cheap pages slower);
  * cold-path old-vs-new on both corpora;
  * the P3-B replay contract re-asserted inside this harness (cold
    render replays exactly once, warm keystrokes replay exactly zero
    times) so a P3-C-era regression in replay semantics cannot hide
    behind the compress-count gate;
  * plan-token identity between the two modes (the storage-encoding
    flag must be observationally invisible);
  * process working-set snapshots (Windows ``GetProcessMemoryInfo``;
    informational — the peak counter is process-wide and monotonic, so
    it cannot be attributed to one mode.  The authoritative per-object
    memory bound stays the structural ``xref_stream_raw`` check in
    ``benchmark_p3c_postprepare_latency.py``; ``tracemalloc`` remains
    excluded per the F2 review finding — blind to MuPDF's C heap).

Latency numbers are informational; the gates are counts and identity.

Each scenario runs twice: a CLEAN pass (counters only — near-zero
overhead, source of the end-to-end percentiles) and a PROBED pass
(stage/primitive timing wrappers installed — source of the per-stage
decomposition; its end-to-end time includes probe overhead and is
reported separately, never mixed with the clean numbers).

Synthetic corpus only — deterministic, privacy-free, reproducible by any
reviewer; no document text or paths beyond this script appear in the
report.  The spec's private-real-corpus leg requires a locally provided
real-PDF corpus (absent by default; the fidelity corpus is synthetic and
generated on demand) and remains open until one exists.  Aggregate-only
JSON is written under the gitignored ``benchmarks/``.

Run:  .venv\\Scripts\\python.exe scripts/benchmark_p3c_stage_census.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz  # noqa: E402

import model.text_commit.evidence as evidence_module  # noqa: E402
import model.text_commit.inspect as inspect_module  # noqa: E402
import model.text_commit.patch as patch_module  # noqa: E402
import model.text_commit.plan as plan_module  # noqa: E402
import model.text_commit.preview as preview_module  # noqa: E402
import model.text_commit.replay as replay_module  # noqa: E402
from model.text_commit.preview import (  # noqa: E402
    PlanPreviewRenderer,
    open_preview_session,
)
from scripts.benchmark_p3c_postprepare_latency import (  # noqa: E402
    TARGET,
    UpdateStreamCounter,
    _build_doc,
    _percentiles,
    _request,
    _span,
)

WARM_KEYSTROKES = 30

# ``page_fingerprint`` and ``replay_page_streams`` are imported BY NAME
# into sibling modules, so a counting shim must patch every namespace
# that holds a reference (the P3-B harness's _ReplayCounter precedent).
_FINGERPRINT_NAMESPACES = (inspect_module, patch_module, plan_module, preview_module)
_REPLAY_NAMESPACES = (replay_module, evidence_module, inspect_module)


class _NamespaceCounter:
    """Counts calls to one function name across every importing namespace."""

    def __init__(self, namespaces: tuple[Any, ...], name: str) -> None:
        self._namespaces = namespaces
        self._name = name
        self._saved: list[tuple[Any, Callable[..., Any]]] = []
        self.count = 0

    def install(self) -> None:
        for mod in self._namespaces:
            orig = getattr(mod, self._name)
            self._saved.append((mod, orig))

            def counting(
                *args: Any, _orig: Callable[..., Any] = orig, **kwargs: Any
            ) -> Any:
                self.count += 1
                return _orig(*args, **kwargs)

            setattr(mod, self._name, counting)

    def uninstall(self) -> None:
        for mod, orig in reversed(self._saved):
            setattr(mod, self._name, orig)
        self._saved.clear()

    def take(self) -> int:
        n = self.count
        self.count = 0
        return n


class CompressOverride:
    """Force ``compress=True`` on the preview scratch's two call sites.

    This is the CONTROL mode — byte-for-byte the pre-P3-C behavior,
    recreated the same way the shipped equivalence test
    (``test_preview_renderer_output_identical_between_compress_true_and_false``)
    does it: wrap ``preview``'s ``apply_patchset`` reference and
    ``AppliedPatch.revert`` on the class, overriding the ``compress``
    keyword.  Installed *before* any stage probe so the probe times the
    overridden (compressed) call.
    """

    def __init__(self) -> None:
        self._orig_apply: Callable[..., Any] | None = None
        self._orig_revert: Callable[..., Any] | None = None

    def install(self) -> None:
        self._orig_apply = preview_module.apply_patchset
        self._orig_revert = patch_module.AppliedPatch.revert
        orig_apply = self._orig_apply
        orig_revert = self._orig_revert

        def forced_apply(*args: Any, **kwargs: Any) -> Any:
            kwargs["compress"] = True
            return orig_apply(*args, **kwargs)

        def forced_revert(*args: Any, **kwargs: Any) -> Any:
            kwargs["compress"] = True
            return orig_revert(*args, **kwargs)

        preview_module.apply_patchset = forced_apply  # type: ignore[assignment]
        patch_module.AppliedPatch.revert = forced_revert  # type: ignore[method-assign]

    def uninstall(self) -> None:
        if self._orig_apply is not None:
            preview_module.apply_patchset = self._orig_apply  # type: ignore[assignment]
            self._orig_apply = None
        if self._orig_revert is not None:
            patch_module.AppliedPatch.revert = self._orig_revert  # type: ignore[method-assign]
            self._orig_revert = None


class StageProbe:
    """Attributes wall time and primitive calls to pipeline stages.

    Stage functions (``prepare_plan``, ``capture_page_state``,
    ``apply_patchset``, ``verify_tier0/1_commit``, ``AppliedPatch.revert``)
    are wrapped in the namespace ``PlanPreviewRenderer.render`` actually
    calls them through; ``fitz`` primitives are wrapped on their classes
    and attribute to whichever stage is live when they fire.  Primitive
    calls inside ``render`` but outside every wrapped stage (the final
    preview raster and its PNG encode) land in ``render_other``.
    """

    _STAGES = (
        (preview_module, "prepare_plan", "prepare"),
        (preview_module, "capture_page_state", "capture"),
        (preview_module, "apply_patchset", "apply"),
        (preview_module, "verify_tier0_commit", "verify"),
        (preview_module, "verify_tier1_commit", "verify"),
        (patch_module.AppliedPatch, "revert", "revert"),
    )

    def __init__(self) -> None:
        self.stage = "outside"
        self.current: dict[str, Any] | None = None
        self.records: list[dict[str, Any]] = []
        self._saved: list[tuple[Any, str, Callable[..., Any]]] = []

    # -- render bracketing -------------------------------------------------
    def begin_render(self) -> None:
        self.current = {
            "stage_ms": defaultdict(float),
            "calls": defaultdict(int),
            "call_ms": defaultdict(float),
        }

    def end_render(self, total_ms: float) -> None:
        assert self.current is not None
        self.current["total_ms"] = total_ms
        self.records.append(self.current)
        self.current = None

    # -- installation ------------------------------------------------------
    def install(self) -> None:
        for obj, name, stage in self._STAGES:
            self._wrap_stage(obj, name, stage)
        page = fitz.Page
        doc = fitz.Document
        self._wrap_call(page, "get_pixmap", classify=self._classify_pixmap)
        self._wrap_call(page, "get_text", key="get_text")
        self._wrap_call(page, "get_textpage", key="get_textpage")
        self._wrap_call(page, "get_displaylist", key="get_displaylist")
        self._wrap_call(page, "get_fonts", key="get_fonts")
        self._wrap_call(doc, "xref_stream", key="xref_stream_read")
        self._wrap_call(doc, "xref_stream_raw", key="xref_stream_raw_read")
        self._wrap_call(doc, "update_stream", classify=self._classify_update_stream)
        self._wrap_call(fitz.Pixmap, "tobytes", key="pixmap_tobytes")
        for mod in _FINGERPRINT_NAMESPACES:
            self._wrap_call(mod, "page_fingerprint", key="page_fingerprint")
        for mod in _REPLAY_NAMESPACES:
            self._wrap_call(mod, "replay_page_streams", key="replay")

    def uninstall(self) -> None:
        for obj, name, orig in reversed(self._saved):
            setattr(obj, name, orig)
        self._saved.clear()

    # -- wrapper factories -------------------------------------------------
    def _wrap_stage(self, obj: Any, name: str, stage: str) -> None:
        orig = getattr(obj, name)

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            prev = self.stage
            self.stage = stage
            t0 = time.perf_counter()
            try:
                return orig(*args, **kwargs)
            finally:
                dt = (time.perf_counter() - t0) * 1000.0
                self.stage = prev
                if self.current is not None:
                    self.current["stage_ms"][stage] += dt

        setattr(obj, name, wrapped)
        self._saved.append((obj, name, orig))

    def _wrap_call(
        self,
        obj: Any,
        name: str,
        *,
        key: str | None = None,
        classify: Callable[[tuple[Any, ...], dict[str, Any]], str] | None = None,
    ) -> None:
        orig = getattr(obj, name)

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter()
            try:
                return orig(*args, **kwargs)
            finally:
                if self.current is not None:
                    dt = (time.perf_counter() - t0) * 1000.0
                    label = classify(args, kwargs) if classify is not None else key
                    slot = f"{self.stage}:{label}"
                    self.current["calls"][slot] += 1
                    self.current["call_ms"][slot] += dt

        setattr(obj, name, wrapped)
        self._saved.append((obj, name, orig))

    @staticmethod
    def _classify_pixmap(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
        if kwargs.get("clip") is not None:
            return "get_pixmap_clipped"
        return "get_pixmap_full"

    @staticmethod
    def _classify_update_stream(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
        # fitz.Document.update_stream(self, xref, stream, new=1, compress=1)
        compress = kwargs.get("compress", args[4] if len(args) > 4 else 1)
        if compress:
            return "update_stream_compressed"
        return "update_stream_uncompressed"

    # -- aggregation -------------------------------------------------------
    def summarize(self) -> dict[str, Any]:
        """Cold (first render) decomposition + WARM per-stage p50/p95 and a
        per-warm-keystroke primitive table.

        The cold render is split out rather than averaged in: its one-time
        replay walk would otherwise smear seconds across every warm mean.
        Primitive CALL COUNTS are exact; primitive MS overlap for nested
        PyMuPDF utils (``get_text`` builds and therefore includes its
        ``get_textpage``; ``get_pixmap`` builds and includes its
        ``get_displaylist``), so ms columns must not be summed across
        nested rows -- the non-overlapping truth is the stage table.
        """
        cold, warm = self.records[0], self.records[1:]

        def _stage_rows(records: list[dict[str, Any]]) -> dict[str, list[float]]:
            series: dict[str, list[float]] = defaultdict(list)
            for record in records:
                accounted = 0.0
                for stage, ms in record["stage_ms"].items():
                    series[stage].append(ms)
                    accounted += ms
                series["render_other"].append(record["total_ms"] - accounted)
                series["total_probed"].append(record["total_ms"])
            return series

        warm_stages = {
            stage: _percentiles(series)
            for stage, series in sorted(_stage_rows(warm).items())
        }
        n = max(1, len(warm))
        calls_total: dict[str, int] = defaultdict(int)
        call_ms_total: dict[str, float] = defaultdict(float)
        for record in warm:
            for slot, count in record["calls"].items():
                calls_total[slot] += count
            for slot, ms in record["call_ms"].items():
                call_ms_total[slot] += ms
        warm_primitives = {
            slot: {
                "calls_per_keystroke": round(calls_total[slot] / n, 2),
                "ms_per_keystroke": round(call_ms_total[slot] / n, 3),
            }
            for slot in sorted(calls_total)
        }
        return {
            "warm_renders": len(warm),
            "cold": {
                "stage_ms": {
                    stage: round(ms, 3)
                    for stage, ms in sorted(cold["stage_ms"].items())
                },
                "total_ms": round(cold["total_ms"], 3),
                "calls": dict(sorted(cold["calls"].items())),
            },
            "warm_stages": warm_stages,
            "warm_primitives": warm_primitives,
        }


def _working_set_snapshot() -> dict[str, float] | None:
    """Windows process working-set counters, informational only.

    ``peak_mb`` is process-wide and monotonic — it cannot distinguish
    which mode/corpus produced it; ``current_mb`` sampled per scenario is
    the retained-memory signal.  Returns ``None`` off Windows or on any
    API failure (never raises).
    """
    try:
        import ctypes
        from ctypes import wintypes

        class _Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        # Typed argtypes are load-bearing: the untyped ``windll`` call path
        # truncates GetCurrentProcess()'s 64-bit pseudo-handle and the API
        # was observed to fail with ok=0 / GetLastError()=0.
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        info = psapi.GetProcessMemoryInfo
        info.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD]
        info.restype = wintypes.BOOL
        counters = _Counters()
        counters.cb = ctypes.sizeof(_Counters)
        ok = info(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        if not ok:
            return None
        return {
            "current_mb": round(counters.WorkingSetSize / (1024 * 1024), 1),
            "peak_mb": round(counters.PeakWorkingSetSize / (1024 * 1024), 1),
        }
    except Exception:  # noqa: BLE001 -- informational probe, never fatal
        return None


def run_scenario(
    *, mode: str, dense: bool, probed: bool, failures: list[str]
) -> dict[str, Any]:
    """One (mode, corpus, pass) cell: cold render + WARM_KEYSTROKES warm."""
    label = f"{mode}/{'dense' if dense else 'small'}/{'probed' if probed else 'clean'}"
    doc = _build_doc(dense=dense)
    span = _span(doc[0], TARGET)
    session = open_preview_session(doc, 0, "p3c-census")
    assert session is not None
    renderer = PlanPreviewRenderer(session)

    override = CompressOverride() if mode == "control" else None
    if override is not None:
        override.install()
    probe = StageProbe() if probed else None
    stream_counter = UpdateStreamCounter()
    replay_counter = _NamespaceCounter(_REPLAY_NAMESPACES, "replay_page_streams")
    try:
        if probe is not None:
            probe.install()
        else:
            # Clean pass: the cheap counters only (2 update_stream calls
            # and <=1 replay per render — negligible next to the render).
            stream_counter.install()
            replay_counter.install()

        def one_render(generation: int, replacement: str) -> tuple[float, str | None]:
            if probe is not None:
                probe.begin_render()
            t0 = time.perf_counter()
            result = renderer.render(_request(doc, generation, replacement, span))
            total_ms = (time.perf_counter() - t0) * 1000.0
            if probe is not None:
                probe.end_render(total_ms)
            if not result.plan_token:
                failures.append(f"{label}: render rejected: {result.reject_reason}")
            return total_ms, result.plan_token

        cold_ms, cold_token = one_render(1, "Price 2025")
        cold_replays = replay_counter.take() if probe is None else None
        cold_compressed, cold_uncompressed = (
            stream_counter.take() if probe is None else (None, None)
        )

        warm_ms: list[float] = []
        warm_tokens: list[str | None] = []
        warm_replays = 0
        warm_compressed = 0
        warm_uncompressed = 0
        for i in range(WARM_KEYSTROKES):
            ms, token = one_render(2 + i, f"Price 2{i % 10}25")
            warm_ms.append(ms)
            warm_tokens.append(token)
            if probe is None:
                warm_replays += replay_counter.take()
                c, u = stream_counter.take()
                warm_compressed += c
                warm_uncompressed += u
    finally:
        if probe is not None:
            probe.uninstall()
        else:
            replay_counter.uninstall()
            stream_counter.uninstall()
        if override is not None:
            override.uninstall()
        renderer.close()
        doc.close()

    record: dict[str, Any] = {
        "cold_ms": round(cold_ms, 3),
        "warm": _percentiles(warm_ms),
        "tokens": [cold_token, *warm_tokens],
    }
    if probe is not None:
        record["decomposition"] = probe.summarize()
    else:
        record["cold_replays"] = cold_replays
        record["warm_replays_total"] = warm_replays
        record["cold_update_stream"] = {
            "compressed": cold_compressed,
            "uncompressed": cold_uncompressed,
        }
        record["warm_update_stream"] = {
            "compressed": warm_compressed,
            "uncompressed": warm_uncompressed,
        }
        # P3-B replay contract, re-asserted inside this harness.
        if cold_replays != 1:
            failures.append(f"{label}: cold render replays {cold_replays} != 1")
        if warm_replays != 0:
            failures.append(f"{label}: warm keystrokes replayed {warm_replays} != 0")
        # Compress-count contract per mode (also proves the control-mode
        # override actually engaged rather than silently no-opping).
        expected = (0, 2) if mode == "shipped" else (2, 0)
        if (cold_compressed, cold_uncompressed) != expected:
            failures.append(
                f"{label}: cold update_stream (compressed, uncompressed) = "
                f"({cold_compressed}, {cold_uncompressed}) != {expected}"
            )
        expected_warm = (expected[0] * WARM_KEYSTROKES, expected[1] * WARM_KEYSTROKES)
        if (warm_compressed, warm_uncompressed) != expected_warm:
            failures.append(
                f"{label}: warm update_stream totals = "
                f"({warm_compressed}, {warm_uncompressed}) != {expected_warm}"
            )
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json-out",
        type=Path,
        default=ROOT / "benchmarks" / "p3c-stage-census-2026-08-23.json",
        help="aggregate-only report path (gitignored benchmarks/ by default)",
    )
    args = parser.parse_args(argv)

    failures: list[str] = []
    results: dict[str, Any] = {}
    memory: dict[str, Any] = {"start": _working_set_snapshot()}
    for mode in ("shipped", "control"):
        for dense in (True, False):
            corpus = "dense" if dense else "small"
            for probed in (False, True):
                cell = run_scenario(
                    mode=mode, dense=dense, probed=probed, failures=failures
                )
                results.setdefault(mode, {}).setdefault(corpus, {})[
                    "probed" if probed else "clean"
                ] = cell
            memory[f"after_{mode}_{corpus}"] = _working_set_snapshot()

    # Token identity between modes: the storage-encoding flag must be
    # observationally invisible on every corpus (clean passes compared;
    # probed passes render the same sequence, so identity is implied).
    for corpus in ("dense", "small"):
        shipped_tokens = results["shipped"][corpus]["clean"]["tokens"]
        control_tokens = results["control"][corpus]["clean"]["tokens"]
        if shipped_tokens != control_tokens:
            failures.append(f"{corpus}: plan tokens differ between shipped and control")
        # Tokens are content-derived; keep them out of the committed
        # record beyond the equality verdict.
        for mode in ("shipped", "control"):
            for cell in results[mode][corpus].values():
                cell.pop("tokens", None)

    comparison = {
        corpus: {
            "warm_p50_ms_control_vs_shipped": [
                results["control"][corpus]["clean"]["warm"]["p50_ms"],
                results["shipped"][corpus]["clean"]["warm"]["p50_ms"],
            ],
            "warm_p95_ms_control_vs_shipped": [
                results["control"][corpus]["clean"]["warm"]["p95_ms"],
                results["shipped"][corpus]["clean"]["warm"]["p95_ms"],
            ],
            "cold_ms_control_vs_shipped": [
                results["control"][corpus]["clean"]["cold_ms"],
                results["shipped"][corpus]["clean"]["cold_ms"],
            ],
        }
        for corpus in ("dense", "small")
    }

    report = {
        "harness": "p3c-stage-census-dual-mode",
        "corpus": (
            "synthetic-deterministic (scripts/benchmark_p3c_postprepare_latency"
            "._build_doc); private real-PDF corpus leg remains OPEN -- requires"
            " a locally provided corpus, absent by default"
        ),
        "warm_keystrokes_per_cell": WARM_KEYSTROKES,
        "acceptance": {"passed": not failures, "failures": failures},
        "comparison": comparison,
        "results": results,
        "memory_working_set": memory,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {"acceptance": report["acceptance"], "comparison": comparison}, indent=2
        )
    )
    print(f"report: {args.json_out}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""P3-D interpretation-reuse acceptance census.

Stage A compares the shipped post-patch interpretation against a test-only
legacy adapter. Stage B modes are added only after the Stage-A GO decision.
Counts and identity are hard gates; latency and working-set values are
informational. Aggregate-only JSON is written below gitignored benchmarks/.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
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
from model.text_commit.interpretation import PageInterpretation  # noqa: E402
from model.text_commit.preview import (  # noqa: E402
    PlanPreviewRenderer,
    PlanPreviewRequest,
    open_preview_session,
)
from scripts.benchmark_p3c_postprepare_latency import (  # noqa: E402
    TARGET,
    _build_doc,
    _percentiles,
    _span,
)

WARM_KEYSTROKES = 30
_FINGERPRINT_NAMESPACES = (inspect_module, patch_module, plan_module, preview_module)
_REPLAY_NAMESPACES = (replay_module, evidence_module, inspect_module)


class LegacyPostInterpretation:
    """Test-only adapter recreating the pre-P3-D page utility calls."""

    def __init__(self, page: fitz.Page, engagement: Counter[str]) -> None:
        self.page = page
        self.engagement = engagement
        engagement["factory"] += 1

    def pixmap(
        self,
        *,
        dpi: int | float | None = None,
        matrix: fitz.Matrix = fitz.Identity,
        clip: fitz.Rect | tuple[float, float, float, float] | None = None,
    ) -> fitz.Pixmap:
        self.engagement["pixmap"] += 1
        return self.page.get_pixmap(
            dpi=dpi, matrix=matrix, clip=clip, annots=True
        )

    def rawdict(self) -> dict[str, object]:
        self.engagement["rawdict"] += 1
        return self.page.get_text("rawdict")

    def clipped_text(self, clip_dict_space: fitz.Rect) -> str:
        self.engagement["clipped_text"] += 1
        return self.page.get_text("text", clip=clip_dict_space)

    def release(self) -> None:
        self.engagement["release"] += 1


class HarnessProbe:
    """Per-render stage, primitive, replay, and verification recorder."""

    def __init__(self, *, full: bool) -> None:
        self.full = full
        self.stage = "render_other"
        self.current: dict[str, Any] | None = None
        self.records: list[dict[str, Any]] = []
        self._saved: list[tuple[Any, str, Callable[..., Any]]] = []

    def begin_render(self) -> None:
        self.current = {
            "stage_ms": defaultdict(float),
            "calls": Counter(),
            "verification": None,
        }

    def end_render(self, total_ms: float) -> None:
        assert self.current is not None
        self.current["total_ms"] = total_ms
        self.records.append(self.current)
        self.current = None

    def install(self) -> None:
        if self.full:
            for obj, name, stage in (
                (preview_module, "prepare_plan", "prepare"),
                (preview_module, "capture_page_state", "capture"),
                (preview_module, "apply_patchset", "apply"),
                (patch_module.AppliedPatch, "revert", "revert"),
            ):
                self._wrap_stage(obj, name, stage)
        self._wrap_verify(preview_module, "verify_tier0_commit")
        self._wrap_verify(preview_module, "verify_tier1_commit")
        self._wrap_interpret()
        self._wrap_call(fitz.Document, "update_stream", self._update_key)
        for namespace in _REPLAY_NAMESPACES:
            self._wrap_call(namespace, "replay_page_streams", lambda *_: "replay")
        if not self.full:
            return
        for namespace in _FINGERPRINT_NAMESPACES:
            self._wrap_call(namespace, "page_fingerprint", lambda *_: "page_fingerprint")
        for obj, name, key in (
            (fitz.Page, "get_pixmap", "page_get_pixmap"),
            (fitz.Page, "get_text", "page_get_text"),
            (fitz.Page, "get_textpage", "page_get_textpage"),
            (fitz.Page, "get_displaylist", "page_get_displaylist"),
            (fitz.Page, "get_drawings", "page_get_drawings"),
            (fitz.DisplayList, "get_pixmap", "displaylist_get_pixmap"),
            (fitz.DisplayList, "get_textpage", "displaylist_get_textpage"),
            (PageInterpretation, "clipped_text", "lowlevel_clipped_stext"),
        ):
            self._wrap_call(obj, name, lambda *_args, _key=key: _key)

    def uninstall(self) -> None:
        for obj, name, original in reversed(self._saved):
            setattr(obj, name, original)
        self._saved.clear()

    def _wrap_stage(self, obj: Any, name: str, stage: str) -> None:
        original = getattr(obj, name)

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            prior = self.stage
            self.stage = stage
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                elapsed = (time.perf_counter() - started) * 1000
                self.stage = prior
                if self.current is not None:
                    self.current["stage_ms"][stage] += elapsed

        setattr(obj, name, wrapped)
        self._saved.append((obj, name, original))

    def _wrap_verify(self, obj: Any, name: str) -> None:
        original = getattr(obj, name)

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            prior = self.stage
            self.stage = "verify"
            started = time.perf_counter()
            try:
                result = original(*args, **kwargs)
                if self.current is not None:
                    self.current["verification"] = result
                return result
            finally:
                elapsed = (time.perf_counter() - started) * 1000
                self.stage = prior
                if self.full and self.current is not None:
                    self.current["stage_ms"]["verify"] += elapsed

        setattr(obj, name, wrapped)
        self._saved.append((obj, name, original))

    def _wrap_interpret(self) -> None:
        original = preview_module.interpret_page

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            prior = self.stage
            self.stage = "interpret"
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                elapsed = (time.perf_counter() - started) * 1000
                self.stage = prior
                if self.current is not None:
                    self.current["calls"]["interpret_page"] += 1
                    if self.full:
                        self.current["stage_ms"]["interpret"] += elapsed

        preview_module.interpret_page = wrapped
        self._saved.append((preview_module, "interpret_page", original))

    def _wrap_call(
        self,
        obj: Any,
        name: str,
        classify: Callable[[tuple[Any, ...], dict[str, Any]], str],
    ) -> None:
        original = getattr(obj, name)

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            try:
                return original(*args, **kwargs)
            finally:
                if self.current is not None:
                    self.current["calls"][classify(args, kwargs)] += 1

        setattr(obj, name, wrapped)
        self._saved.append((obj, name, original))

    @staticmethod
    def _update_key(
        args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> str:
        compress = kwargs.get("compress", args[4] if len(args) > 4 else 1)
        return (
            "update_stream_compressed"
            if compress
            else "update_stream_uncompressed"
        )


def _request(doc: fitz.Document, generation: int, replacement: str) -> PlanPreviewRequest:
    return PlanPreviewRequest(
        session_key="p3d-census",
        generation=generation,
        target_text=TARGET,
        replacement_text=replacement,
        expected_origin=None,
        target_bbox=None,
        clip_rect=tuple(float(value) for value in doc[0].rect),
        render_scale=1.5,
    )


def _observable(result: Any, verification: Any) -> tuple[Any, ...]:
    return (
        result.png_bytes,
        result.plan_token,
        result.reject_reason,
        verification,
        result.clip_rect,
        result.render_scale,
        result.new_rect,
        result.prepared,
    )


def _summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    cold = records[0]
    warm = records[1:]
    calls: dict[str, list[int]] = defaultdict(list)
    stages: dict[str, list[float]] = defaultdict(list)
    for record in warm:
        for key in set(record["calls"]):
            calls[key].append(record["calls"][key])
        for key, value in record["stage_ms"].items():
            stages[key].append(value)
    return {
        "cold_calls": dict(sorted(cold["calls"].items())),
        "warm_calls_per_render": {
            key: sorted(set(values)) for key, values in sorted(calls.items())
        },
        "warm_stages_ms": {
            key: _percentiles(values) for key, values in sorted(stages.items())
        },
    }


def _assert_counts(
    *, mode: str, rotated: bool, records: list[dict[str, Any]], failures: list[str]
) -> None:
    expected = {
        "page_get_pixmap": 1 if mode == "stage-a-shipped" else 3,
        "page_get_text": 2 if mode == "stage-a-shipped" else 3,
        "page_get_textpage": 1 if mode == "stage-a-shipped" else 3,
        "page_get_displaylist": (
            (3 if rotated else 2) if mode == "stage-a-shipped" else 3
        ),
        "displaylist_get_pixmap": 3,
        "displaylist_get_textpage": 1 if mode == "stage-a-shipped" else 0,
        "lowlevel_clipped_stext": 1 if mode == "stage-a-shipped" else 0,
        "interpret_page": 1,
        "update_stream_compressed": 0,
        "update_stream_uncompressed": 2,
    }
    for index, record in enumerate(records):
        label = "cold" if index == 0 else f"warm-{index}"
        calls = record["calls"]
        for key, value in expected.items():
            if calls[key] != value:
                failures.append(
                    f"{mode}/{'rotated' if rotated else 'unrotated'}/{label}: "
                    f"{key}={calls[key]} != {value}"
                )
        interpretations = calls["page_get_displaylist"] + calls["page_get_textpage"]
        expected_interpretations = (
            (4 if rotated else 3) if mode == "stage-a-shipped" else 6
        )
        if interpretations != expected_interpretations:
            failures.append(
                f"{mode}/{label}: interpretations={interpretations} "
                f"!= {expected_interpretations}"
            )
        expected_replay = 1 if index == 0 else 0
        if calls["replay"] != expected_replay:
            failures.append(
                f"{mode}/{label}: replay={calls['replay']} != {expected_replay}"
            )


def run_scenario(
    *, mode: str, corpus: str, probed: bool, failures: list[str]
) -> dict[str, Any]:
    dense = corpus != "small"
    rotated = corpus == "dense-rotated"
    doc = _build_doc(dense=dense)
    if rotated:
        doc[0].set_rotation(270)
    # Validate the target before installing render instrumentation.
    _span(doc[0], TARGET)
    session = open_preview_session(doc, 0, "p3d-census")
    assert session is not None
    renderer = PlanPreviewRenderer(session)
    engagement: Counter[str] = Counter()
    original_interpret = preview_module.interpret_page
    if mode == "legacy-control":
        preview_module.interpret_page = lambda page: LegacyPostInterpretation(
            page, engagement
        )  # type: ignore[assignment]
    probe = HarnessProbe(full=probed)
    probe.install()
    observations: list[tuple[Any, ...]] = []
    timings: list[float] = []
    try:
        for index in range(WARM_KEYSTROKES + 1):
            probe.begin_render()
            started = time.perf_counter()
            result = renderer.render(
                _request(doc, index + 1, f"Price 2{index % 10}25")
            )
            elapsed = (time.perf_counter() - started) * 1000
            probe.end_render(elapsed)
            timings.append(elapsed)
            verification = probe.records[-1]["verification"]
            observations.append(_observable(result, verification))
            if result.plan_token is None:
                failures.append(
                    f"{mode}/{corpus}: render {index} rejected: {result.reject_reason}"
                )
    finally:
        probe.uninstall()
        preview_module.interpret_page = original_interpret
        renderer.close()
        doc.close()
    if mode == "legacy-control":
        for key in ("factory", "pixmap", "rawdict", "clipped_text", "release"):
            if engagement[key] == 0:
                failures.append(f"legacy-control/{corpus}: adapter {key} not engaged")
    if probed:
        _assert_counts(
            mode=mode, rotated=rotated, records=probe.records, failures=failures
        )
    capture_shares = [
        record["stage_ms"].get("capture", 0.0) / record["total_ms"]
        for record in probe.records[1:]
        if record["total_ms"] > 0
    ]
    return {
        "cold_ms": round(timings[0], 3),
        "warm": _percentiles(timings[1:]),
        "decomposition": _summarize_records(probe.records) if probed else None,
        "capture_share_median": (
            round(statistics.median(capture_shares), 6)
            if probed and capture_shares
            else None
        ),
        "_observations": observations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json-out",
        type=Path,
        default=ROOT / "benchmarks" / "p3d-interpretation-reuse.json",
    )
    args = parser.parse_args(argv)
    failures: list[str] = []
    results: dict[str, Any] = {}
    for corpus in ("dense", "small", "dense-rotated"):
        for mode in ("stage-a-shipped", "legacy-control"):
            for probed in (False, True):
                cell = run_scenario(
                    mode=mode, corpus=corpus, probed=probed, failures=failures
                )
                results.setdefault(corpus, {}).setdefault(mode, {})[
                    "probed" if probed else "clean"
                ] = cell

    for corpus, modes in results.items():
        for pass_name in ("clean", "probed"):
            shipped = modes["stage-a-shipped"][pass_name].pop("_observations")
            control = modes["legacy-control"][pass_name].pop("_observations")
            if shipped != control:
                failures.append(f"{corpus}/{pass_name}: shipped/control identity mismatch")

    capture_share = results["dense"]["stage-a-shipped"]["probed"][
        "capture_share_median"
    ]
    stage_b = "GO" if not failures and capture_share >= 0.20 else "NO-GO"
    report = {
        "harness": "p3d-interpretation-reuse",
        "pymupdf": fitz.__version__,
        "warm_keystrokes_per_cell": WARM_KEYSTROKES,
        "corpus": "synthetic deterministic; private real-PDF corpus NOT RUN",
        "acceptance": {"passed": not failures, "failures": failures},
        "decision": {
            "dense_unrotated_stage_a_capture_share_median": capture_share,
            "threshold": 0.20,
            "stage_b": stage_b,
        },
        "results": results,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = {
        "acceptance": report["acceptance"],
        "decision": report["decision"],
        "page_level_interpretations": {
            "stage_a_unrotated": 3,
            "stage_a_rotated": 4,
            "legacy_control": 6,
        },
    }
    print(json.dumps(summary, indent=2))
    print(f"report: {args.json_out}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

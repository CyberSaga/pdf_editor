"""GUI-path benchmark for the Tier 1 text-commit engine.

Runs the real Model/View/Controller stack offscreen (QT_QPA_PLATFORM=offscreen)
and drives edits through PDFController.edit_text — the exact slot the GUI
signal path invokes. Parameterized by --worktree so the identical script can
benchmark two worktrees comparably.

Usage:
  <venv python> bench_gui_tier1.py --worktree <root> --out <dir> [--smoke]
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wintypes
import json
import logging
import os
import re
import shutil
import statistics
import sys
import time
import traceback

# --------------------------------------------------------------------------
# CLI + environment (MUST happen before any project / Qt import)
# --------------------------------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument("--worktree", required=True)
parser.add_argument("--out", required=True)
parser.add_argument("--smoke", action="store_true")
ARGS = parser.parse_args()

WORKTREE = os.path.abspath(ARGS.worktree)
OUT_DIR = os.path.abspath(ARGS.out)
RENDERS_DIR = os.path.join(OUT_DIR, "renders")
WORK_DIR = os.path.join(OUT_DIR, "work")
os.makedirs(RENDERS_DIR, exist_ok=True)
os.makedirs(WORK_DIR, exist_ok=True)

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["TEXT_COMMIT_ENGINE"] = "tiered"
os.environ["TEXT_COMMIT_MAX_TIER"] = "1"

# Telemetry: enable only if this worktree's dto.py advertises a non-off value.
TELEMETRY_ENABLED = False
_dto_path = os.path.join(WORKTREE, "model", "text_commit", "dto.py")
if os.path.exists(_dto_path):
    with open(_dto_path, encoding="utf-8") as fh:
        _dto_src = fh.read()
    m = re.search(r"_TELEMETRY_VALUES\s*=\s*\(([^)]*)\)", _dto_src)
    if m:
        values = [v.strip().strip("'\"") for v in m.group(1).split(",") if v.strip()]
        non_off = [v for v in values if v and v != "off"]
        if non_off:
            os.environ["TEXT_COMMIT_TELEMETRY"] = non_off[0]
            TELEMETRY_ENABLED = True

sys.path.insert(0, WORKTREE)
os.chdir(WORKTREE)

# --------------------------------------------------------------------------
# Project imports + leak-proofing assertion
# --------------------------------------------------------------------------
import fitz  # noqa: E402

import model  # noqa: E402

_model_file = os.path.abspath(model.__file__)
assert _model_file.lower().startswith(WORKTREE.lower()), (
    f"model package leaked outside worktree: {_model_file!r} not under {WORKTREE!r}"
)

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import controller.pdf_controller as pdf_controller_mod  # noqa: E402
from controller.pdf_controller import PDFController  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import TextCommitSettings  # noqa: E402
from view.pdf_view import PDFView  # noqa: E402

for _mod_name in ("controller", "view", "fitz"):
    _mod = sys.modules.get(_mod_name)
    if _mod is not None and getattr(_mod, "__file__", None):
        # fitz lives in the venv; project packages must live in the worktree.
        if _mod_name != "fitz":
            assert os.path.abspath(_mod.__file__).lower().startswith(WORKTREE.lower()), (
                f"{_mod_name} leaked: {_mod.__file__}"
            )

# --------------------------------------------------------------------------
# Log capture (tier telemetry travels through model loggers)
# --------------------------------------------------------------------------
class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.records.append(
                f"{record.name}:{record.levelname}:{record.getMessage()}"
            )
        except Exception:
            pass


LOG_CAPTURE = _ListHandler()
for _lname in (
    "model.pdf_text_edit",
    "model.text_commit",
    "model.edit_commands",
    "controller.pdf_controller",
):
    _lg = logging.getLogger(_lname)
    _lg.setLevel(logging.DEBUG)
    _lg.addHandler(LOG_CAPTURE)

# Errors surfaced through blocking dialogs must not block offscreen runs:
# record them instead. This is an in-memory patch of the harness process only.
SHOWN_ERRORS: list[str] = []


def _record_error(parent, message: str) -> None:  # signature-compatible
    SHOWN_ERRORS.append(str(message))


pdf_controller_mod.show_error = _record_error

# --------------------------------------------------------------------------
# Windows memory via psapi
# --------------------------------------------------------------------------
class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
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
        ("PrivateUsage", ctypes.c_size_t),
    ]


_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_PSAPI = ctypes.WinDLL("psapi", use_last_error=True)
_KERNEL32.GetCurrentProcess.restype = wintypes.HANDLE
_PSAPI.GetProcessMemoryInfo.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
    wintypes.DWORD,
]
_PSAPI.GetProcessMemoryInfo.restype = wintypes.BOOL


def mem_info() -> dict:
    pmc = PROCESS_MEMORY_COUNTERS_EX()
    pmc.cb = ctypes.sizeof(pmc)
    ok = _PSAPI.GetProcessMemoryInfo(
        _KERNEL32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb
    )
    if not ok:
        return {"working_set": None, "peak_working_set": None}
    return {
        "working_set": int(pmc.WorkingSetSize),
        "peak_working_set": int(pmc.PeakWorkingSetSize),
    }


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
FIXTURES = [
    "1.pdf",
    "test-complexed-layout.pdf",
    "test-colored-background.pdf",
    "test-horizontal-texts.pdf",
    "test-large-file.pdf",
]
# The worktree's test_files may hold only a subset (untracked fixtures live in
# the main repo checkout). Fall back to the main repo's test_files so both
# worktree runs use byte-identical fixture sources.
MAIN_REPO_TEST_FILES = os.path.abspath(
    os.path.join(WORKTREE, "..", "..", "..", "test_files")
)


def locate_fixture(name: str) -> str | None:
    for base in (os.path.join(WORKTREE, "test_files"), MAIN_REPO_TEST_FILES):
        cand = os.path.join(base, name)
        if os.path.exists(cand):
            return cand
    return None


# --------------------------------------------------------------------------
# Deterministic targets + replacement text
# --------------------------------------------------------------------------
TARGET_PICKS = (0, 2, 5)  # indices among qualifying runs, fixed rule
MIN_SPAN_CHARS = 4
MAX_PROBE_PAGES = 15


def qualifying_runs(pdf_model, page_idx: int) -> list:
    """Horizontal block-manager runs with >= MIN_SPAN_CHARS chars, reading order.

    Uses the model's own TextBlockManager run index — the same span_id
    namespace the GUI's precise ("run") edit mode hands to the controller.
    """
    runs = []
    for span in pdf_model.block_manager.get_spans(page_idx):
        if span.rotation != 0:
            continue
        d = span.dir_vec
        if abs(d[0] - 1.0) > 0.01 or abs(d[1]) > 0.01:
            continue
        if len(span.text.strip()) >= MIN_SPAN_CHARS:
            runs.append(span)
    return runs


def discover_engine_eligible_targets(
    src: str, max_targets: int = 3, max_pages: int = 30
) -> list[tuple[int, str, tuple[float, float]]]:
    """Deterministic document-structure scan: (page_idx, text) pairs whose
    text equals the decoded bytes of a whole single-literal/hex ``Tj`` show
    operator — the only show-op shape the tiered engine's Tier 0/1 path
    accepts. Read-only fitz open of the pristine fixture; identical rule for
    every worktree.
    """
    from model.text_commit.inspect import replay_page

    found: list[tuple[int, str, tuple[float, float]]] = []
    doc = fitz.open(src)
    try:
        for idx in range(min(len(doc), max_pages)):
            page = doc[idx]
            try:
                replay = replay_page(doc, page)
            except Exception:
                continue
            singles: set[str] = set()
            for s in replay.shows:
                # Whole single-literal/hex Tj with a clean text state — the
                # structural shape Tier 0/1 can even consider. All checks are
                # document properties, not engine calls.
                if (
                    s.operator == "Tj"
                    and s.string_kind in ("literal", "hex")
                    and s.hscale == 100.0
                    and s.render_mode == 0
                    and s.rise == 0.0
                    and getattr(s, "mc_depth", 0) == 0
                ):
                    try:
                        singles.add(s.decoded_bytes.decode("latin-1"))
                    except UnicodeDecodeError:
                        pass
            if not singles:
                continue
            data = page.get_text("dict")
            for block in data.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    d = line.get("dir", (1, 0))
                    if abs(d[0] - 1.0) > 0.01 or abs(d[1]) > 0.01:
                        continue
                    for span in line.get("spans", []):
                        text = span.get("text", "")
                        if (
                            len(text.strip()) >= MIN_SPAN_CHARS
                            and text == text.strip()  # run text is stripped
                            and text in singles
                        ):
                            origin = tuple(span.get("origin", span["bbox"][:2]))
                            found.append((idx, text, origin))
                            if len(found) >= max_targets:
                                return found
    finally:
        doc.close()
    return found


def first_text_page(pdf_model) -> tuple[int, int] | None:
    """(page_idx, qualifying_run_count) of first text-bearing page."""
    n_pages = len(pdf_model.doc) if pdf_model.doc else 0
    for idx in range(min(n_pages, MAX_PROBE_PAGES)):
        pdf_model.ensure_page_index_built(idx + 1)
        n = len(qualifying_runs(pdf_model, idx))
        if n > 0:
            return idx, n
    return None


_ROT = {}
for _seq in ("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "0123456789"):
    for _i, _c in enumerate(_seq):
        _ROT[_c] = _seq[(_i + 1) % len(_seq)]


def make_replacement(text: str, scenario: str) -> str:
    rotated = "".join(_ROT.get(c, c) for c in text)
    if rotated == text:
        rotated = text[::-1] if text[::-1] != text else text + "X"
    if scenario == "same":
        return rotated
    if scenario == "longer":
        extra = max(1, round(len(text) * 0.4))
        return (rotated + rotated)[: len(text) + extra]
    if scenario == "shorter":
        keep = max(2, len(text) - max(1, round(len(text) * 0.4)))
        return rotated[:keep]
    raise ValueError(scenario)


# --------------------------------------------------------------------------
# Pixel diff
# --------------------------------------------------------------------------
try:
    import numpy as _np
except ImportError:
    _np = None

DPI = 144
ZOOM = DPI / 72.0


def render_page(doc: fitz.Document, page_idx: int) -> fitz.Pixmap:
    return doc[page_idx].get_pixmap(dpi=DPI, alpha=False)


def rect_to_px(rect: fitz.Rect, page_rect: fitz.Rect, w: int, h: int, pad_pt: float):
    r = fitz.Rect(rect) + (-pad_pt, -pad_pt, pad_pt, pad_pt)
    r &= page_rect
    x0 = max(0, int((r.x0 - page_rect.x0) * ZOOM))
    y0 = max(0, int((r.y0 - page_rect.y0) * ZOOM))
    x1 = min(w, int((r.x1 - page_rect.x0) * ZOOM + 0.999))
    y1 = min(h, int((r.y1 - page_rect.y0) * ZOOM + 0.999))
    return x0, y0, x1, y1


def pixel_diff(pa: fitz.Pixmap, pb: fitz.Pixmap, rect_px) -> dict:
    if (pa.width, pa.height, pa.n) != (pb.width, pb.height, pb.n):
        return {
            "note": "pixmap_dim_mismatch",
            "outside_diff_ratio": None,
            "inside_changed": None,
        }
    w, h, n = pa.width, pa.height, pa.n
    x0, y0, x1, y1 = rect_px
    a, b = pa.samples, pb.samples
    stride_a, stride_b = pa.stride, pb.stride
    if _np is not None:
        arr_a = _np.frombuffer(a, dtype=_np.uint8).reshape(h, stride_a)[:, : w * n]
        arr_b = _np.frombuffer(b, dtype=_np.uint8).reshape(h, stride_b)[:, : w * n]
        mask = (arr_a != arr_b).reshape(h, w, n).any(axis=2)
        inside = mask[y0:y1, x0:x1]
        inside_changed = bool(inside.any())
        changed_total = int(mask.sum())
        changed_inside = int(inside.sum())
        outside_total = w * h - (y1 - y0) * (x1 - x0)
        changed_outside = changed_total - changed_inside
    else:
        changed_outside = 0
        inside_changed = False
        outside_total = w * h - (y1 - y0) * (x1 - x0)
        for y in range(h):
            ra = a[y * stride_a : y * stride_a + w * n]
            rb = b[y * stride_b : y * stride_b + w * n]
            if ra == rb:
                continue
            in_row = y0 <= y < y1
            for x in range(w):
                off = x * n
                if ra[off : off + n] != rb[off : off + n]:
                    if in_row and x0 <= x < x1:
                        inside_changed = True
                    else:
                        changed_outside += 1
    return {
        "outside_diff_ratio": (changed_outside / outside_total) if outside_total else 0.0,
        "outside_changed_px": changed_outside,
        "outside_total_px": outside_total,
        "inside_changed": inside_changed,
    }


# --------------------------------------------------------------------------
# GUI stack (replicates main.py attach_and_activate_controller wiring)
# --------------------------------------------------------------------------
def build_gui():
    app = QApplication.instance() or QApplication([sys.argv[0]])
    gui_mode = "real-view-offscreen"
    try:
        view = PDFView(defer_heavy_panels=False)
        view.apply_initial_theme()
    except Exception:
        traceback.print_exc()

        class _StubView:
            controller = None

            def __getattr__(self, name):
                def _noop(*a, **k):
                    return None

                return _noop

        view = _StubView()
        gui_mode = "stub-view"
    pdf_model = PDFModel(text_commit_settings=TextCommitSettings.from_env(os.environ))
    ctrl = PDFController(pdf_model, view)
    view.controller = ctrl
    ctrl.activate()
    # Bypass the modal close-confirmation dialog (offscreen run would hang).
    ctrl._confirm_close_session = lambda _sid: True
    if gui_mode == "real-view-offscreen":
        try:
            view.show()
            view.ensure_heavy_panels_initialized()
        except Exception:
            traceback.print_exc()
    return app, view, ctrl, pdf_model, gui_mode


def spin(app: QApplication, ms: int = 60) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    app.processEvents()


def close_all_sessions(ctrl, pdf_model, app) -> None:
    for _ in range(20):
        sid = pdf_model.get_active_session_id()
        if not sid:
            break
        idx = None
        for i in range(50):
            if pdf_model.get_session_id_by_index(i) == sid:
                idx = i
                break
        if idx is None:
            pdf_model.close_session(sid)
        else:
            ctrl.on_tab_close_requested(idx)
        app.processEvents()
    spin(app, 30)


def probe_fixture(app, ctrl, pdf_model, src: str, fixture_name: str):
    """Open a fresh copy through the controller; return (page_idx, run_count)
    for the first text-bearing page, or an error string."""
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", os.path.splitext(fixture_name)[0])
    work_path = os.path.join(WORK_DIR, f"{stem}__probe.pdf")
    shutil.copyfile(src, work_path)
    try:
        ctrl.open_pdf(work_path)
        app.processEvents()
        if not pdf_model.doc:
            return "open_failed"
        ftp = first_text_page(pdf_model)
        if ftp is None:
            return "no_text_runs"
        return ftp
    except Exception as e:
        return f"probe_failed: {type(e).__name__}: {e}"
    finally:
        try:
            close_all_sessions(ctrl, pdf_model, app)
        except Exception:
            pass
        try:
            os.remove(work_path)
        except OSError:
            pass


# --------------------------------------------------------------------------
# Outcome extraction
# --------------------------------------------------------------------------
def outcome_record(pdf_model) -> dict:
    o = getattr(pdf_model, "last_commit_outcome", None)
    if o is None:
        return {"present": False, "tier": None, "status": None, "fallback_chain": []}
    tier = getattr(o, "tier", None)
    return {
        "present": True,
        "status": getattr(getattr(o, "status", None), "value", str(getattr(o, "status", None))),
        "tier": int(tier) if tier is not None else None,
        "fallback_chain": list(getattr(o, "fallback_chain", ()) or ()),
        "degraded_reason": getattr(o, "degraded_reason", None),
        "warnings": list(getattr(o, "warnings", ()) or ()),
    }


# --------------------------------------------------------------------------
# One edit run
# --------------------------------------------------------------------------
def run_one_edit(
    app,
    ctrl,
    pdf_model,
    fixture_src: str,
    fixture_name: str,
    target_ordinal: int,
    span_index: int,
    scenario: str,
    page_idx: int,
    work_tag: str,
    save_renders: bool = True,
    span_text: str | None = None,
    span_origin: tuple[float, float] | None = None,
) -> dict:
    rec: dict = {
        "fixture": fixture_name,
        "target": target_ordinal,
        "span_index": span_index,
        "scenario": scenario,
        "page": page_idx + 1,
    }
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", os.path.splitext(fixture_name)[0])
    work_path = os.path.join(WORK_DIR, f"{stem}__{work_tag}.pdf")
    shutil.copyfile(fixture_src, work_path)
    SHOWN_ERRORS.clear()
    log_start = len(LOG_CAPTURE.records)
    try:
        ctrl.open_pdf(work_path)
        app.processEvents()
        if not pdf_model.doc:
            rec["error"] = "open_failed"
            return rec
        page_num = page_idx + 1
        pdf_model.ensure_page_index_built(page_num)
        runs = qualifying_runs(pdf_model, page_idx)
        if span_text is not None:
            matches = [r for r in runs if r.text.strip() == span_text.strip()]
            if not matches:
                rec["error"] = "discovered_span_not_found"
                return rec
            if span_origin is not None:
                matches.sort(
                    key=lambda r: (r.origin.x - span_origin[0]) ** 2
                    + (r.origin.y - span_origin[1]) ** 2
                )
            span = matches[0]
            rec["discovered"] = True
        elif span_index >= len(runs):
            rec["error"] = "span_index_out_of_range"
            return rec
        else:
            span = runs[span_index]
        orig_text = span.text
        new_text = make_replacement(orig_text, scenario)
        rect = fitz.Rect(span.bbox)
        rec["orig_len"] = len(orig_text)
        rec["new_len"] = len(new_text)
        rec["span_id"] = span.span_id
        rec["font"] = span.font

        pix_before = render_page(pdf_model.doc, page_idx)
        render_dir = os.path.join(RENDERS_DIR, stem)
        os.makedirs(render_dir, exist_ok=True)
        if save_renders:
            pix_before.save(
                os.path.join(render_dir, f"t{target_ordinal}_{scenario}_before.png")
            )

        ws_before = mem_info()
        t0 = time.perf_counter()
        exc: dict | None = None
        try:
            ctrl.edit_text(
                page_num,
                rect,
                new_text,
                font=span.font,
                size=float(span.size),
                color=tuple(span.color),
                original_text=orig_text,
                target_span_id=span.span_id,
                target_mode="run",
            )
        except Exception as e:  # controller swallows most; keep the honest path
            exc = {"type": type(e).__name__, "message": str(e)[:400]}
        app.processEvents()
        spin(app, 200)  # let viewport-anchor timers fire like the real GUI
        latency_ms = (time.perf_counter() - t0) * 1000.0
        ws_after = mem_info()

        rec["latency_ms"] = round(latency_ms, 2)
        rec["exception"] = exc
        rec["shown_errors"] = list(SHOWN_ERRORS)
        rec["ws_before"] = ws_before["working_set"]
        rec["ws_after"] = ws_after["working_set"]
        rec["outcome"] = outcome_record(pdf_model)
        tier = rec["outcome"]["tier"]
        rec["tiered_engine_handled"] = tier in (0, 1)
        rec["tier1_engaged"] = tier == 1
        rec["log_lines"] = [
            ln
            for ln in LOG_CAPTURE.records[log_start:]
            if "text_commit" in ln or "edit_transaction" in ln or "ERROR" in ln
        ][:20]

        pix_after = render_page(pdf_model.doc, page_idx)
        if save_renders:
            pix_after.save(
                os.path.join(render_dir, f"t{target_ordinal}_{scenario}_after.png")
            )
        page_rect = pdf_model.doc[page_idx].rect
        rect_px = rect_to_px(rect, page_rect, pix_before.width, pix_before.height, 3.0)
        rec["fidelity"] = pixel_diff(pix_before, pix_after, rect_px)
        pix_before = None
        pix_after = None
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["traceback"] = traceback.format_exc()[-1500:]
    finally:
        try:
            close_all_sessions(ctrl, pdf_model, app)
        except Exception as e:
            rec["close_error"] = f"{type(e).__name__}: {e}"
        try:
            os.remove(work_path)
        except OSError:
            pass
    return rec


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> int:
    app, view, ctrl, pdf_model, gui_mode = build_gui()
    spin(app, 100)

    fixture_list = ["1.pdf"] if ARGS.smoke else FIXTURES
    edits: list[dict] = []
    fixtures_meta: list[dict] = []

    for fixture_name in fixture_list:
        src = locate_fixture(fixture_name)
        meta: dict = {"fixture": fixture_name, "source": src}
        if src is None:
            meta["skipped"] = "not_found"
            fixtures_meta.append(meta)
            continue
        # Probe through the real stack (fresh copy; never edits the original).
        ftp = probe_fixture(app, ctrl, pdf_model, src, fixture_name)
        if isinstance(ftp, str):
            meta["skipped"] = ftp
            fixtures_meta.append(meta)
            continue
        page_idx, span_count = ftp
        picks = [i for i in TARGET_PICKS if i < span_count]
        if ARGS.smoke:
            picks = picks[:1]
        if fixture_name == "test-large-file.pdf":
            picks = picks[:1]
        meta.update({"page_idx": page_idx, "qualifying_runs": span_count, "picks": picks})
        fixtures_meta.append(meta)

        for ordinal, span_index in enumerate(picks):
            for scenario in ("same", "longer", "shorter"):
                tag = f"t{ordinal}_{scenario}"
                rec = run_one_edit(
                    app, ctrl, pdf_model, src, fixture_name,
                    ordinal, span_index, scenario, page_idx, tag,
                )
                edits.append(rec)
                print(
                    f"[edit] {fixture_name} t{ordinal}(span#{span_index}) {scenario}: "
                    f"tier={rec.get('outcome', {}).get('tier')} "
                    f"lat={rec.get('latency_ms')}ms "
                    f"err={rec.get('error') or (rec.get('exception') or {}).get('type')}",
                    flush=True,
                )

        # Discovery pass: deterministic scan for spans whose text equals a
        # whole single-literal-Tj show op — the only shape Tier 0/1 accepts.
        # Ensures the tiered engine is exercised where the document allows it.
        if not ARGS.smoke:
            try:
                discovered = discover_engine_eligible_targets(src)
            except Exception as e:
                discovered = []
                meta["discovery_error"] = f"{type(e).__name__}: {e}"
            meta["discovered_targets"] = [
                {"page_idx": p, "text": t, "origin": list(o)}
                for p, t, o in discovered
            ]
            for d_ord, (d_page_idx, d_text, d_origin) in enumerate(discovered):
                ordinal = 100 + d_ord  # distinct render/target namespace
                for scenario in ("same", "longer", "shorter"):
                    tag = f"d{d_ord}_{scenario}"
                    rec = run_one_edit(
                        app, ctrl, pdf_model, src, fixture_name,
                        ordinal, -1, scenario, d_page_idx, tag,
                        span_text=d_text,
                        span_origin=d_origin,
                    )
                    edits.append(rec)
                    print(
                        f"[edit] {fixture_name} d{d_ord}({d_text[:20]!r} "
                        f"p{d_page_idx + 1}) {scenario}: "
                        f"tier={rec.get('outcome', {}).get('tier')} "
                        f"lat={rec.get('latency_ms')}ms "
                        f"err={rec.get('error') or (rec.get('exception') or {}).get('type')}",
                        flush=True,
                    )

    # Stability / leak loop: 1.pdf same-length edit x10 on fresh copies.
    loop_records: list[dict] = []
    src_1 = locate_fixture("1.pdf")
    if src_1 and not ARGS.smoke:
        ftp = probe_fixture(app, ctrl, pdf_model, src_1, "1.pdf")
        if not isinstance(ftp, str):
            page_idx = ftp[0]
            for it in range(10):
                rec = run_one_edit(
                    app, ctrl, pdf_model, src_1, "1.pdf",
                    0, TARGET_PICKS[0], "same", page_idx,
                    f"loop{it}", save_renders=False,
                )
                loop_records.append(
                    {
                        "iter": it,
                        "latency_ms": rec.get("latency_ms"),
                        "ws_before": rec.get("ws_before"),
                        "ws_after": rec.get("ws_after"),
                        "tier": rec.get("outcome", {}).get("tier"),
                        "error": rec.get("error")
                        or (rec.get("exception") or {}).get("type"),
                    }
                )
                print(f"[loop] iter {it}: ws_after={rec.get('ws_after')}", flush=True)

    # ---------------- aggregates ----------------
    latencies = [e["latency_ms"] for e in edits if e.get("latency_ms") is not None]
    lat_sorted = sorted(latencies)

    def pct(p: float):
        if not lat_sorted:
            return None
        k = min(len(lat_sorted) - 1, max(0, round(p * (len(lat_sorted) - 1))))
        return lat_sorted[k]

    tier_funnel = {"tier0": 0, "tier1": 0, "tier2_legacy_fallback": 0, "no_outcome": 0}
    reject_reasons: dict[str, int] = {}
    for e in edits:
        t = e.get("outcome", {}).get("tier")
        if t == 0:
            tier_funnel["tier0"] += 1
        elif t == 1:
            tier_funnel["tier1"] += 1
        elif t == 2:
            tier_funnel["tier2_legacy_fallback"] += 1
            fc = e.get("outcome", {}).get("fallback_chain") or []
            key = fc[0] if fc else "unknown"
            reject_reasons[key] = reject_reasons.get(key, 0) + 1
        else:
            tier_funnel["no_outcome"] += 1

    skipped_targets = [
        e for e in edits if e.get("error") == "discovered_span_not_found"
    ]
    errors = [
        e for e in edits
        if (
            (e.get("error") and e.get("error") != "discovered_span_not_found")
            or e.get("exception")
            or e.get("shown_errors")
        )
    ]
    out_ratios = [
        e["fidelity"]["outside_diff_ratio"]
        for e in edits
        if e.get("fidelity", {}).get("outside_diff_ratio") is not None
    ]
    ws_growth = None
    if len(loop_records) >= 2:
        first = loop_records[0].get("ws_after")
        last = loop_records[-1].get("ws_after")
        if first and last:
            ws_growth = last - first

    final_mem = mem_info()
    result = {
        "worktree": WORKTREE,
        "gui_mode": gui_mode,
        "telemetry_enabled": TELEMETRY_ENABLED,
        "env": {
            k: os.environ.get(k)
            for k in (
                "TEXT_COMMIT_ENGINE",
                "TEXT_COMMIT_MAX_TIER",
                "TEXT_COMMIT_TELEMETRY",
                "QT_QPA_PLATFORM",
            )
        },
        "numpy_used": _np is not None,
        "fixtures": fixtures_meta,
        "edits": edits,
        "leak_loop": loop_records,
        "aggregates": {
            "total_edits": len(edits),
            "p50_latency_ms": pct(0.50),
            "p95_latency_ms": pct(0.95),
            "error_count": len(errors),
            "skipped_target_count": len(skipped_targets),
            "tier_funnel": tier_funnel,
            "tier0_reject_reasons": reject_reasons,
            "peak_working_set": final_mem["peak_working_set"],
            "ws_growth_over_loop": ws_growth,
            "mean_outside_diff_ratio": (
                statistics.mean(out_ratios) if out_ratios else None
            ),
            "max_outside_diff_ratio": max(out_ratios) if out_ratios else None,
        },
    }

    json_path = os.path.join(OUT_DIR, "result.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, ensure_ascii=False)

    agg = result["aggregates"]
    print("---- summary ----")
    print(f"gui_mode={gui_mode} edits={agg['total_edits']} errors={agg['error_count']}")
    print(f"p50={agg['p50_latency_ms']}ms p95={agg['p95_latency_ms']}ms")
    print(f"tier_funnel={agg['tier_funnel']}")
    print(f"peak_ws={agg['peak_working_set']} ws_growth_loop={agg['ws_growth_over_loop']}")
    print(
        f"outside_diff mean={agg['mean_outside_diff_ratio']} "
        f"max={agg['max_outside_diff_ratio']}"
    )
    print(f"json={json_path}")

    try:
        close_all_sessions(ctrl, pdf_model, app)
        pdf_model.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

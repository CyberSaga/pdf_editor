"""
benchmark_ui_open_render.py -- UI-path open/page-change responsiveness benchmark
===========================================================================
Measures the controller/view path in offscreen mode:
- startup to placeholder geometry ready
- initial page low-quality ready
- initial page high-quality ready
- far-page jump high-quality ready

Run:
  python test_scripts/benchmark_ui_open_render.py --path test_files/2024_ASHRAE_content.pdf
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
from pathlib import Path

if sys.platform == "win32" and __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _wait_for_quality(startup: dict, session_id: str, page_idx: int, quality: str, timeout_s: float) -> float:
    controller = startup["controller"]
    app = startup["app"]
    deadline = time.perf_counter() + timeout_s
    start = time.perf_counter()
    page_quality = controller._page_render_quality_by_session.get(session_id, {}).get(page_idx)
    if page_quality == quality:
        return 0.0
    while time.perf_counter() < deadline:
        app.processEvents()
        page_quality = controller._page_render_quality_by_session.get(session_id, {}).get(page_idx)
        if page_quality == quality:
            return (time.perf_counter() - start) * 1000.0
        time.sleep(0.005)
    raise TimeoutError(f"Timed out waiting for page {page_idx + 1} quality={quality}")


def _cleanup_startup(startup: dict) -> None:
    startup["view"].close()
    model = startup.get("model")
    if model is not None:
        model.close()
    startup["app"].quit()


def main() -> int:
    import main as main_module

    parser = argparse.ArgumentParser(description="UI-path open/page-change responsiveness benchmark")
    parser.add_argument("--path", required=True, help="PDF path to open")
    parser.add_argument("--target-page", type=int, default=0, help="1-based target page for page-jump timing; 0 means midpoint")
    parser.add_argument("--timeout", type=float, default=15.0, help="Timeout in seconds for each wait")
    args = parser.parse_args()

    pdf_path = Path(args.path)
    if not pdf_path.is_file():
        print(f"Missing PDF: {pdf_path}")
        return 1

    t0 = time.perf_counter()
    startup = main_module.run(argv=[str(pdf_path)], start_event_loop=False)
    startup_ms = (time.perf_counter() - t0) * 1000.0

    try:
        controller = startup["controller"]
        view = startup["view"]
        model = startup["model"]
        session_id = model.get_active_session_id()
        if session_id is None or not model.doc:
            raise RuntimeError("No active session after startup")

        page_count = len(model.doc)
        initial_page_idx = max(0, view.current_page)
        placeholders_ready = (
            view.total_pages == page_count
            and len(view.page_items) == page_count
            and len(view.page_y_positions) == page_count
            and len(view.page_heights) == page_count
        )
        if not placeholders_ready:
            raise RuntimeError("Placeholder geometry not ready after startup")

        low_ms = _wait_for_quality(startup, session_id, initial_page_idx, "low", args.timeout)
        high_ms = _wait_for_quality(startup, session_id, initial_page_idx, "high", args.timeout)

        target_page = args.target_page if args.target_page > 0 else max(1, page_count // 2)
        target_page = max(1, min(target_page, page_count))
        target_idx = target_page - 1

        t_jump = time.perf_counter()
        controller.change_page(target_idx)
        jump_high_ms = _wait_for_quality(startup, session_id, target_idx, "high", args.timeout)
        jump_total_ms = (time.perf_counter() - t_jump) * 1000.0

        print(f"file={pdf_path.name}")
        print(f"pages={page_count}")
        print(f"startup_to_placeholders_ms={startup_ms:.1f}")
        print(f"initial_low_ready_ms={low_ms:.1f}")
        print(f"initial_high_ready_ms={high_ms:.1f}")
        print(f"jump_target_page={target_page}")
        print(f"jump_high_ready_ms={jump_high_ms:.1f}")
        print(f"jump_total_elapsed_ms={jump_total_ms:.1f}")
        return 0
    finally:
        _cleanup_startup(startup)


if __name__ == "__main__":
    raise SystemExit(main())

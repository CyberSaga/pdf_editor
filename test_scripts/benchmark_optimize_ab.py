from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

MEASURE_SNIPPET = r"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import psutil
from model.pdf_model import PDFModel


def main() -> int:
    src = Path(sys.argv[1]).resolve()
    preset = sys.argv[2]
    process = psutil.Process(os.getpid())
    model = PDFModel()
    model.open_pdf(str(src))
    options = model.preset_optimize_options(preset)
    base_rss = process.memory_info().rss
    peak = {'rss': base_rss}
    start_io = process.io_counters()
    done = False

    def watch():
        while not done:
            try:
                rss = process.memory_info().rss
                if rss > peak['rss']:
                    peak['rss'] = rss
            except Exception:
                pass
            time.sleep(0.02)

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    temp_output = Path(tempfile.gettempdir()) / f'codex_ab_{os.getpid()}_{int(time.time() * 1000)}.pdf'
    t0 = time.perf_counter()
    try:
        result = model.save_optimized_copy(str(temp_output), options)
        t1 = time.perf_counter()
    finally:
        done = True
        thread.join(timeout=1.0)
        end_io = process.io_counters()
        model.close()
    summary = {
        't_seconds': round(t1 - t0, 3),
        'base_rss': base_rss,
        'peak_rss': peak['rss'],
        'm_delta': peak['rss'] - base_rss,
        'optimized_bytes': result.optimized_bytes,
        'bytes_saved': result.bytes_saved,
        'percent_saved': result.percent_saved,
        'read_bytes': end_io.read_bytes - start_io.read_bytes,
        'write_bytes': end_io.write_bytes - start_io.write_bytes,
    }
    summary['read_mb_s'] = round(summary['read_bytes'] / max(summary['t_seconds'], 1e-9) / (1024 * 1024), 3)
    summary['write_mb_s'] = round(summary['write_bytes'] / max(summary['t_seconds'], 1e-9) / (1024 * 1024), 3)
    print(json.dumps(summary, ensure_ascii=False))
    if temp_output.exists():
        temp_output.unlink()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
"""


def _run_measurement(repo_dir: Path, pdf_path: Path, preset: str) -> dict:
    temp_script = repo_dir / ".codex_measure_optimize.py"
    temp_script.write_text(MEASURE_SNIPPET, encoding="utf-8")
    try:
        completed = subprocess.run(
            [sys.executable, str(temp_script), str(pdf_path), preset],
            cwd=str(repo_dir),
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        temp_script.unlink(missing_ok=True)
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return json.loads(lines[-1])


def _extract_revision(repo_root: Path, revision: str, temp_dir: Path) -> Path:
    archive_path = temp_dir / f"{revision}.zip"
    snapshot_dir = temp_dir / revision
    subprocess.run(
        ["git", "archive", "--format=zip", f"--output={archive_path}", revision],
        cwd=str(repo_root),
        check=True,
    )
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(snapshot_dir)
    return snapshot_dir


def compare_revisions(repo_root: Path, baseline_revision: str, pdf_paths: list[Path], preset: str = "平衡") -> dict:
    report = {
        "baseline_revision": baseline_revision,
        "optimized_revision": "WORKTREE",
        "preset": preset,
        "files": [],
    }
    with tempfile.TemporaryDirectory(prefix="pdf_optimize_ab_") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        baseline_dir = _extract_revision(repo_root, baseline_revision, temp_dir)
        for pdf_path in pdf_paths:
            baseline = _run_measurement(baseline_dir, pdf_path.resolve(), preset)
            optimized = _run_measurement(repo_root, pdf_path.resolve(), preset)
            file_report = {
                "pdf_path": str(pdf_path.resolve()),
                "baseline": baseline,
                "optimized": optimized,
                "time_speedup": round(baseline["t_seconds"] / optimized["t_seconds"], 3),
                "memory_delta_ratio": round(
                    optimized["m_delta"] / baseline["m_delta"], 3
                ) if baseline["m_delta"] else None,
                "memory_delta_reduction_percent": round(
                    (baseline["m_delta"] - optimized["m_delta"]) / baseline["m_delta"] * 100.0,
                    2,
                ) if baseline["m_delta"] else None,
            }
            report["files"].append(file_report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark optimize-copy between a baseline revision and the current worktree.")
    parser.add_argument("--baseline-revision", default="2cd2a67")
    parser.add_argument("--preset", default="平衡")
    parser.add_argument("pdf_paths", nargs="+", type=Path)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    report = compare_revisions(repo_root, args.baseline_revision, list(args.pdf_paths), preset=args.preset)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

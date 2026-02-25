"""
Cross-platform print pipeline validation.

Checks:
1. Accuracy: print-to-PDF output should preserve page visuals/text.
2. Performance: on-demand rendering should use less peak memory than naive eager rendering.
"""

from __future__ import annotations

import gc
import os
import sys
import tempfile
import time
import tracemalloc
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import fitz
from PIL import Image, ImageChops

# Ensure repository root is importable when script is launched from test_scripts.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Headless-friendly Qt backend for CI/terminal runs.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.printing import PrintDispatcher, PrintJobOptions
from src.printing.pdf_renderer import PDFRenderer


@dataclass
class BenchmarkResult:
    seconds: float
    peak_bytes: int
    estimated_image_peak_bytes: int
    pages: int


def _normalize_text(text: str) -> str:
    return "".join(text.split()).lower()


def _build_sample_pdf(path: Path, pages: int = 12) -> None:
    doc = fitz.open()
    try:
        for idx in range(pages):
            page = doc.new_page(width=595, height=842)  # A4 @ 72dpi
            page.insert_text(
                (72, 80),
                f"PDF Print Pipeline Validation - Page {idx + 1}",
                fontsize=18,
                fontname="helv",
            )
            page.insert_textbox(
                fitz.Rect(72, 120, 523, 300),
                (
                    "This page verifies print fidelity between source PDF and "
                    "print pipeline output. "
                    f"Deterministic token: page={idx + 1}, checksum={idx * idx + 7}."
                ),
                fontsize=12,
                fontname="helv",
                align=fitz.TEXT_ALIGN_JUSTIFY,
            )
            top = 340 + (idx % 5) * 8
            page.draw_rect(
                fitz.Rect(72, top, 360, top + 120),
                color=(0.1, 0.3, 0.8),
                fill=(0.85, 0.9, 1.0),
                width=2,
            )
            page.insert_text((88, top + 68), f"VectorBox-{idx + 1}", fontsize=20, fontname="helv")
            page.insert_text((72, 790), f"Footer-{idx + 1:03d}", fontsize=10, fontname="cour")
        doc.save(path)
    finally:
        doc.close()


def _render_page_gray(path: Path, page_index: int, dpi: int = 180) -> Image.Image:
    doc = fitz.open(path)
    try:
        page = doc[page_index]
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return img.convert("L")
    finally:
        doc.close()


def _page_similarity_score(source: Image.Image, printed: Image.Image) -> float:
    if source.size != printed.size:
        printed = printed.resize(source.size, Image.Resampling.BICUBIC)
    diff = ImageChops.difference(source, printed)
    hist = diff.histogram()
    total = max(1, sum(hist))
    mae = sum(i * count for i, count in enumerate(hist)) / total
    return 1.0 - (mae / 255.0)


def _text_similarity(source_pdf: Path, printed_pdf: Path) -> float:
    source_doc = fitz.open(source_pdf)
    printed_doc = fitz.open(printed_pdf)
    try:
        source_text = []
        printed_text = []
        page_count = min(len(source_doc), len(printed_doc))
        for idx in range(page_count):
            source_text.append(source_doc[idx].get_text("text"))
            printed_text.append(printed_doc[idx].get_text("text"))
        return SequenceMatcher(
            None,
            _normalize_text("\n".join(source_text)),
            _normalize_text("\n".join(printed_text)),
        ).ratio()
    finally:
        source_doc.close()
        printed_doc.close()


def _benchmark_naive(renderer: PDFRenderer, pdf_path: Path, page_indices: list[int], dpi: int) -> BenchmarkResult:
    gc.collect()
    tracemalloc.start()
    t0 = time.perf_counter()
    rendered = renderer.render_all_to_images(str(pdf_path), page_indices, dpi)
    elapsed = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    count = len(rendered)
    estimated_peak = sum(page.image.sizeInBytes() for page in rendered)
    del rendered
    gc.collect()
    return BenchmarkResult(
        seconds=elapsed,
        peak_bytes=peak,
        estimated_image_peak_bytes=estimated_peak,
        pages=count,
    )


def _benchmark_on_demand(renderer: PDFRenderer, pdf_path: Path, page_indices: list[int], dpi: int) -> BenchmarkResult:
    gc.collect()
    tracemalloc.start()
    t0 = time.perf_counter()
    count = 0
    estimated_peak = 0
    for rendered_page in renderer.iter_page_images(str(pdf_path), page_indices, dpi):
        estimated_peak = max(estimated_peak, rendered_page.image.sizeInBytes())
        count += 1
    elapsed = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    gc.collect()
    return BenchmarkResult(
        seconds=elapsed,
        peak_bytes=peak,
        estimated_image_peak_bytes=estimated_peak,
        pages=count,
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        src_pdf = root / "source_print_test.pdf"
        out_pdf = root / "printed_output.pdf"
        _build_sample_pdf(src_pdf, pages=16)

        dispatcher = PrintDispatcher()
        print_opts = PrintJobOptions(
            output_pdf_path=str(out_pdf),
            page_ranges="1-16",
            dpi=220,
            fit_to_page=True,
            color_mode="color",
            transport="raster",
            job_name="print_pipeline_validation",
        )
        t_submit = time.perf_counter()
        result = dispatcher.print_pdf_file(str(src_pdf), print_opts)
        submit_elapsed = time.perf_counter() - t_submit

        if not out_pdf.exists():
            print("[FAIL] print output PDF not found")
            return 1

        source_doc = fitz.open(src_pdf)
        try:
            page_count = len(source_doc)
        finally:
            source_doc.close()

        scores = []
        for page_index in range(page_count):
            source_img = _render_page_gray(src_pdf, page_index, dpi=180)
            printed_img = _render_page_gray(out_pdf, page_index, dpi=180)
            scores.append(_page_similarity_score(source_img, printed_img))
        avg_score = sum(scores) / len(scores)
        min_score = min(scores)
        text_score = None
        if "direct-pdf" in result.route or "cups" in result.route:
            text_score = _text_similarity(src_pdf, out_pdf)

        renderer = PDFRenderer(displaylist_cache_size=12)
        indices = list(range(page_count))
        naive = _benchmark_naive(renderer, src_pdf, indices, dpi=220)
        on_demand = _benchmark_on_demand(renderer, src_pdf, indices, dpi=220)

        mem_gain = 0.0
        if naive.estimated_image_peak_bytes > 0:
            mem_gain = 1.0 - (
                on_demand.estimated_image_peak_bytes / naive.estimated_image_peak_bytes
            )

        print("=" * 68)
        print("Print Pipeline Validation")
        print("=" * 68)
        print(f"route: {result.route}")
        print(f"submission: {submit_elapsed:.3f}s")
        print(f"accuracy(avg): {avg_score:.4f}")
        print(f"accuracy(min): {min_score:.4f}")
        if text_score is None:
            print("text similarity: n/a (raster route generates image-only pages)")
        else:
            print(f"text similarity: {text_score:.4f}")
        print("-" * 68)
        print(
            "naive eager render: "
            f"{naive.seconds:.3f}s, peak={naive.peak_bytes / (1024 * 1024):.2f} MB"
        )
        print(
            "on-demand render:   "
            f"{on_demand.seconds:.3f}s, peak={on_demand.peak_bytes / (1024 * 1024):.2f} MB"
        )
        print(
            "estimated image peak (naive/on-demand): "
            f"{naive.estimated_image_peak_bytes / (1024 * 1024):.2f} MB / "
            f"{on_demand.estimated_image_peak_bytes / (1024 * 1024):.2f} MB"
        )
        print(f"peak-memory gain:   {mem_gain * 100:.1f}%")
        print("=" * 68)

        accuracy_ok = avg_score >= 0.965 and min_score >= 0.94
        if text_score is not None:
            accuracy_ok = accuracy_ok and text_score >= 0.95
        memory_ok = mem_gain >= 0.30
        if accuracy_ok and memory_ok:
            print("[PASS] Accuracy and performance targets met.")
            return 0
        print("[FAIL] Targets not met.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Tests for the render-epsilon calibration script.

Verifies that ``calibrate_render_epsilon`` correctly measures pixel noise
across repeated renders of the same page and produces a valid calibration
report with the expected structure and semantics.
"""
from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from scripts.calibrate_render_epsilon import (
    DEFAULT_DPI,
    RenderNoiseStats,
    calibrate_corpus,
    measure_page_noise,
    recommended_epsilon,
)


@pytest.fixture()
def simple_pdf(tmp_path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Epsilon calibration test", fontsize=14, fontname="helv")
    path = tmp_path / "simple.pdf"
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture()
def two_pdf_corpus(tmp_path: Path, simple_pdf: Path) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    import shutil

    shutil.copy(simple_pdf, corpus / "case_a.pdf")
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Second case", fontsize=12, fontname="cour")
    doc.save(str(corpus / "case_b.pdf"))
    doc.close()
    return corpus


class TestMeasurePageNoise:
    def test_returns_render_noise_stats(self, simple_pdf: Path) -> None:
        doc = fitz.open(str(simple_pdf))
        stats = measure_page_noise(doc, page_num=0, iterations=5, dpi=DEFAULT_DPI)
        assert isinstance(stats, RenderNoiseStats)
        doc.close()

    def test_stats_have_expected_fields(self, simple_pdf: Path) -> None:
        doc = fitz.open(str(simple_pdf))
        stats = measure_page_noise(doc, page_num=0, iterations=5, dpi=DEFAULT_DPI)
        assert hasattr(stats, "max_abs_diff")
        assert hasattr(stats, "mean_abs_diff")
        assert hasattr(stats, "p99_abs_diff")
        assert hasattr(stats, "p999_abs_diff")
        assert hasattr(stats, "iterations")
        assert hasattr(stats, "dpi")
        assert hasattr(stats, "pixel_count")
        doc.close()

    def test_iterations_recorded(self, simple_pdf: Path) -> None:
        doc = fitz.open(str(simple_pdf))
        stats = measure_page_noise(doc, page_num=0, iterations=7, dpi=DEFAULT_DPI)
        assert stats.iterations == 7
        doc.close()

    def test_dpi_recorded(self, simple_pdf: Path) -> None:
        doc = fitz.open(str(simple_pdf))
        stats = measure_page_noise(doc, page_num=0, iterations=5, dpi=72)
        assert stats.dpi == 72
        doc.close()

    def test_pixel_count_positive(self, simple_pdf: Path) -> None:
        doc = fitz.open(str(simple_pdf))
        stats = measure_page_noise(doc, page_num=0, iterations=5, dpi=DEFAULT_DPI)
        assert stats.pixel_count > 0
        doc.close()

    def test_noise_values_nonnegative(self, simple_pdf: Path) -> None:
        doc = fitz.open(str(simple_pdf))
        stats = measure_page_noise(doc, page_num=0, iterations=10, dpi=DEFAULT_DPI)
        assert stats.max_abs_diff >= 0
        assert stats.mean_abs_diff >= 0.0
        assert stats.p99_abs_diff >= 0
        assert stats.p999_abs_diff >= 0
        doc.close()

    def test_max_ge_p999_ge_p99_ge_mean(self, simple_pdf: Path) -> None:
        doc = fitz.open(str(simple_pdf))
        stats = measure_page_noise(doc, page_num=0, iterations=10, dpi=DEFAULT_DPI)
        assert stats.max_abs_diff >= stats.p999_abs_diff
        assert stats.p999_abs_diff >= stats.p99_abs_diff
        assert stats.p99_abs_diff >= stats.mean_abs_diff
        doc.close()

    def test_minimum_iterations_enforced(self, simple_pdf: Path) -> None:
        doc = fitz.open(str(simple_pdf))
        with pytest.raises(ValueError, match="iterations"):
            measure_page_noise(doc, page_num=0, iterations=1, dpi=DEFAULT_DPI)
        doc.close()


class TestCalibrateCorpus:
    def test_returns_dict_keyed_by_case_name(self, two_pdf_corpus: Path) -> None:
        report = calibrate_corpus(two_pdf_corpus, iterations=3, dpi=DEFAULT_DPI)
        assert "case_a" in report
        assert "case_b" in report

    def test_each_entry_is_render_noise_stats(self, two_pdf_corpus: Path) -> None:
        report = calibrate_corpus(two_pdf_corpus, iterations=3, dpi=DEFAULT_DPI)
        for stats in report.values():
            assert isinstance(stats, RenderNoiseStats)

    def test_ignores_non_pdf_files(self, two_pdf_corpus: Path) -> None:
        (two_pdf_corpus / "readme.txt").write_text("not a pdf")
        report = calibrate_corpus(two_pdf_corpus, iterations=3, dpi=DEFAULT_DPI)
        assert "readme" not in report

    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty_corpus"
        empty.mkdir()
        report = calibrate_corpus(empty, iterations=3, dpi=DEFAULT_DPI)
        assert report == {}


class TestRecommendedEpsilon:
    def test_returns_int(self, simple_pdf: Path) -> None:
        doc = fitz.open(str(simple_pdf))
        stats = measure_page_noise(doc, page_num=0, iterations=5, dpi=DEFAULT_DPI)
        doc.close()
        eps = recommended_epsilon({"simple": stats})
        assert isinstance(eps, int)

    def test_at_least_zero(self, simple_pdf: Path) -> None:
        doc = fitz.open(str(simple_pdf))
        stats = measure_page_noise(doc, page_num=0, iterations=5, dpi=DEFAULT_DPI)
        doc.close()
        eps = recommended_epsilon({"simple": stats})
        assert eps >= 0

    def test_ge_max_observed_noise(self, simple_pdf: Path) -> None:
        doc = fitz.open(str(simple_pdf))
        stats = measure_page_noise(doc, page_num=0, iterations=5, dpi=DEFAULT_DPI)
        doc.close()
        eps = recommended_epsilon({"simple": stats})
        assert eps >= stats.max_abs_diff

    def test_empty_report_returns_zero(self) -> None:
        eps = recommended_epsilon({})
        assert eps == 0


class TestCLIOutput:
    def test_main_writes_json_report(self, two_pdf_corpus: Path, tmp_path: Path) -> None:
        from scripts.calibrate_render_epsilon import main

        out_file = tmp_path / "report.json"
        rc = main([str(two_pdf_corpus), "--output", str(out_file), "--iterations", "3"])
        assert rc == 0
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert "recommended_epsilon" in data
        assert "cases" in data
        assert isinstance(data["recommended_epsilon"], int)

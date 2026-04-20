from __future__ import annotations

import fitz
import pytest

from model.geometry import clamp_rect_to_page, rect_from_points, rect_overlap_ratio, rect_union


def test_clamp_inside_page_unchanged():
    r = fitz.Rect(10, 10, 100, 100)
    assert clamp_rect_to_page(r, fitz.Rect(0, 0, 595, 842)) == r


def test_clamp_overflow_right():
    r = fitz.Rect(500, 10, 700, 100)
    assert clamp_rect_to_page(r, fitz.Rect(0, 0, 595, 842)).x1 <= 595


def test_clamp_overflow_bottom():
    r = fitz.Rect(10, 800, 100, 900)
    assert clamp_rect_to_page(r, fitz.Rect(0, 0, 595, 842)).y1 <= 842


def test_clamp_degenerate_is_nonempty():
    r = clamp_rect_to_page(fitz.Rect(700, 700, 800, 800), fitz.Rect(0, 0, 595, 842))
    assert r.width >= 1 and r.height >= 1


def test_rect_from_points_basic():
    r = rect_from_points([fitz.Point(0, 0), fitz.Point(100, 200)])
    assert r == fitz.Rect(0, 0, 100, 200)


def test_rect_from_points_multiple():
    pts = [fitz.Point(50, 10), fitz.Point(10, 50), fitz.Point(30, 30)]
    r = rect_from_points(pts)
    assert r.x0 == 10 and r.y0 == 10 and r.x1 == 50 and r.y1 == 50


def test_rect_union_empty():
    assert rect_union([]) == fitz.Rect()


def test_rect_union_single():
    r = fitz.Rect(10, 10, 50, 50)
    assert rect_union([r]) == r


def test_rect_union_two():
    u = rect_union([fitz.Rect(0, 0, 50, 50), fitz.Rect(25, 25, 100, 100)])
    assert u == fitz.Rect(0, 0, 100, 100)


def test_rect_union_three():
    u = rect_union([fitz.Rect(0, 0, 10, 10), fitz.Rect(20, 20, 30, 30), fitz.Rect(5, 5, 25, 25)])
    assert u.x0 == 0 and u.y0 == 0 and u.x1 == 30 and u.y1 == 30


def test_overlap_ratio_no_overlap():
    assert rect_overlap_ratio(fitz.Rect(0, 0, 50, 50), fitz.Rect(100, 100, 200, 200)) == 0.0


def test_overlap_ratio_full_contain():
    ratio = rect_overlap_ratio(fitz.Rect(0, 0, 100, 100), fitz.Rect(25, 25, 75, 75))
    assert ratio == pytest.approx(1.0)


def test_overlap_ratio_partial():
    # Two 50x50 rects overlapping by 25x50 = 1250 area; smaller is 2500; ratio = 0.5
    ratio = rect_overlap_ratio(fitz.Rect(0, 0, 50, 50), fitz.Rect(25, 0, 75, 50))
    assert ratio == pytest.approx(0.5)


def test_overlap_ratio_empty_rect():
    assert rect_overlap_ratio(fitz.Rect(), fitz.Rect(0, 0, 10, 10)) == 0.0

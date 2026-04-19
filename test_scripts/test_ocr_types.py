from __future__ import annotations

import pytest

from model.tools.ocr_types import (
    OcrAvailability,
    OcrDevice,
    OcrLanguage,
    OcrRequest,
    OcrSpan,
    parse_page_range,
)


def test_ocr_span_constructs_with_bbox_text_confidence():
    span = OcrSpan(bbox=(1.0, 2.0, 3.0, 4.0), text="hi", confidence=0.98)
    assert span.bbox == (1.0, 2.0, 3.0, 4.0)
    assert span.text == "hi"
    assert span.confidence == pytest.approx(0.98)


def test_ocr_span_is_immutable():
    span = OcrSpan(bbox=(0.0, 0.0, 1.0, 1.0), text="x", confidence=0.5)
    with pytest.raises(Exception):
        span.text = "y"  # type: ignore[misc]


def test_ocr_language_codes_match_surya_strings():
    assert OcrLanguage.ENGLISH.value == "en"
    assert OcrLanguage.TRAD_CHINESE.value == "zh-Hant"
    assert OcrLanguage.SIMP_CHINESE.value == "zh-Hans"
    assert OcrLanguage.JAPANESE.value == "ja"


def test_ocr_language_lookup_from_string():
    assert OcrLanguage.from_code("en") is OcrLanguage.ENGLISH
    assert OcrLanguage.from_code("zh-Hant") is OcrLanguage.TRAD_CHINESE
    assert OcrLanguage.from_code("ZH-HANT") is OcrLanguage.TRAD_CHINESE
    with pytest.raises(ValueError):
        OcrLanguage.from_code("klingon")


def test_ocr_device_known_options():
    assert OcrDevice.AUTO.value == "auto"
    assert OcrDevice.CUDA.value == "cuda"
    assert OcrDevice.CPU.value == "cpu"


def test_ocr_availability_default_unavailable():
    avail = OcrAvailability(available=False, reason="missing")
    assert avail.available is False
    assert avail.reason == "missing"
    assert avail.install_hint == ""


def test_ocr_availability_with_install_hint():
    avail = OcrAvailability(available=False, reason="not installed", install_hint="pip install surya-ocr")
    assert avail.install_hint == "pip install surya-ocr"


def test_ocr_request_holds_indices_languages_device():
    req = OcrRequest(page_indices=(0, 2, 3), languages=("en", "zh-Hant"), device="cuda")
    assert req.page_indices == (0, 2, 3)
    assert req.languages == ("en", "zh-Hant")
    assert req.device == "cuda"


def test_ocr_request_default_device_is_auto():
    req = OcrRequest(page_indices=(0,), languages=("en",))
    assert req.device == "auto"


def test_parse_page_range_basic_mixed():
    assert parse_page_range("1,3-5,9", total_pages=10) == [0, 2, 3, 4, 8]


def test_parse_page_range_handles_whitespace():
    assert parse_page_range(" 1 , 3 - 5 , 9 ", total_pages=10) == [0, 2, 3, 4, 8]


def test_parse_page_range_all_keyword_returns_full_doc():
    assert parse_page_range("all", total_pages=10) == list(range(10))
    assert parse_page_range("ALL", total_pages=3) == [0, 1, 2]


def test_parse_page_range_empty_uses_default_current():
    assert parse_page_range("", total_pages=10, default_current=4) == [4]
    assert parse_page_range("   ", total_pages=10, default_current=0) == [0]


def test_parse_page_range_empty_without_default_raises():
    with pytest.raises(ValueError):
        parse_page_range("", total_pages=10)


def test_parse_page_range_dedupes_and_sorts():
    assert parse_page_range("3,1,3,2-3", total_pages=10) == [0, 1, 2]


def test_parse_page_range_rejects_zero_or_negative():
    with pytest.raises(ValueError):
        parse_page_range("0", total_pages=10)
    with pytest.raises(ValueError):
        parse_page_range("-1", total_pages=10)


def test_parse_page_range_rejects_inverted_range():
    with pytest.raises(ValueError):
        parse_page_range("5-3", total_pages=10)


def test_parse_page_range_rejects_non_numeric():
    with pytest.raises(ValueError):
        parse_page_range("abc", total_pages=10)
    with pytest.raises(ValueError):
        parse_page_range("1,foo", total_pages=10)


def test_parse_page_range_rejects_out_of_bounds():
    with pytest.raises(ValueError):
        parse_page_range("11", total_pages=10)
    with pytest.raises(ValueError):
        parse_page_range("8-12", total_pages=10)


def test_parse_page_range_default_current_must_be_in_range():
    with pytest.raises(ValueError):
        parse_page_range("", total_pages=5, default_current=10)
    with pytest.raises(ValueError):
        parse_page_range("", total_pages=5, default_current=-1)

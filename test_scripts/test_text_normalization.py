from __future__ import annotations

from model.text_normalization import normalize_text, normalized_similarity, token_coverage_ratio


def test_normalize_strips_whitespace():
    assert normalize_text("hello  world") == "helloworld"


def test_normalize_lowercases():
    assert normalize_text("Hello") == "hello"


def test_normalize_expands_fi_ligature():
    assert normalize_text("\ufb01re") == "fire"


def test_normalize_expands_ff_ligature():
    assert normalize_text("\ufb00") == "ff"


def test_normalize_empty():
    assert normalize_text("") == ""


def test_similarity_identical():
    assert normalized_similarity("abc", "abc") == 1.0


def test_similarity_one_empty():
    assert normalized_similarity("abc", "") == 0.0


def test_similarity_substring():
    assert normalized_similarity("hello", "say hello world") == 1.0


def test_token_coverage_full():
    assert token_coverage_ratio("hello world", normalize_text("hello world")) == 1.0


def test_token_coverage_empty_source():
    assert token_coverage_ratio("", "anything") == 1.0


def test_token_coverage_no_match():
    assert token_coverage_ratio("xyz abc", normalize_text("unrelated")) == 0.0

from __future__ import annotations

import difflib
import re

# Whitespace normalizer — strips all whitespace for comparison.
_RE_WS_STRIP = re.compile(r'\s+')

# Unicode ligature → decomposed character mapping.
# PyMuPDF's insert_htmlbox renders ligature substitutions (e.g. fi→ﬁ),
# so get_text() extraction diverges from the original string.
# This table expands them before any text comparison.
_LIGATURE_MAP = {
    '\ufb00': 'ff',   # ﬀ
    '\ufb01': 'fi',   # ﬁ
    '\ufb02': 'fl',   # ﬂ
    '\ufb03': 'ffi',  # ﬃ
    '\ufb04': 'ffl',  # ﬄ
    '\ufb05': 'st',   # ﬅ (long s + t)
    '\ufb06': 'st',   # ﬆ
}


def normalize_text(text: str) -> str:
    """Strip whitespace, lowercase, expand Unicode ligatures for text comparison.

    PyMuPDF's insert_htmlbox rendering substitutes letter combinations with
    Unicode ligatures (e.g. fi→ﬁ), causing get_text() extraction to diverge
    from the original string. This function normalizes both sides before
    comparison.
    """
    if not text:
        return ""
    result = text
    for lig, expanded in _LIGATURE_MAP.items():
        if lig in result:
            result = result.replace(lig, expanded)
    # Drop unstable extraction artifacts and normalize common punctuation variants.
    result = (
        result.replace("\ufffd", "")
        .replace("\u200b", "")
        .replace("\ufeff", "")
        .replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )
    return _RE_WS_STRIP.sub('', result).lower()


def normalized_similarity(left: str, right: str) -> float:
    """Similarity score on normalized strings (0..1).

    Returns 1.0 if either string contains the other as a substring (after
    normalization), otherwise falls back to difflib SequenceMatcher ratio.
    """
    norm_left = normalize_text(left)
    norm_right = normalize_text(right)
    if not norm_left and not norm_right:
        return 1.0
    if not norm_left or not norm_right:
        return 0.0
    if norm_left in norm_right or norm_right in norm_left:
        return 1.0
    return difflib.SequenceMatcher(None, norm_left, norm_right).ratio()


def token_coverage_ratio(source_text: str, haystack_norm: str) -> float:
    """Return token hit ratio (0..1) using normalized token containment with 1-char tolerance.

    Splits source_text on whitespace, normalizes each token, and counts how
    many appear in the pre-normalized haystack_norm. A one-character prefix/
    suffix truncation is allowed to absorb minor OCR/extraction drift.
    """
    if not source_text:
        return 1.0
    if not haystack_norm:
        return 0.0
    raw_tokens = [tok for tok in re.split(r"\s+", source_text) if tok]
    tokens = [normalize_text(tok) for tok in raw_tokens]
    tokens = [tok for tok in tokens if tok]
    if not tokens:
        return 1.0
    hit = 0
    for tok in tokens:
        if tok in haystack_norm:
            hit += 1
            continue
        if len(tok) >= 4 and (tok[1:] in haystack_norm or tok[:-1] in haystack_norm):
            hit += 1
    return hit / len(tokens)

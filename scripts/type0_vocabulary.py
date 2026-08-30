"""Closed replacement vocabularies for the Task 14 Type0 census.

The strings are inputs only.  Census reports publish vocabulary slugs and
aggregate counts, never the characters or candidate font paths.  The CAD list
is a seed pending domain-owner sign-off; it is not a normative dictionary.

``fitz.Font(fontfile=...)`` observes face 0 of a TTC.  The dependency-free
supplier here is therefore a heuristic upper bound; the later same-face audit
must inspect every collection face with fontTools before any mutation is safe.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import fitz


def _unique_chars(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(text))


_FULLWIDTH_DIGITS_PUNCT = _unique_chars(
    "".join(chr(code) for code in range(0xFF10, 0xFF1A))
    + "".join(chr(code) for code in range(0x3000, 0x3003))
    + "".join(chr(code) for code in (0xFF01, 0xFF08, 0xFF09, 0xFF0C))
    + "".join(chr(code) for code in (0xFF1A, 0xFF1B, 0xFF1F))
    + "".join(chr(code) for code in (0x300C, 0x300D))
    + "".join(chr(code) for code in (0x00B0, 0x00B1, 0x00D7))
)

# SEED pending domain sign-off.  Kept as characters rather than words because
# replacement admission is decided one Unicode scalar at a time.
_CAD_COMMON = _unique_chars(
    "圖號比例尺寸材料數量備註版本日期設計審核准單位平面立剖詳說明工程名稱"
    "建築結構機電空調消防給排水弱電照明動力控制系統設備管線風機泵浦閥門"
    "冷卻冰水回送排氣溫濕度壓差流量容量效率功率電壓頻率轉速重量高度寬深"
    "中心標高樓層屋頂地下室基礎牆柱梁板門窗孔洞套管支架吊架保溫防震隔音"
    "施工安裝測試運轉維護檢查清潔更換拆除新增既有預留接續現場依照規範"
    "標準廠牌型式規格編號位置方向範圍界面細部典型參考索引修訂變更確認"
    "注意不得應須可由及或與為之於上下左右前後內外東西南北層區棟座組台"
    "公尺毫米平方立方每秒小時年月日甲乙丙丁主次進出口開關閉合正常異常"
)

_HIRAGANA = "".join(chr(code) for code in range(0x3041, 0x3097))
_KATAKANA = "".join(chr(code) for code in range(0x30A1, 0x30FB))
_JAPANESE_COMMON_KANJI = (
    "日一国会人年大十二本中長出三同時政事自行社見月分議後前民生連五発間"
    "対上部東者党地合市業内相方四定今回新場金員九入選立開手米力学問高代"
    "明実円関決子動京全目表戦経通外最言氏現理調体化田当八六約主題下首意"
    "法不来作性的要用制治度務強気小七成期公持野協取都和統以機平総加山思"
    "家話世受区領多県続進正安設保改数記院女初北午指権心界支第産結百派点"
    "教報済書府活原先共得解名交資予川向際査勝面委告軍文反元重近千考判認"
    "画海参売利組知案道信策集在件団別物側任引使求所次水半品昨論計死官増"
    "係感特情投示変打男基私各始島直両朝革価式確村提運終挙果西勢減台広容"
)
_JAPANESE_COMMON = _unique_chars(
    _HIRAGANA + _KATAKANA + _JAPANESE_COMMON_KANJI
)

_SIP_SAMPLE = tuple(
    chr(code)
    for code in (
        0x20000,
        0x20001,
        0x20003,
        0x20009,
        0x2000B,
        0x2000D,
        0x20022,
        0x20031,
        0x2003E,
        0x20046,
        0x2004E,
        0x20087,
    )
)

VOCABULARY_NAMES = (
    "fullwidth_digits_punct",
    "cad_common",
    "japanese_common",
    "sip_sample",
)
VOCABULARIES: dict[str, tuple[str, ...]] = {
    "fullwidth_digits_punct": _FULLWIDTH_DIGITS_PUNCT,
    "cad_common": _CAD_COMMON,
    "japanese_common": _JAPANESE_COMMON,
    "sip_sample": _SIP_SAMPLE,
}

# Duplicated deliberately from model/pdf_model.py and pinned by a sync test.
# Importing the GUI/model composition module from this read-only script would
# pull unrelated runtime dependencies into the census.
CANDIDATE_FONT_FILES = (
    Path(r"C:\Windows\Fonts\msjh.ttc"),
    Path(r"C:\Windows\Fonts\mingliu.ttc"),
    Path(r"C:\Windows\Fonts\kaiu.ttf"),
)


def system_candidate_supplier() -> Callable[[str], bool] | None:
    """Return a face-0 glyph predicate for existing candidate files."""
    faces: list[fitz.Font] = []
    for path in CANDIDATE_FONT_FILES:
        if not path.is_file():
            continue
        try:
            faces.append(fitz.Font(fontfile=str(path)))
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
            continue
    if not faces:
        return None

    def has_glyph(char: str) -> bool:
        codepoint = ord(char)
        for face in faces:
            try:
                if face.has_glyph(codepoint, fallback=0) != 0:
                    return True
            except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
                continue
        return False

    return has_glyph

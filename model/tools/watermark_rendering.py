from __future__ import annotations

import math
import re

import fitz


def needs_cjk_font(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))


def resolve_watermark_font(font_name: str, text: str) -> str:
    non_cjk_fonts = ("helv", "cour", "Helvetica", "Courier")
    if needs_cjk_font(text) and font_name in non_cjk_fonts:
        return "china-ts"
    return font_name


def apply_watermarks_to_page(page: fitz.Page, watermarks: list[dict]) -> None:
    if not watermarks:
        return

    page_rect = page.rect
    cx = page_rect.width / 2
    cy = page_rect.height / 2

    for wm in watermarks:
        text = wm.get("text", "")
        angle = wm.get("angle", 0)
        opacity = max(0.0, min(1.0, wm.get("opacity", 0.5)))
        font_size = wm.get("font_size", 48)
        color = wm.get("color", (0.7, 0.7, 0.7))
        font_name = resolve_watermark_font(wm.get("font", "helv"), text)
        offset_x = wm.get("offset_x", 0)
        offset_y = wm.get("offset_y", 0)
        line_spacing = wm.get("line_spacing", 1.3)

        center_x = cx + offset_x
        center_y = cy + offset_y
        center = fitz.Point(center_x, center_y)

        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if not lines:
            continue

        try:
            font = fitz.Font(font_name)
        except Exception:
            font = fitz.Font("china-ts" if needs_cjk_font(text) else "helv")

        line_height = font_size * line_spacing
        total_height = line_height * len(lines)
        rad = math.radians(-angle)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        for i, line in enumerate(lines):
            line_len = font.text_length(line, fontsize=font_size)
            dx = -line_len / 2
            dy = -total_height / 2 + i * line_height + font_size * 0.35
            px = center_x + dx * cos_a - dy * sin_a
            py = center_y + dx * sin_a + dy * cos_a
            pt = fitz.Point(px, py)
            mat = fitz.Matrix(cos_a, -sin_a, sin_a, cos_a, 0, 0)
            page.insert_text(
                pt,
                line,
                fontsize=font_size,
                fontname=font_name,
                color=color[:3] if len(color) >= 3 else (0.7, 0.7, 0.7),
                morph=(center, mat),
                fill_opacity=opacity,
                stroke_opacity=opacity,
            )

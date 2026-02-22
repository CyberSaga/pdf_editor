# -*- coding: utf-8 -*-
"""
測試 1.pdf 水平文字編輯：驗證輸出在頁面內、文字可見
支援兩種測試路徑：
1. 索引路徑：直接用 index 的 block rect（與 model 內部一致）
2. GUI 路徑：用 get_text_info_at_point 取得 rect（模擬使用者點擊）
"""
import sys
import io
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from model.pdf_model import PDFModel

def test_horizontal_edit_and_verify(use_gui_flow: bool = False, save_output: str = None):
    base = Path(__file__).parent
    path = base / "1.pdf"
    if not path.exists():
        print("1.pdf 不存在")
        return 1

    model = PDFModel()
    model.open_pdf(str(path))
    page = model.doc[0]
    page_rect = page.rect

    if use_gui_flow:
        # GUI 路徑：用 block 中心點呼叫 get_text_info_at_point，取得 rect
        blocks = model.block_manager.get_blocks(0)
        target = None
        for b in blocks:
            if b.rotation == 0 and len(b.text.strip()) >= 5:
                target = b
                break
        if not target:
            print("無合適水平文字塊")
            model.close()
            return 1
        block_rect = target.layout_rect
        center = block_rect.x0 + block_rect.width / 2, block_rect.y0 + block_rect.height / 2
        import fitz
        info = model.get_text_info_at_point(1, fitz.Point(center[0], center[1]))
        if not info:
            print("get_text_info_at_point 未取得文字")
            model.close()
            return 1
        rect, orig_text = info[0], info[1]
        font, size, color = info[2], int(info[3]), info[4]
        print(f"GUI 路徑: rect={rect}, orig_text[:30]={repr(orig_text[:30])}")
    else:
        # 索引路徑：直接用 block_manager 的 TextBlock dataclass
        blocks = model.block_manager.get_blocks(0)
        target = None
        for b in blocks:
            if b.rotation == 0 and len(b.text.strip()) >= 5:
                target = b
                break
        if not target:
            print("無合適水平文字塊")
            model.close()
            return 1
        rect = target.layout_rect
        orig_text = target.text
        font = target.font
        size = int(target.size)
        color = target.color
    # 用較長文字測試，確認會換行且不超出
    new_text = "This is a test of horizontal text editing. " * 5

    try:
        model.edit_text(
            page_num=1,
            rect=rect,
            new_text=new_text,
            font=font,
            size=size,
            color=color,
            original_text=orig_text,
        )
    except Exception as e:
        print(f"編輯失敗: {e}")
        model.close()
        return 1

    # 驗證：擷取頁面文字，確認新文字存在（get_text 可能回傳 \xa0 等字元）
    page = model.doc[0]
    full_text = page.get_text("text")
    if "This" not in full_text and "horizontal" not in full_text:
        print("失敗：編輯後頁面找不到新文字")
        model.close()
        return 1

    # 驗證：取得所有文字塊的 bbox，確認不超出頁面
    words = page.get_text("words")
    if words:
        x0_min = min(w[0] for w in words)
        y0_min = min(w[1] for w in words)
        x1_max = max(w[2] for w in words)
        y1_max = max(w[3] for w in words)
        if x1_max > page_rect.x1 or x0_min < page_rect.x0:
            print(f"失敗：文字超出頁面 x 範圍 (x0={x0_min}, x1={x1_max}, page.x1={page_rect.x1})")
            model.close()
            return 1
        if y1_max > page_rect.y1 or y0_min < page_rect.y0:
            print(f"失敗：文字超出頁面 y 範圍 (y0={y0_min}, y1={y1_max})")
            model.close()
            return 1

    if save_output:
        out_path = Path(save_output)
        model.doc.save(str(out_path), garbage=0)
        print(f"已儲存編輯結果至: {out_path}（可開啟檢視文字是否在頁面內）")

    print("通過：水平文字編輯成功，文字在頁面內且可見")
    model.close()
    return 0

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--gui", action="store_true", help="模擬 GUI 流程（get_text_info_at_point）")
    p.add_argument("--save", metavar="PATH", help="儲存編輯後 PDF 以供視覺驗證")
    args = p.parse_args()
    sys.exit(test_horizontal_edit_and_verify(use_gui_flow=args.gui, save_output=args.save))

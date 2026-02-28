# -*- coding: utf-8 -*-
"""
使用 1.pdf、2.pdf、when I was young I.pdf 測試 PDF 編輯器
驗證：開啟、建立索引、擷取文字、執行編輯
"""
import sys
import io
from pathlib import Path

if sys.platform == 'win32' and __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from model.pdf_model import PDFModel

PDF_FILES = [
    "1.pdf",
    "2.pdf",
    "when I was young I.pdf",
]

def test_pdf(path: Path) -> tuple[bool, str]:
    """測試單一 PDF：開啟、索引、擷取文字、嘗試編輯第一塊文字"""
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        n_pages = len(model.doc)
        all_page_indices = list(model.block_manager._index.keys())
        total_blocks = sum(len(model.block_manager.get_blocks(p)) for p in all_page_indices)
        if total_blocks == 0:
            model.close()
            return True, f"OK (無文字塊, {n_pages} 頁)"
        for page_idx in all_page_indices:
            blocks = model.block_manager.get_blocks(page_idx)
            for block in blocks:
                text = block.text.strip()
                if not text or len(text) < 2:
                    continue
                rect = block.layout_rect
                try:
                    new_text = "[TEST]" + text[:20] + ("..." if len(text) > 20 else "")
                    model.edit_text(
                        page_num=page_idx + 1,
                        rect=rect,
                        new_text=new_text,
                        font=block.font,
                        size=int(block.size),
                        color=block.color,
                        original_text=text,
                    )
                    model.close()
                    return True, f"OK (已編輯第1塊, {n_pages}頁 {total_blocks}塊)"
                except Exception as e:
                    model.close()
                    return False, f"編輯失敗: {e}"
        model.close()
        return True, f"OK (無可編輯塊, {n_pages}頁 {total_blocks}塊)"
    except Exception as e:
        try:
            model.close()
        except Exception:
            pass
        return False, str(e)

def main():
    base = Path(__file__).parent
    print("=" * 60)
    print("測試 PDF 檔案：1.pdf, 2.pdf, when I was young I.pdf")
    print("=" * 60)
    ok_count = 0
    for name in PDF_FILES:
        path = base / name
        if not path.exists():
            print(f"\n{name}: [略過] 檔案不存在")
            continue
        success, msg = test_pdf(path)
        status = "[通過]" if success else "[失敗]"
        print(f"\n{name}: {status} {msg}")
        if success:
            ok_count += 1
    print("\n" + "=" * 60)
    print(f"結果: {ok_count}/{len(PDF_FILES)} 通過")
    return 0 if ok_count == len(PDF_FILES) else 1

if __name__ == "__main__":
    sys.exit(main())

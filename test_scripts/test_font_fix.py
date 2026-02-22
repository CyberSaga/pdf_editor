"""
測試腳本：驗證中英文混合文字的字體分配是否正確
"""
# -*- coding: utf-8 -*-
import sys
import io

# 設置標準輸出編碼為 UTF-8（Windows 兼容）
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from model.pdf_model import PDFModel

def test_html_conversion():
    """測試 _convert_text_to_html 函數的字體分配"""
    model = PDFModel()
    
    # 測試案例
    test_cases = [
        ("Hello 世界", "應包含 helv 和 cjk 字體"),
        ("測試 Test 123", "應包含 cjk、helv、helv 字體"),
        ("ABC中文DEF", "應包含 helv、cjk、helv 字體"),
        ("只有中文", "應只有 cjk 字體"),
        ("Only English 123", "應只有 helv 字體"),
        ("第一行\n第二行 Second Line", "應正確處理換行"),
    ]
    
    print("=" * 60)
    print("測試 HTML 轉換功能")
    print("=" * 60)
    
    for i, (text, description) in enumerate(test_cases, 1):
        print(f"\n測試案例 {i}: {text}")
        print(f"說明: {description}")
        print("-" * 60)
        
        html = model._convert_text_to_html(text, font_size=12, color=(0.0, 0.0, 0.0))
        print(f"生成的 HTML:\n{html}")
        
        # 檢查字體分配
        has_cjk = 'font-family: cjk' in html
        has_helv = 'font-family: helv' in html
        
        # 檢查文字是否包含中文和英文
        has_chinese = any(0x4E00 <= ord(c) <= 0x9FFF for c in text)
        has_english = any(c.isascii() and c.isalnum() for c in text)
        
        print(f"\n分析:")
        print(f"  文字包含中文: {has_chinese}")
        print(f"  文字包含英文/數字: {has_english}")
        print(f"  HTML 包含 cjk 字體: {has_cjk}")
        print(f"  HTML 包含 helv 字體: {has_helv}")
        
        # 驗證
        if has_chinese and has_english:
            if has_cjk and has_helv:
                print("  [通過] 混合文字正確分配了兩種字體")
            else:
                print("  [失敗] 混合文字應包含兩種字體")
        elif has_chinese:
            if has_cjk and not has_helv:
                print("  [通過] 純中文正確使用 cjk 字體")
            else:
                print("  [失敗] 純中文應只使用 cjk 字體")
        elif has_english:
            if has_helv and not has_cjk:
                print("  [通過] 純英文正確使用 helv 字體")
            else:
                print("  [失敗] 純英文應只使用 helv 字體")
    
    print("\n" + "=" * 60)
    print("測試完成！")
    print("=" * 60)
    print("\n提示：如果所有測試案例都通過，表示字體分配邏輯正確。")
    print("您仍需要啟動 GUI 並實際編輯 PDF 來驗證最終顯示效果。")

if __name__ == "__main__":
    test_html_conversion()


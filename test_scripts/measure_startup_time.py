"""
測量測試程式的啟動時間
"""
# -*- coding: utf-8 -*-
import time
import sys
import io

# 設置標準輸出編碼為 UTF-8（Windows 兼容）
if sys.platform == 'win32' and __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

print("開始測量啟動時間...")
print("-" * 60)

# 測量導入時間
import_start = time.time()
from model.pdf_model import PDFModel
import_end = time.time()
import_time = import_end - import_start

# 測量實例化時間
instance_start = time.time()
model = PDFModel()
instance_end = time.time()
instance_time = instance_end - instance_start

# 測量完整測試執行時間
test_start = time.time()
exec(open('test_font_fix.py').read())
test_end = time.time()
test_time = test_end - test_start

print("\n" + "=" * 60)
print("時間測量結果：")
print("=" * 60)
print(f"導入 PDFModel 模組時間: {import_time:.3f} 秒")
print(f"實例化 PDFModel 時間: {instance_time:.3f} 秒")
print(f"完整測試執行時間: {test_time:.3f} 秒")
print(f"總啟動時間（導入+實例化）: {import_time + instance_time:.3f} 秒")
print("=" * 60)


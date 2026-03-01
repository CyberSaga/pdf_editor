# -*- coding: utf-8 -*-
"""
測量啟動時間：
1) 匯入 PDFModel
2) 建立 PDFModel 實例
3) 執行 test_font_fix.py
"""

from __future__ import annotations

import io
import runpy
import sys
import time
from pathlib import Path


if sys.platform == "win32" and __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    print("開始測量啟動時間...")
    print("-" * 60)

    import_start = time.time()
    from model.pdf_model import PDFModel  # noqa: WPS433
    import_end = time.time()
    import_time = import_end - import_start

    instance_start = time.time()
    _model = PDFModel()
    instance_end = time.time()
    instance_time = instance_end - instance_start

    test_start = time.time()
    runpy.run_path(str(SCRIPTS_DIR / "test_font_fix.py"), run_name="__main__")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

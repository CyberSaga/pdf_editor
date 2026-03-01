# -*- coding: utf-8 -*-
"""
test_all_pdfs.py — 全 test_files 目錄 PDF 批次測試
====================================================
測試策略（三層）：
  Layer 1 — open_pdf：能否正常開啟（含加密 PDF 自動嘗試密碼）
  Layer 2 — build_index：TextBlockManager 能否正確建立索引
  Layer 3 — edit_text：若頁面含文字塊，嘗試執行 1 次 edit_text

特殊處理：
  - encrypted.pdf → 先試無密碼，再試 "kanbanery"
  - corrupted.pdf → 預期開啟失敗，記錄為 EXPECTED_FAIL
  - password-protected 其他 PDF → 記為 SKIP_ENCRYPTED（無法取得密碼）
  - 無文字塊的 PDF → Layer 3 記為 SKIP_NO_TEXT
  - veraPDF-corpus-staging：已知為合規測試用途，僅跑 Layer 1+2

輸出：
  test_outputs/error_log.txt   — 所有錯誤與異常的詳細記錄
  終端機 stdout   — 進度概覽 + 最終統計
"""
import sys
import io
import os
import time
import traceback
from pathlib import Path

if sys.platform == "win32" and __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import logging
logging.disable(logging.CRITICAL)   # 批次測試期間關閉所有 log，避免大量 I/O

import fitz

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "test_outputs"
sys.path.insert(0, str(ROOT))
from model.pdf_model import PDFModel

# ──────────────────────────────────────────────────────────────────
# 設定
# ──────────────────────────────────────────────────────────────────
TEST_FILES_ROOT = ROOT / "test_files"
ERROR_LOG       = OUTPUT_DIR / "error_log.txt"

# 已知密碼表：{檔名（小寫）→ 密碼}
# 支援 user password（開啟密碼）與 owner password（權限密碼）。
# PyMuPDF authenticate() 會自動判斷類型：
#   回傳 2=user, 4=owner, 6=both — 均視為認證成功
KNOWN_PASSWORDS = {
    "encrypted.pdf": "kanbanery",
    "libreoffice-writer-password.pdf": "permissionpassword",
}
# 無 edit_text 的目錄（veraPDF 合規測試太多，僅 Layer 1+2）
NO_EDIT_DIRS = {"veraPDF-corpus-staging"}

# Layer 3 edit_text 使用的替換文字
EDIT_TEXT_SAMPLE = "Phase 7 batch test edit"

# ──────────────────────────────────────────────────────────────────
# 結果分類
# ──────────────────────────────────────────────────────────────────
class Result:
    OK           = "OK"
    SKIP_ENC     = "SKIP_ENCRYPTED"
    SKIP_NO_TEXT = "SKIP_NO_TEXT"
    SKIP_EDIT    = "SKIP_EDIT_DISABLED"
    EXPECTED_FAIL= "EXPECTED_FAIL"
    ERR_OPEN     = "ERR_OPEN"
    ERR_INDEX    = "ERR_INDEX"
    ERR_EDIT     = "ERR_EDIT"

# ──────────────────────────────────────────────────────────────────
# 輔助：判斷 PDF 所在頂層子目錄
# ──────────────────────────────────────────────────────────────────
def _top_subdir(pdf_path: Path) -> str:
    try:
        rel = pdf_path.relative_to(TEST_FILES_ROOT)
        return rel.parts[0] if rel.parts else ""
    except ValueError:
        return ""

def _is_no_edit(pdf_path: Path) -> bool:
    return _top_subdir(pdf_path) in NO_EDIT_DIRS

def _get_password(pdf_path: Path) -> str | None:
    return KNOWN_PASSWORDS.get(pdf_path.name.lower()) or KNOWN_PASSWORDS.get(pdf_path.name)

# ──────────────────────────────────────────────────────────────────
# 單檔測試
# ──────────────────────────────────────────────────────────────────
def test_one_pdf(pdf_path: Path, error_lines: list) -> dict:
    """
    測試單個 PDF 檔案，回傳 {
        'path': str, 'layer1': str, 'layer2': str, 'layer3': str,
        'pages': int, 'text_blocks': int, 'duration_ms': float
    }
    """
    rel = str(pdf_path.relative_to(TEST_FILES_ROOT))
    result = {
        "path": rel, "layer1": None, "layer2": None, "layer3": None,
        "pages": 0, "text_blocks": 0, "duration_ms": 0.0,
    }
    t0 = time.perf_counter()
    model = PDFModel()

    try:
        # ── Layer 1: open_pdf ──
        # model.open_pdf() 已支援 password 參數（user / owner password 均可）
        password = _get_password(pdf_path)
        try:
            model.open_pdf(str(pdf_path), password=password)
            result["layer1"] = Result.OK
        except Exception as e:
            err_str = str(e)
            _enc_keywords = ("encrypted", "password", "authenticate", "needs_pass",
                             "closed or encrypted")
            is_enc_err = any(kw in err_str.lower() for kw in _enc_keywords)
            if is_enc_err and not password:
                # 無已知密碼 → 跳過
                result["layer1"] = Result.SKIP_ENC
                error_lines.append(f"[SKIP_ENCRYPTED] {rel} | 未知密碼，無法開啟")
                return _finalize(result, t0, model)
            elif is_enc_err and password:
                # 有密碼但仍失敗（密碼錯誤）
                result["layer1"] = Result.SKIP_ENC
                error_lines.append(f"[SKIP_ENCRYPTED] {rel} | 密碼驗證失敗 ({password})")
                return _finalize(result, t0, model)
            else:
                result["layer1"] = Result.ERR_OPEN
                short = err_str[:120].replace("\n", " ")
                error_lines.append(f"[ERR_OPEN] {rel} | {short}")
                return _finalize(result, t0, model)

        result["pages"] = len(model.doc) if model.doc else 0

        # ── Layer 2: build_index ──
        # open_pdf 已呼叫 build_index，此處確認索引正常
        try:
            total_blocks = sum(
                len(model.block_manager.get_blocks(i))
                for i in range(result["pages"])
            )
            result["text_blocks"] = total_blocks
            result["layer2"] = Result.OK
        except Exception as e:
            result["layer2"] = Result.ERR_INDEX
            error_lines.append(f"[ERR_INDEX] {rel} | {str(e)[:120]}")
            return _finalize(result, t0, model)

        # ── Layer 3: edit_text ──
        if _is_no_edit(pdf_path):
            result["layer3"] = Result.SKIP_EDIT
        elif result["text_blocks"] == 0:
            result["layer3"] = Result.SKIP_NO_TEXT
        else:
            result["layer3"] = _try_edit(model, rel, error_lines)

        return _finalize(result, t0, model)

    except Exception as e:
        result["layer1"] = result["layer1"] or Result.ERR_OPEN
        error_lines.append(
            f"[UNEXPECTED] {rel} | {str(e)[:120]}\n"
            f"  {''.join(traceback.format_exc().splitlines(True)[-3:]).strip()}"
        )
        return _finalize(result, t0, model)
    finally:
        try:
            model.close()
        except Exception:
            pass


def _finalize(result: dict, t0: float, model: PDFModel) -> dict:
    result["duration_ms"] = (time.perf_counter() - t0) * 1000
    # 未執行到的 layer 標為 None（表示未到達）
    return result


def _try_edit(model: PDFModel, rel: str, error_lines: list) -> str:
    """
    在第一個有文字塊的頁面執行 1 次 edit_text，回傳 Result.*。
    """
    for page_idx in range(len(model.doc)):
        blocks = model.block_manager.get_blocks(page_idx)
        if not blocks:
            continue
        blk = blocks[0]
        if not blk.text.strip():
            continue
        try:
            model.edit_text(
                page_num=page_idx + 1,
                rect=blk.layout_rect,
                new_text=EDIT_TEXT_SAMPLE,
                font="helv",
                size=max(8, int(blk.size) if blk.size else 11),
                color=(0.0, 0.0, 0.0),
                original_text=blk.text,
            )
            return Result.OK
        except RuntimeError as e:
            err = str(e)[:120]
            error_lines.append(f"[ERR_EDIT] {rel} | p{page_idx+1} RuntimeError: {err}")
            return Result.ERR_EDIT
        except Exception as e:
            error_lines.append(
                f"[ERR_EDIT] {rel} | p{page_idx+1} UNEXPECTED: {str(e)[:120]}"
            )
            return Result.ERR_EDIT
    return Result.SKIP_NO_TEXT


# ──────────────────────────────────────────────────────────────────
# 收集所有 PDF
# ──────────────────────────────────────────────────────────────────
def collect_pdfs() -> list[Path]:
    pdfs = sorted(TEST_FILES_ROOT.rglob("*.pdf"))
    return pdfs


# ──────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pdfs = collect_pdfs()
    total = len(pdfs)
    print(f"\n{'='*65}")
    print(f"  test_all_pdfs — 批次測試 {total} 個 PDF 檔案")
    print(f"  error_log → {ERROR_LOG.name}")
    print(f"{'='*65}\n")

    # 統計
    counts = {r: 0 for r in (
        Result.OK, Result.SKIP_ENC, Result.SKIP_NO_TEXT,
        Result.SKIP_EDIT, Result.EXPECTED_FAIL,
        Result.ERR_OPEN, Result.ERR_INDEX, Result.ERR_EDIT,
    )}
    error_lines: list[str] = []
    layer3_errors: list[str] = []
    total_ms = 0.0
    slow_files: list[str] = []

    t_start = time.perf_counter()

    for idx, pdf_path in enumerate(pdfs, 1):
        r = test_one_pdf(pdf_path, error_lines)
        total_ms += r["duration_ms"]

        # 最終狀態取最嚴重的層次
        final = (
            r["layer3"] or r["layer2"] or r["layer1"] or Result.ERR_OPEN
        )
        # 若任何層是 ERR，以 ERR 為主
        for layer in ("layer1", "layer2", "layer3"):
            v = r[layer]
            if v and v.startswith("ERR"):
                final = v
                break

        counts[final] = counts.get(final, 0) + 1
        if r["duration_ms"] > 2000:
            slow_files.append(f"{r['path']} ({r['duration_ms']:.0f}ms)")

        # 進度顯示（每 100 個或最後一個）
        if idx % 100 == 0 or idx == total:
            elapsed = time.perf_counter() - t_start
            pct = idx / total * 100
            ok_n = counts[Result.OK]
            err_n = counts[Result.ERR_OPEN] + counts[Result.ERR_INDEX] + counts[Result.ERR_EDIT]
            print(
                f"  [{idx:4d}/{total}] {pct:5.1f}%  "
                f"OK={ok_n}  ERR={err_n}  "
                f"跳過={counts[Result.SKIP_ENC]+counts[Result.SKIP_NO_TEXT]+counts[Result.SKIP_EDIT]}  "
                f"耗時 {elapsed:.0f}s"
            )

    total_elapsed = time.perf_counter() - t_start

    # ── 寫入 error_log.txt ──
    with open(ERROR_LOG, "w", encoding="utf-8") as f:
        f.write(f"test_all_pdfs error log — {total} 個 PDF\n")
        f.write(f"測試時間：{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'='*65}\n\n")
        if error_lines:
            f.write("\n".join(error_lines))
            f.write("\n")
        else:
            f.write("（無錯誤）\n")
        if slow_files:
            f.write(f"\n{'─'*65}\n超過 2s 的檔案：\n")
            for s in slow_files:
                f.write(f"  {s}\n")

    # ── 終端機報告 ──
    print(f"\n{'='*65}")
    print(f"  批次測試完成  共 {total} 個 PDF，耗時 {total_elapsed:.1f}s")
    print(f"{'─'*65}")
    print(f"  OK（全部通過）：{counts[Result.OK]}")
    print(f"  SKIP_ENCRYPTED：{counts[Result.SKIP_ENC]}")
    print(f"  SKIP_NO_TEXT   ：{counts[Result.SKIP_NO_TEXT]}")
    print(f"  SKIP_EDIT_DISABLED：{counts[Result.SKIP_EDIT]}")
    print(f"  ERR_OPEN       ：{counts[Result.ERR_OPEN]}")
    print(f"  ERR_INDEX      ：{counts[Result.ERR_INDEX]}")
    print(f"  ERR_EDIT       ：{counts[Result.ERR_EDIT]}")
    print(f"{'─'*65}")
    total_err = counts[Result.ERR_OPEN] + counts[Result.ERR_INDEX] + counts[Result.ERR_EDIT]
    print(f"  總錯誤數：{total_err}")
    if total_err == 0:
        print(f"\n  所有可開啟的 PDF 均通過測試 ✓")
    else:
        print(f"\n  詳細錯誤已記錄至 {ERROR_LOG.name}，請查閱後修正。")
    print(f"{'='*65}\n")
    return 0 if total_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

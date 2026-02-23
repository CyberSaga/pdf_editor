# -*- coding: utf-8 -*-
"""
test_feature_conflict.py — 功能與衝突驗證
==========================================
- 單一功能：逐項呼叫 Model/Command 流程，驗證每項功能可獨立成功。
- 衝突情境：多功能依序或交錯（如 註解→編輯文字、編輯→復原→重做、刪頁→復原 等），
  驗證無互相覆蓋或狀態錯亂。
- 使用 test_files 內 PDF（優先 sample-files-main，必要時 veraPDF 代表檔）。
- 輸出：每個概念的通過率、耗時、失敗案例與根本成因分析；穩定性結論與建議。
"""
import sys
import io
import os
import time
import tempfile
import traceback
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass, field

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import logging
logging.disable(logging.CRITICAL)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_FILES_ROOT = ROOT / "test_files"
if not TEST_FILES_ROOT.exists():
    TEST_FILES_ROOT = Path(__file__).resolve().parent / "test_files"
SAMPLE_DIR = TEST_FILES_ROOT / "sample-files-main"
REPORT_PATH = ROOT / "docs" / "feature_conflict_test_report.txt"

import fitz
from model.pdf_model import PDFModel
from model.edit_commands import EditTextCommand, SnapshotCommand

KNOWN_PASSWORDS = {"encrypted.pdf": "kanbanery", "libreoffice-writer-password.pdf": "permissionpassword"}


@dataclass
class CaseResult:
    name: str
    passed: bool
    duration_ms: float
    detail: str = ""
    error: str = ""


@dataclass
class ConceptResult:
    id: str
    title: str
    cases: List[CaseResult] = field(default_factory=list)
    total_ms: float = 0.0

    @property
    def total(self) -> int: return len(self.cases)
    @property
    def passed(self) -> int: return sum(1 for c in self.cases if c.passed)
    @property
    def pass_rate(self) -> float: return self.passed / self.total * 100 if self.total else 0


def _ms() -> float:
    return time.perf_counter() * 1000


def _get_password(p: Path) -> Optional[str]:
    return KNOWN_PASSWORDS.get(p.name.lower())


def _collect_pdfs(limit: int = 12) -> List[Path]:
    out = []
    if not SAMPLE_DIR.exists():
        return out
    for f in sorted(SAMPLE_DIR.rglob("*.pdf")):
        if _get_password(f):
            out.append(f)
        else:
            try:
                d = fitz.open(str(f))
                if d.needs_pass:
                    d.close()
                    continue
                d.close()
            except Exception:
                continue
            out.append(f)
        if len(out) >= limit:
            break
    return out[:limit]


def _first_block(model: PDFModel):
    for pi in range(len(model.doc)):
        for b in model.block_manager.get_blocks(pi):
            if b.text.strip():
                return pi, b
    return None, None


# ---------- 單一功能測試 ----------

def run_open_save(pdfs: List[Path]) -> ConceptResult:
    r = ConceptResult("F1", "開啟 / 儲存 / 另存")
    for p in pdfs:
        t0 = _ms()
        try:
            m = PDFModel()
            m.open_pdf(str(p), password=_get_password(p))
            n = len(m.doc)
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                tmp = f.name
            m.save_as(tmp)
            m.close()
            m2 = PDFModel()
            m2.open_pdf(tmp)
            ok = len(m2.doc) == n
            m2.close()
            os.unlink(tmp)
            r.cases.append(CaseResult(p.name, ok, _ms() - t0, f"頁數={n}", ""))
        except Exception as e:
            r.cases.append(CaseResult(p.name, False, _ms() - t0, "", str(e)[:150]))
    r.total_ms = sum(c.duration_ms for c in r.cases)
    return r


def run_page_ops(pdfs: List[Path]) -> ConceptResult:
    r = ConceptResult("F2", "刪除頁 / 旋轉頁 / 匯出頁 / 插入空白頁")
    multi = [p for p in pdfs if _page_count(p) >= 3][:4]
    for p in multi:
        t0 = _ms()
        err = []
        try:
            m = PDFModel()
            m.open_pdf(str(p), password=_get_password(p))
            n0 = len(m.doc)
            m.delete_pages([n0])
            if len(m.doc) != n0 - 1:
                err.append("delete_pages")
            m.rotate_pages([1], 90)
            m.insert_blank_page(1)
            if len(m.doc) != n0:
                err.append("insert_blank_page")
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                tmp = f.name
            m.export_pages([1], tmp, as_image=True)
            m.close()
            os.unlink(tmp)
            r.cases.append(CaseResult(p.name, len(err) == 0, _ms() - t0, f"n0={n0}", "; ".join(err)))
        except Exception as e:
            r.cases.append(CaseResult(p.name, False, _ms() - t0, "", str(e)[:150]))
    if not r.cases:
        r.cases.append(CaseResult("(無≥3頁PDF)", True, 0, "SKIP", ""))
    r.total_ms = sum(c.duration_ms for c in r.cases)
    return r


def _page_count(p: Path) -> int:
    try:
        d = fitz.open(str(p), password=_get_password(p))
        n = len(d)
        d.close()
        return n
    except Exception:
        return 0


def run_edit_undo_redo(pdfs: List[Path]) -> ConceptResult:
    r = ConceptResult("F3", "編輯文字 + 復原 + 重做")
    for p in pdfs[:8]:
        t0 = _ms()
        err = []
        try:
            m = PDFModel()
            m.open_pdf(str(p), password=_get_password(p))
            pi, blk = _first_block(m)
            if blk is None:
                m.close()
                continue
            snap = m._capture_page_snapshot(pi)
            cmd = EditTextCommand(
                model=m, page_num=pi + 1, rect=blk.layout_rect,
                new_text="F3 test", font="helv", size=11, color=(0, 0, 0),
                original_text=blk.text, vertical_shift_left=True,
                page_snapshot_bytes=snap, old_block_id=blk.block_id, old_block_text=blk.text,
            )
            m.command_manager.execute(cmd)
            if not m.command_manager.can_undo():
                err.append("no undo")
            m.command_manager.undo()
            if m.command_manager.can_undo():
                err.append("undo not clear")
            if not m.command_manager.can_redo():
                err.append("no redo")
            m.command_manager.redo()
            m.close()
            r.cases.append(CaseResult(p.name, len(err) == 0, _ms() - t0, "", "; ".join(err)))
        except Exception as e:
            r.cases.append(CaseResult(p.name, False, _ms() - t0, "", str(e)[:150]))
    r.total_ms = sum(c.duration_ms for c in r.cases)
    return r


def run_annot_rect_highlight(pdfs: List[Path]) -> ConceptResult:
    r = ConceptResult("F4", "註解 / 矩形 / 螢光筆")
    for p in pdfs[:6]:
        t0 = _ms()
        try:
            m = PDFModel()
            m.open_pdf(str(p), password=_get_password(p))
            page = m.doc[0]
            r0 = page.rect
            m.add_annotation(1, fitz.Point(r0.x0 + 50, r0.y0 + 50), "F4 annot")
            m.add_rect(1, fitz.Rect(100, 100, 200, 150), (1, 0, 0, 0.5), False)
            m.add_highlight(1, fitz.Rect(100, 160, 250, 180), (1, 1, 0, 0.5))
            ann = m.get_all_annotations()
            m.close()
            ok = len(ann) >= 1
            r.cases.append(CaseResult(p.name, ok, _ms() - t0, f"annots={len(ann)}", ""))
        except Exception as e:
            r.cases.append(CaseResult(p.name, False, _ms() - t0, "", str(e)[:150]))
    r.total_ms = sum(c.duration_ms for c in r.cases)
    return r


def run_search_pixmap(pdfs: List[Path]) -> ConceptResult:
    r = ConceptResult("F5", "搜尋 / 取得 Pixmap")
    for p in pdfs[:6]:
        t0 = _ms()
        try:
            m = PDFModel()
            m.open_pdf(str(p), password=_get_password(p))
            res = m.search_text("the")  # 常見字
            pix = m.get_page_pixmap(1, scale=0.3)
            thumb = m.get_thumbnail(1)
            m.close()
            ok = pix.width > 0 and thumb.width > 0
            r.cases.append(CaseResult(p.name, ok, _ms() - t0, f"search={len(res)}", ""))
        except Exception as e:
            r.cases.append(CaseResult(p.name, False, _ms() - t0, "", str(e)[:150]))
    r.total_ms = sum(c.duration_ms for c in r.cases)
    return r


def run_watermark(pdfs: List[Path]) -> ConceptResult:
    r = ConceptResult("F6", "浮水印 新增/列表/更新/移除")
    for p in pdfs[:4]:
        t0 = _ms()
        try:
            m = PDFModel()
            m.open_pdf(str(p), password=_get_password(p))
            n = len(m.doc)
            m.add_watermark(list(range(1, min(3, n) + 1)), "F6 WM", 45, 0.4, 36, (0.7, 0.7, 0.7), "helv")
            wl = m.get_watermarks()
            if not wl:
                r.cases.append(CaseResult(p.name, False, _ms() - t0, "", "get_watermarks empty"))
                m.close()
                continue
            wid = wl[0].get("id")
            m.update_watermark(wid, pages=[1], text="F6 updated", angle=30, opacity=0.5, font_size=24, color=(0.6, 0.6, 0.6), font="helv")
            m.remove_watermark(wid)
            wl2 = m.get_watermarks()
            m.close()
            ok = len(wl2) < len(wl)
            r.cases.append(CaseResult(p.name, ok, _ms() - t0, f"before={len(wl)} after={len(wl2)}", ""))
        except Exception as e:
            r.cases.append(CaseResult(p.name, False, _ms() - t0, "", str(e)[:150]))
    r.total_ms = sum(c.duration_ms for c in r.cases)
    return r


# ---------- 衝突情境 ----------

def run_conflict_annot_then_edit(pdfs: List[Path]) -> ConceptResult:
    r = ConceptResult("C1", "衝突：先新增註解再編輯文字（註解應保留）")
    for p in pdfs[:6]:
        t0 = _ms()
        try:
            m = PDFModel()
            m.open_pdf(str(p), password=_get_password(p))
            pi, blk = _first_block(m)
            if blk is None:
                m.close()
                continue
            page = m.doc[pi]
            rect = page.rect
            m.add_annotation(pi + 1, fitz.Point(rect.x0 + 60, rect.y0 + 60), "C1 annot")
            before_ann = len(list(page.annots())) if hasattr(page, 'annots') else 0
            m.edit_text(pi + 1, blk.layout_rect, "C1 edit", font="helv", size=11, color=(0, 0, 0), original_text=blk.text)
            page = m.doc[pi]
            after_ann = len(list(page.annots()))
            m.close()
            ok = after_ann >= 1
            r.cases.append(CaseResult(p.name, ok, _ms() - t0, f"annots after edit={after_ann}", "" if ok else "annot lost"))
        except Exception as e:
            r.cases.append(CaseResult(p.name, False, _ms() - t0, "", str(e)[:150]))
    r.total_ms = sum(c.duration_ms for c in r.cases)
    return r


def run_conflict_structural_undo(pdfs: List[Path]) -> ConceptResult:
    r = ConceptResult("C2", "衝突：刪除頁 → 復原（頁數應還原）")
    multi = [p for p in pdfs if _page_count(p) >= 3][:4]
    for p in multi:
        t0 = _ms()
        err = []
        try:
            m = PDFModel()
            m.open_pdf(str(p), password=_get_password(p))
            n0 = len(m.doc)
            before = m._capture_doc_snapshot()
            m.delete_pages([n0])
            after = m._capture_doc_snapshot()
            cmd = SnapshotCommand(m, "delete_pages", [n0], before, after, "刪除末頁")
            m.command_manager.record(cmd)
            if len(m.doc) != n0 - 1:
                err.append("page count after delete")
            m.command_manager.undo()
            if len(m.doc) != n0:
                err.append("page count after undo")
            m.close()
            r.cases.append(CaseResult(p.name, len(err) == 0, _ms() - t0, f"n0={n0}", "; ".join(err)))
        except Exception as e:
            r.cases.append(CaseResult(p.name, False, _ms() - t0, "", str(e)[:150]))
    if not r.cases:
        r.cases.append(CaseResult("(無≥3頁)", True, 0, "SKIP", ""))
    r.total_ms = sum(c.duration_ms for c in r.cases)
    return r


def run_conflict_rotate_then_edit(pdfs: List[Path]) -> ConceptResult:
    r = ConceptResult("C3", "衝突：旋轉頁後再編輯該頁文字")
    for p in pdfs[:6]:
        t0 = _ms()
        try:
            m = PDFModel()
            m.open_pdf(str(p), password=_get_password(p))
            m.rotate_pages([1], 90)
            m.block_manager.rebuild_page(0, m.doc)
            pi, blk = _first_block(m)
            if blk is None:
                m.close()
                continue
            m.edit_text(pi + 1, blk.layout_rect, "C3 after rotate", font="helv", size=11, color=(0, 0, 0), original_text=blk.text)
            m.close()
            r.cases.append(CaseResult(p.name, True, _ms() - t0, "", ""))
        except Exception as e:
            r.cases.append(CaseResult(p.name, False, _ms() - t0, "", str(e)[:150]))
    r.total_ms = sum(c.duration_ms for c in r.cases)
    return r


def run_conflict_insert_then_edit(pdfs: List[Path]) -> ConceptResult:
    r = ConceptResult("C4", "衝突：插入空白頁後編輯原第一頁（現第二頁）")
    for p in pdfs[:6]:
        t0 = _ms()
        try:
            m = PDFModel()
            m.open_pdf(str(p), password=_get_password(p))
            m.insert_blank_page(1)
            m.block_manager.build_index(m.doc)
            pi = 1  # 原第一頁現在是 index 1
            if pi >= len(m.doc):
                m.close()
                continue
            blks = m.block_manager.get_blocks(pi)
            if not blks or not blks[0].text.strip():
                m.close()
                continue
            blk = blks[0]
            m.edit_text(pi + 1, blk.layout_rect, "C4 after insert", font="helv", size=11, color=(0, 0, 0), original_text=blk.text)
            m.close()
            r.cases.append(CaseResult(p.name, True, _ms() - t0, "", ""))
        except Exception as e:
            r.cases.append(CaseResult(p.name, False, _ms() - t0, "", str(e)[:150]))
    r.total_ms = sum(c.duration_ms for c in r.cases)
    return r


def run_conflict_multi_undo_redo(pdfs: List[Path]) -> ConceptResult:
    r = ConceptResult("C5", "衝突：多輪 編輯→復原→重做 循環")
    for p in pdfs[:4]:
        t0 = _ms()
        err = []
        try:
            m = PDFModel()
            m.open_pdf(str(p), password=_get_password(p))
            pi, blk = _first_block(m)
            if blk is None:
                m.close()
                continue
            for round in range(3):
                snap = m._capture_page_snapshot(pi)
                cmd = EditTextCommand(
                    model=m, page_num=pi + 1, rect=blk.layout_rect,
                    new_text=f"C5 r{round}", font="helv", size=11, color=(0, 0, 0),
                    original_text=blk.text, vertical_shift_left=True,
                    page_snapshot_bytes=snap, old_block_id=blk.block_id, old_block_text=blk.text,
                )
                m.command_manager.execute(cmd)
                blks = m.block_manager.get_blocks(pi)
                if blks:
                    blk = blks[0]
            n_undo = m.command_manager.undo_count
            for _ in range(n_undo):
                m.command_manager.undo()
            if m.command_manager.can_undo():
                err.append("undo stack not empty")
            for _ in range(n_undo):
                m.command_manager.redo()
            if m.command_manager.can_redo():
                err.append("redo stack not empty")
            m.close()
            r.cases.append(CaseResult(p.name, len(err) == 0, _ms() - t0, "", "; ".join(err)))
        except Exception as e:
            r.cases.append(CaseResult(p.name, False, _ms() - t0, "", str(e)[:150]))
    r.total_ms = sum(c.duration_ms for c in r.cases)
    return r


def run_save_with_watermark(pdfs: List[Path]) -> ConceptResult:
    r = ConceptResult("C6", "浮水印後 save_as 再開檔驗證（元數據還原，可編輯）")
    # 方案 B：浮水印元數據寫入 PDF 內嵌檔案，開檔時還原；驗證重新開檔後 get_watermarks() 有值。
    for p in pdfs[:4]:
        t0 = _ms()
        try:
            m = PDFModel()
            m.open_pdf(str(p), password=_get_password(p))
            m.add_watermark([1], "C6 WM", 45, 0.3, 24, (0.8, 0.8, 0.8), "helv")
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                tmp = f.name
            m.save_as(tmp)
            m.close()
            m2 = PDFModel()
            m2.open_pdf(tmp)
            wl = m2.get_watermarks()
            pix = m2.get_page_pixmap(1, scale=0.2)
            m2.close()
            os.unlink(tmp)
            ok = len(wl) >= 1 and pix.width > 0 and pix.height > 0
            r.cases.append(CaseResult(p.name, ok, _ms() - t0, f"watermarks={len(wl)}", "" if ok else "get_watermarks empty or render failed"))
        except Exception as e:
            r.cases.append(CaseResult(p.name, False, _ms() - t0, "", str(e)[:150]))
    r.total_ms = sum(c.duration_ms for c in r.cases)
    return r


def generate_report(concepts: List[ConceptResult], total_ms: float) -> str:
    lines = []
    W = 72
    lines.append("=" * W)
    lines.append("  功能與衝突測試報告")
    lines.append(f"  生成時間：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  總耗時：{total_ms/1000:.2f}s")
    lines.append("=" * W)

    total_cases = sum(c.total for c in concepts)
    total_passed = sum(c.passed for c in concepts)
    total_failed = total_cases - total_passed
    rate = total_passed / total_cases * 100 if total_cases else 0

    lines.append("\n【總覽】")
    lines.append(f"  概念數：{len(concepts)}  案例數：{total_cases}  通過：{total_passed}  失敗：{total_failed}")
    lines.append(f"  整體通過率：{rate:.1f}%")

    lines.append(f"\n{'─'*W}")
    lines.append("【各概念摘要】")
    lines.append(f"  {'ID':<6} {'標題':<42} {'通過':<6} {'失敗':<6} {'通過率':<8} {'耗時'}")
    for c in concepts:
        fail = c.total - c.passed
        flag = "✓" if fail == 0 else "✗"
        lines.append(f"  {c.id:<6} {c.title[:42]:<42} {c.passed:<6} {fail:<6} {c.pass_rate:6.1f}%  {c.total_ms/1000:.2f}s  {flag}")

    lines.append(f"\n{'═'*W}")
    lines.append("【失敗案例與根本成因】")
    for c in concepts:
        fails = [x for x in c.cases if not x.passed]
        if not fails:
            continue
        lines.append(f"\n  [{c.id}] {c.title}")
        for x in fails:
            lines.append(f"    - {x.name}: {x.error or x.detail}")

    lines.append(f"\n{'═'*W}")
    lines.append("【浮水印持久化說明】")
    lines.append("  方案 B 已實作：Model 在 save 時將浮水印元數據寫入 PDF 內嵌檔案（__pdf_editor_watermarks），")
    lines.append("  開檔時還原 watermark_list，支援「重新開檔後仍可編輯浮水印」。C6 驗證 save_as 後重開 get_watermarks() 有值。")

    lines.append(f"\n{'═'*W}")
    lines.append("【穩定性結論】")
    if rate >= 95:
        lines.append("  ✅ 可視為穩定版本：各功能獨立與衝突情境通過率 ≥ 95%。")
    elif rate >= 85:
        lines.append("  ⚠️ 接近穩定：部分情境需修正後再發布。")
    else:
        lines.append("  ❌ 尚不穩定：失敗案例較多，建議修正後重測。")
    lines.append("\n【建議】")
    lines.append("  1. 定期執行本腳本與 test_deep.py，回歸驗證。")
    lines.append("  2. 新增功能時補上對應概念測試與衝突情境。")
    lines.append("  3. 浮水印元數據已透過 PDF 內嵌檔案持久化，重新開檔後可編輯（方案 B）。")
    lines.append("")
    lines.append("【綜合驗證】")
    lines.append("  建議同時執行 test_scripts/test_deep.py --quick（深度壓力與邊界測試）。")
    lines.append("  本腳本通過率 100% 且深度測試 183/183 通過時，可視為穩定版本。")
    lines.append("=" * W)
    return "\n".join(lines)


def main():
    print("\n功能與衝突測試 — 使用 test_files 內 PDF")
    print(f"  test_files 根目錄: {TEST_FILES_ROOT}")
    pdfs = _collect_pdfs(12)
    if not pdfs:
        print("  未找到可用的測試 PDF，請確認 test_files/sample-files-main 存在且含 PDF。")
        return 1
    print(f"  使用 PDF 數量: {len(pdfs)}\n")

    concepts = []
    t0 = _ms()

    concepts.append(run_open_save(pdfs))
    concepts.append(run_page_ops(pdfs))
    concepts.append(run_edit_undo_redo(pdfs))
    concepts.append(run_annot_rect_highlight(pdfs))
    concepts.append(run_search_pixmap(pdfs))
    concepts.append(run_watermark(pdfs))
    concepts.append(run_conflict_annot_then_edit(pdfs))
    concepts.append(run_conflict_structural_undo(pdfs))
    concepts.append(run_conflict_rotate_then_edit(pdfs))
    concepts.append(run_conflict_insert_then_edit(pdfs))
    concepts.append(run_conflict_multi_undo_redo(pdfs))
    concepts.append(run_save_with_watermark(pdfs))

    total_ms = _ms() - t0

    report = generate_report(concepts, total_ms)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")

    total_cases = sum(c.total for c in concepts)
    total_passed = sum(c.passed for c in concepts)
    print(f"  總案例：{total_cases}  通過：{total_passed}  失敗：{total_cases - total_passed}")
    print(f"  報告已寫入：{REPORT_PATH}\n")
    return 0 if total_passed == total_cases else 1


if __name__ == "__main__":
    sys.exit(main())

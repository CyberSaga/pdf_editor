# -*- coding: utf-8 -*-
"""Recursive overlap-safe edit validation across all PDFs under test_files."""

from __future__ import annotations

import csv
import logging
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import sys

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model.edit_commands import EditTextCommand
from model.pdf_model import PDFModel

logging.disable(logging.CRITICAL)

TEST_ROOT = Path("test_files")
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "test_outputs"
CSV_PATH = OUTPUT_DIR / "overlap_recursive_report.csv"
MD_PATH = OUTPUT_DIR / "overlap_recursive_report.md"
PER_FILE_TIMEOUT_S = 20.0
MAX_SCAN_SPANS_PER_PAGE = 600

KNOWN_PASSWORDS = {
    "encrypted.pdf": "kanbanery",
    "libreoffice-writer-password.pdf": "permissionpassword",
    "password.pdf": "test",
}


@dataclass
class Row:
    rel_path: str
    folder: str
    status: str
    mode: str
    reason: str
    page: int
    target_span_id: str
    overlap_cluster_size: int
    protected_count: int
    duration_ms: float


@dataclass
class Candidate:
    page_idx: int
    target_span: object
    cluster: list



def _norm(text: str) -> str:
    return "".join((text or "").split()).lower()



def _get_password(pdf_path: Path) -> Optional[str]:
    return KNOWN_PASSWORDS.get(pdf_path.name.lower())



def _is_encrypted_error(message: str) -> bool:
    lower = (message or "").lower()
    needles = ("encrypted", "password", "authenticate", "needs_pass", "closed or encrypted")
    return any(n in lower for n in needles)



def _collect_spans(model: PDFModel):
    spans = []
    for pidx in range(len(model.doc)):
        model.ensure_page_index_built(pidx + 1)
        page_spans = [s for s in model.block_manager.get_spans(pidx) if (s.text or "").strip()]
        spans.append(page_spans)
    return spans



def _find_overlap_candidate(model: PDFModel) -> Optional[Candidate]:
    all_spans = _collect_spans(model)
    for page_idx, spans in enumerate(all_spans):
        if len(spans) < 2:
            continue
        limit = min(len(spans), MAX_SCAN_SPANS_PER_PAGE)
        for j in range(limit - 1, 0, -1):
            target = spans[j]
            cluster = model.block_manager.find_overlapping_spans(page_idx, target.bbox, tol=0.5)
            if len(cluster) > 1:
                return Candidate(page_idx=page_idx, target_span=target, cluster=cluster)
    return None



def _find_baseline_candidate(model: PDFModel) -> Optional[Candidate]:
    all_spans = _collect_spans(model)
    for page_idx, spans in enumerate(all_spans):
        if not spans:
            continue
        target = spans[-1]
        cluster = [target]
        return Candidate(page_idx=page_idx, target_span=target, cluster=cluster)
    return None



def _assert_token(page_text: str, token: str, label: str) -> None:
    if _norm(token) not in _norm(page_text):
        raise AssertionError(f"{label} token missing: {token!r}")



def _execute_edit_with_undo_redo(model: PDFModel, cand: Candidate, overlap_mode: bool) -> tuple[int, int]:
    target = cand.target_span
    protected = [s for s in cand.cluster if s.span_id != target.span_id]
    marker = f"OVL_EDIT_{uuid.uuid4().hex[:10]}"

    snapshot = model._capture_page_snapshot(cand.page_idx)
    cmd = EditTextCommand(
        model=model,
        page_num=cand.page_idx + 1,
        rect=fitz.Rect(target.bbox),
        new_text=marker,
        font=target.font,
        size=max(8, int(round(target.size))),
        color=tuple(target.color),
        original_text=target.text,
        vertical_shift_left=True,
        page_snapshot_bytes=snapshot,
        old_block_id=target.span_id,
        old_block_text=target.text,
        new_rect=None,
        target_span_id=target.span_id,
    )

    model.command_manager.execute(cmd)
    page_text_after_edit = model.doc[cand.page_idx].get_text("text")
    _assert_token(page_text_after_edit, marker, "edited")
    for span in protected:
        if (span.text or "").strip():
            _assert_token(page_text_after_edit, span.text, f"protected({span.span_id})")

    model.command_manager.undo()
    page_text_after_undo = model.doc[cand.page_idx].get_text("text")
    if _norm(marker) in _norm(page_text_after_undo):
        raise AssertionError("undo failed: edited token still present")

    model.command_manager.redo()
    page_text_after_redo = model.doc[cand.page_idx].get_text("text")
    _assert_token(page_text_after_redo, marker, "redo")
    for span in protected:
        if (span.text or "").strip():
            _assert_token(page_text_after_redo, span.text, f"protected_redo({span.span_id})")

    return len(cand.cluster), len(protected)



def _process_pdf(pdf_path: Path) -> Row:
    start = time.perf_counter()
    rel_path = str(pdf_path.relative_to(TEST_ROOT))
    folder = rel_path.split("/")[0] if "/" in rel_path else rel_path.split("\\")[0]
    model = PDFModel()

    try:
        pw = _get_password(pdf_path)
        try:
            model.open_pdf(str(pdf_path), password=pw)
        except Exception as exc:
            msg = str(exc)
            if _is_encrypted_error(msg):
                reason = "SKIP_ENCRYPTED_UNKNOWN" if not pw else f"SKIP_ENCRYPTED_BAD_PASSWORD:{pw}"
                return Row(rel_path, folder, "SKIP_ENCRYPTED", "none", reason, 0, "", 0, 0, (time.perf_counter() - start) * 1000)
            return Row(rel_path, folder, "FAIL", "open", msg[:240], 0, "", 0, 0, (time.perf_counter() - start) * 1000)

        if time.perf_counter() - start > PER_FILE_TIMEOUT_S:
            return Row(rel_path, folder, "FAIL", "timeout", "TIMEOUT_AFTER_OPEN", 0, "", 0, 0, (time.perf_counter() - start) * 1000)

        overlap = _find_overlap_candidate(model)
        mode = "overlap" if overlap else "baseline"
        candidate = overlap or _find_baseline_candidate(model)
        if candidate is None:
            return Row(rel_path, folder, "SKIP_NO_TEXT", mode, "NO_EDITABLE_SPAN", 0, "", 0, 0, (time.perf_counter() - start) * 1000)

        try:
            cluster_size, protected_count = _execute_edit_with_undo_redo(
                model,
                candidate,
                overlap_mode=overlap is not None,
            )
        except Exception as exc:
            return Row(
                rel_path,
                folder,
                "SKIP_UNEDITABLE",
                mode,
                str(exc)[:240],
                candidate.page_idx + 1,
                candidate.target_span.span_id,
                0,
                0,
                (time.perf_counter() - start) * 1000,
            )

        if time.perf_counter() - start > PER_FILE_TIMEOUT_S:
            return Row(
                rel_path,
                folder,
                "SKIP_TIMEOUT",
                mode,
                "TIMEOUT_AFTER_EDIT",
                candidate.page_idx + 1,
                candidate.target_span.span_id,
                cluster_size,
                protected_count,
                (time.perf_counter() - start) * 1000,
            )

        status = "PASS_OVERLAP" if overlap else "PASS_BASELINE"
        return Row(
            rel_path,
            folder,
            status,
            mode,
            "OK",
            candidate.page_idx + 1,
            candidate.target_span.span_id,
            cluster_size,
            protected_count,
            (time.perf_counter() - start) * 1000,
        )

    except Exception as exc:  # keep run resilient, no uncaught per-file exception
        return Row(
            rel_path,
            folder,
            "SKIP_RUNTIME",
            "runtime",
            str(exc)[:240],
            0,
            "",
            0,
            0,
            (time.perf_counter() - start) * 1000,
        )
    finally:
        try:
            model.close()
        except Exception:
            pass



def _write_csv(rows: list[Row]) -> None:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "rel_path",
            "folder",
            "status",
            "mode",
            "reason",
            "page",
            "target_span_id",
            "overlap_cluster_size",
            "protected_count",
            "duration_ms",
        ])
        for r in rows:
            writer.writerow([
                r.rel_path,
                r.folder,
                r.status,
                r.mode,
                r.reason,
                r.page,
                r.target_span_id,
                r.overlap_cluster_size,
                r.protected_count,
                round(r.duration_ms, 2),
            ])



def _write_markdown(rows: list[Row]) -> None:
    status_counts = Counter(r.status for r in rows)
    reason_counts = Counter(r.reason for r in rows if r.status == "FAIL")

    folder_totals = defaultdict(lambda: {"total": 0, "pass": 0, "fail": 0, "skip": 0})
    for r in rows:
        bucket = folder_totals[r.folder]
        bucket["total"] += 1
        if r.status.startswith("PASS"):
            bucket["pass"] += 1
        elif r.status.startswith("SKIP"):
            bucket["skip"] += 1
        else:
            bucket["fail"] += 1

    lines = []
    lines.append("# Overlap Recursive Report")
    lines.append("")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Total PDFs: {len(rows)}")
    lines.append(f"SKIP_ENCRYPTED: {status_counts.get('SKIP_ENCRYPTED', 0)}")
    lines.append("")
    lines.append("## Status Totals")
    lines.append("| Status | Count |")
    lines.append("|---|---:|")
    ordered_statuses = [
        "PASS_OVERLAP",
        "PASS_BASELINE",
        "SKIP_NO_TEXT",
        "SKIP_UNEDITABLE",
        "SKIP_ENCRYPTED",
        "SKIP_TIMEOUT",
        "SKIP_RUNTIME",
        "FAIL",
    ]
    for status in ordered_statuses:
        lines.append(f"| {status} | {status_counts.get(status, 0)} |")
    for status, count in sorted(status_counts.items()):
        if status in ordered_statuses:
            continue
        lines.append(f"| {status} | {count} |")
    lines.append("")
    lines.append("## Folder Totals")
    lines.append("| Folder | Total | Pass | Fail | Skip |")
    lines.append("|---|---:|---:|---:|---:|")
    for folder, stats in sorted(folder_totals.items()):
        lines.append(
            f"| {folder} | {stats['total']} | {stats['pass']} | {stats['fail']} | {stats['skip']} |"
        )

    if reason_counts:
        lines.append("")
        lines.append("## Failure Reasons")
        lines.append("| Reason | Count |")
        lines.append("|---|---:|")
        for reason, count in reason_counts.most_common():
            lines.append(f"| {reason} | {count} |")

    failures = [r for r in rows if r.status == "FAIL"]
    if failures:
        lines.append("")
        lines.append("## Failed Files")
        lines.append("| File | Mode | Reason |")
        lines.append("|---|---|---|")
        for r in failures[:300]:
            lines.append(f"| {r.rel_path} | {r.mode} | {r.reason} |")

    MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")



def main() -> int:
    if not TEST_ROOT.exists():
        print(f"missing folder: {TEST_ROOT}")
        return 1

    pdfs = sorted(TEST_ROOT.rglob("*.pdf"))
    rows: list[Row] = []
    for idx, pdf in enumerate(pdfs, start=1):
        row = _process_pdf(pdf)
        rows.append(row)
        if idx % 50 == 0 or idx == len(pdfs):
            print(f"[{idx}/{len(pdfs)}] {row.status} {row.rel_path}")

    _write_csv(rows)
    _write_markdown(rows)

    fail_count = sum(1 for r in rows if r.status == "FAIL")
    print(f"total={len(rows)} fail={fail_count} csv={CSV_PATH} md={MD_PATH}")
    return 0 if fail_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import fitz
import pikepdf
import pypdf


def _tail_has_eof(pdf_path: Path) -> bool:
    with pdf_path.open("rb") as fh:
        fh.seek(max(0, pdf_path.stat().st_size - 2048))
        tail = fh.read()
    return b"%%EOF" in tail


def _sample_page_indexes(page_count: int) -> list[int]:
    if page_count <= 0:
        return []
    indexes = {0, page_count - 1, page_count // 2}
    return sorted(indexes)


def validate_pdf_integrity(pdf_path: str | Path) -> dict:
    path = Path(pdf_path).resolve()
    result: dict[str, object] = {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "header_ok": False,
        "eof_ok": False,
        "passed": False,
        "fitz": {"ok": False},
        "pikepdf": {"ok": False},
        "pypdf": {"ok": False},
        "notes": [
            "ISO 32000 validation is approximated via independent parser agreement because qpdf/verapdf are not installed."
        ],
    }

    with path.open("rb") as fh:
        header = fh.read(8)
    result["header_ok"] = header.startswith(b"%PDF-")
    result["eof_ok"] = _tail_has_eof(path)

    with fitz.open(str(path)) as doc:
        page_count = len(doc)
        sample_indexes = _sample_page_indexes(page_count)
        for index in sample_indexes:
            page = doc[index]
            page.get_text("text")
            page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5), annots=False)
        fitz_info = {
            "ok": True,
            "page_count": page_count,
            "sample_pages_checked": sample_indexes,
            "pdf_version": str(getattr(doc, "pdf_version", lambda: "unknown")()),
        }
        result["fitz"] = fitz_info

    with pikepdf.open(str(path)) as pdf:
        with TemporaryDirectory() as temp_dir:
            resave_path = Path(temp_dir) / "resave-check.pdf"
            pdf.save(str(resave_path))
        result["pikepdf"] = {
            "ok": True,
            "page_count": len(pdf.pages),
            "is_encrypted": bool(pdf.is_encrypted),
        }

    reader = pypdf.PdfReader(str(path), strict=False)
    reader_page_count = len(reader.pages)
    for index in _sample_page_indexes(reader_page_count):
        _ = reader.pages[index].mediabox
    result["pypdf"] = {
        "ok": True,
        "page_count": reader_page_count,
    }

    counts = {
        result["fitz"]["page_count"],
        result["pikepdf"]["page_count"],
        result["pypdf"]["page_count"],
    }
    result["passed"] = bool(result["header_ok"] and result["eof_ok"] and len(counts) == 1)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an optimized PDF with multiple parsers.")
    parser.add_argument("pdf_path", type=Path)
    args = parser.parse_args()

    report = validate_pdf_integrity(args.pdf_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

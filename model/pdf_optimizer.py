from __future__ import annotations

"""
Internal optimizer implementation for `檔案 > 另存為最佳化的副本`.

Design constraints:
- Latency-first: preset `平衡` must be fast for large PDFs.
- Never mutate the live active `fitz.Document` in-place; always operate on a disposable working document.
- Avoid cloning live bytes for clean file-backed sessions (reopen from path instead).
- Image rewrite is the dominant cost; parallelize when safe, otherwise fall back to serial mode.
- Post-save packaging (linearize/object streams) is optional and only run when requested.

`PDFModel` is the public facade; it re-exports the schema types and delegates to this module.
"""

import io
import json
import logging
import os
import shutil
import sys
import uuid
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

import fitz

try:
    from PIL import Image
except ImportError:  # pragma: no cover - optional dependency
    Image = None

try:
    import pikepdf
except ImportError:  # pragma: no cover - optional dependency
    pikepdf = None

if TYPE_CHECKING:
    from model.pdf_model import PDFModel

logger = logging.getLogger(__name__)
logging.getLogger("PIL").setLevel(logging.INFO)
logging.getLogger("PIL.PngImagePlugin").setLevel(logging.INFO)

_IMAGE_REWRITE_WORKER_DOC: fitz.Document | None = None
_MIN_PARALLEL_IMAGE_REWRITES = 4
_MAX_PARALLEL_IMAGE_WORKERS = 4


@dataclass(frozen=True)
class PdfOptimizeOptions:
    preset: str = "平衡"
    optimize_images: bool = True
    image_dpi_target: int = 150
    image_dpi_threshold: int = 225
    image_jpeg_quality: int = 60
    optimize_color_images: bool = True
    optimize_gray_images: bool = True
    optimize_bitonal_images: bool = True
    optimize_fonts: bool = True
    subset_fonts: bool = True
    remove_metadata: bool = False
    remove_xml_metadata: bool = False
    content_cleanup: bool = True
    garbage_level: int = 3
    deflate_streams: bool = True
    deflate_images: bool = True
    deflate_fonts: bool = True
    use_object_streams: bool = True
    linearize: bool = False
    compression_effort: int = 6


@dataclass(frozen=True)
class PdfAuditItem:
    label: str
    count: int
    bytes_used: int
    percent: float


@dataclass(frozen=True)
class PdfAuditReport:
    pdf_version: str
    compatibility: str
    total_bytes: int
    items: list[PdfAuditItem]


@dataclass(frozen=True)
class PdfOptimizationResult:
    output_path: str
    original_bytes: int
    optimized_bytes: int
    bytes_saved: int
    percent_saved: float
    applied_preset: str
    applied_summary: list[str]


def _init_image_rewrite_worker(source_path: str) -> None:
    global _IMAGE_REWRITE_WORKER_DOC
    _IMAGE_REWRITE_WORKER_DOC = fitz.open(source_path)


def _classify_worker_pil_image_mode(mode: str) -> str:
    normalized = (mode or "").upper()
    if normalized == "1":
        return "bitonal"
    if normalized in {"L", "LA"}:
        return "gray"
    return "color"


def _transcode_image_payload(
    image_bytes: bytes,
    max_dpi: float,
    settings: dict[str, int | bool],
) -> bytes | None:
    if not image_bytes:
        return None
    image = Image.open(io.BytesIO(image_bytes))
    try:
        image.load()
        family = _classify_worker_pil_image_mode(getattr(image, "mode", ""))
        if family == "color" and not settings["optimize_color_images"]:
            return None
        if family == "gray" and not settings["optimize_gray_images"]:
            return None
        if family == "bitonal" and not settings["optimize_bitonal_images"]:
            return None

        rewritten = image
        dpi_threshold = max(int(settings["image_dpi_threshold"]), 1)
        dpi_target = max(int(settings["image_dpi_target"]), 1)
        if max_dpi > dpi_threshold:
            scale = min(1.0, dpi_target / max_dpi)
            new_size = (
                max(1, int(round(image.width * scale))),
                max(1, int(round(image.height * scale))),
            )
            rewritten = image.resize(new_size, Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        has_alpha = "A" in ((rewritten.mode or "").upper())
        if family == "bitonal" or has_alpha:
            rewritten.save(buf, format="PNG", optimize=True)
        else:
            target_mode = "L" if family == "gray" else "RGB"
            rewritten.convert(target_mode).save(
                buf,
                format="JPEG",
                quality=int(settings["image_jpeg_quality"]),
                optimize=True,
            )
        return buf.getvalue()
    finally:
        try:
            image.close()
        except Exception:
            pass


def _rewrite_source_image_task(task: tuple[int, float, dict[str, int | bool]]) -> tuple[int, bytes | None, str | None]:
    xref, max_dpi, settings = task
    try:
        if _IMAGE_REWRITE_WORKER_DOC is None:
            raise RuntimeError("image rewrite worker document is not initialized")
        image_info = _IMAGE_REWRITE_WORKER_DOC.extract_image(int(xref))
        image_bytes = image_info.get("image")
        rewritten = _transcode_image_payload(image_bytes, float(max_dpi), settings)
        return int(xref), rewritten, None
    except Exception as exc:
        return int(xref), None, str(exc)


def _rewrite_extracted_image_task(
    task: tuple[int, int, float, bytes, dict[str, int | bool]]
) -> tuple[int, int, bytes | None, str | None]:
    xref, page_index, max_dpi, image_bytes, settings = task
    try:
        rewritten = _transcode_image_payload(image_bytes, float(max_dpi), settings)
        return int(xref), int(page_index), rewritten, None
    except Exception as exc:
        return int(xref), int(page_index), None, str(exc)


def preset_optimize_options(preset: str) -> PdfOptimizeOptions:
    normalized = (preset or "").strip()
    if normalized == "快速":
        return PdfOptimizeOptions(
            preset="快速",
            image_dpi_target=220,
            image_dpi_threshold=300,
            image_jpeg_quality=78,
            remove_metadata=False,
            remove_xml_metadata=False,
            garbage_level=2,
            use_object_streams=False,
            linearize=False,
            compression_effort=3,
        )
    if normalized == "極致壓縮":
        return PdfOptimizeOptions(
            preset="極致壓縮",
            image_dpi_target=110,
            image_dpi_threshold=165,
            image_jpeg_quality=42,
            remove_metadata=True,
            remove_xml_metadata=True,
            garbage_level=4,
            use_object_streams=False,
            linearize=True,
            compression_effort=9,
        )
    return PdfOptimizeOptions()


def normalize_optimize_options(options: PdfOptimizeOptions) -> PdfOptimizeOptions:
    if options.linearize and options.use_object_streams:
        return replace(options, use_object_streams=False)
    return options


def resolve_file_backed_optimize_source(model: PDFModel, session_id: str | None) -> Path | None:
    if not session_id or not model.doc:
        return None
    session = model._sessions_by_id.get(session_id)
    if session is None or model.session_has_unsaved_changes(session_id):
        return None
    if getattr(model.doc, "needs_pass", False):
        return None
    source_path = Path(session.original_path).resolve()
    doc_name = getattr(model.doc, "name", "") or ""
    if not doc_name:
        return None
    try:
        if Path(doc_name).resolve() != source_path:
            return None
    except OSError:
        return None
    if not source_path.exists():
        return None
    return source_path


def current_document_size_bytes(model: PDFModel, session_id: str | None) -> int:
    if not model.doc:
        raise RuntimeError("沒有可最佳化的 PDF")
    source_path = model._resolve_file_backed_optimize_source(session_id)
    if source_path is not None:
        return source_path.stat().st_size
    return len(model.doc.tobytes(garbage=0, no_new_id=1))


def build_working_doc_for_optimized_copy(model: PDFModel, session_id: str | None) -> fitz.Document:
    """
    Optimize-copy pipeline:
      live doc -> disposable working doc -> tool save prep
    Prefer reopening the clean source file to avoid cloning the live doc bytes.
    """
    if not model.doc:
        raise RuntimeError("沒有可最佳化的 PDF")
    source_path = model._resolve_file_backed_optimize_source(session_id)
    if source_path is not None:
        working_doc = fitz.open(str(source_path))
    else:
        working_doc = fitz.open("pdf", model.doc.tobytes(garbage=0, no_new_id=1))
    prepared_doc = model.tools.prepare_doc_for_save(session_id, working_doc) if session_id else None
    if prepared_doc is None:
        return working_doc
    if prepared_doc is not working_doc:
        working_doc.close()
    return prepared_doc


def make_active_audit_cache_key(model: PDFModel) -> tuple | None:
    session_id = model.get_active_session_id()
    if not session_id or not model.doc:
        return None
    session = model._sessions_by_id.get(session_id)
    if session is None:
        return None
    source_path = model._resolve_file_backed_optimize_source(session_id)
    if source_path is not None:
        stat = source_path.stat()
        return ("file", session_id, stat.st_size, stat.st_mtime_ns, len(model.doc), model.edit_count)
    return ("memory", session_id, len(model.doc), model.doc.xref_length(), model.edit_count)


def blank_metadata_dict(doc: fitz.Document) -> dict[str, str]:
    metadata = doc.metadata or {}
    if not metadata:
        return {
            "author": "",
            "producer": "",
            "creator": "",
            "title": "",
            "subject": "",
            "keywords": "",
            "trapped": "",
            "creationDate": "",
            "modDate": "",
        }
    return {key: "" for key in metadata.keys()}


def xref_size_bytes(doc: fitz.Document, xref: int) -> int:
    size = 0
    try:
        obj = doc.xref_object(xref, compressed=0, ascii=0)
        if obj:
            size += len(obj.encode("utf-8", "ignore"))
    except Exception:
        pass
    try:
        if doc.xref_is_stream(xref):
            size += len(doc.xref_stream_raw(xref) or b"")
    except Exception:
        pass
    return size


def build_pdf_audit_report(model: PDFModel, doc: fitz.Document | None = None) -> PdfAuditReport:
    target_doc = doc if doc is not None else model.doc
    if target_doc is None:
        raise RuntimeError("沒有可審計的 PDF")
    cache_key = None if doc is not None else model._make_active_audit_cache_key()
    if cache_key is not None and cache_key == model._audit_report_cache_key and model._audit_report_cache_value is not None:
        return model._audit_report_cache_value

    source_path = None if doc is not None else model._resolve_file_backed_optimize_source(model.get_active_session_id())
    if source_path is not None:
        total_bytes = source_path.stat().st_size
    else:
        total_bytes = len(target_doc.tobytes(garbage=0))
    image_xrefs: set[int] = set()
    font_xrefs: set[int] = set()
    content_xrefs: set[int] = set()

    for page_index in range(len(target_doc)):
        page = target_doc[page_index]
        try:
            content_xrefs.update(int(xref) for xref in page.get_contents() if int(xref) > 0)
        except Exception:
            pass
        try:
            image_xrefs.update(int(item[0]) for item in page.get_images(full=True) if int(item[0]) > 0)
        except Exception:
            pass
        try:
            font_xrefs.update(int(item[0]) for item in page.get_fonts(full=True) if int(item[0]) > 0)
        except Exception:
            pass

    image_bytes = sum(model._xref_size_bytes(target_doc, xref) for xref in image_xrefs)
    font_bytes = sum(model._xref_size_bytes(target_doc, xref) for xref in font_xrefs)
    content_bytes = sum(model._xref_size_bytes(target_doc, xref) for xref in content_xrefs)
    metadata_payload = json.dumps(target_doc.metadata or {}, ensure_ascii=False).encode("utf-8")
    xml_metadata = target_doc.get_xml_metadata() or ""
    overhead_bytes = len(metadata_payload) + len(xml_metadata.encode("utf-8", "ignore"))

    known_bytes = image_bytes + font_bytes + content_bytes + overhead_bytes
    other_bytes = max(0, total_bytes - known_bytes)
    items = [
        PdfAuditItem(
            label=label,
            count=count,
            bytes_used=bytes_used,
            percent=(bytes_used / total_bytes * 100.0) if total_bytes else 0.0,
        )
        for label, count, bytes_used in [
            ("圖片", len(image_xrefs), image_bytes),
            ("內容串流", len(content_xrefs), content_bytes),
            ("字體", len(font_xrefs), font_bytes),
            ("文件開銷", 1 if overhead_bytes else 0, overhead_bytes),
            ("其他/未分類", 1 if other_bytes else 0, other_bytes),
        ]
    ]
    version = getattr(target_doc, "pdf_version", lambda: "")()
    if not version:
        version = "未知"
    report = PdfAuditReport(
        pdf_version=str(version),
        compatibility="保留現有",
        total_bytes=total_bytes,
        items=items,
    )
    if cache_key is not None:
        model._audit_report_cache_key = cache_key
        model._audit_report_cache_value = report
    return report


def apply_optimize_options(
    model: PDFModel,
    working_doc: fitz.Document,
    options: PdfOptimizeOptions,
    source_path: Path | None = None,
) -> None:
    if options.content_cleanup:
        for page_index in range(len(working_doc)):
            try:
                working_doc[page_index].clean_contents()
            except Exception as exc:
                logger.warning("clean_contents 失敗（頁面 %s）: %s", page_index + 1, model._safe_exc_message(exc))

    if options.remove_metadata:
        working_doc.set_metadata(model._blank_metadata_dict(working_doc))
    if options.remove_xml_metadata:
        try:
            working_doc.del_xml_metadata()
        except Exception as exc:
            logger.warning("移除 XML metadata 失敗: %s", model._safe_exc_message(exc))

    if options.optimize_fonts and options.subset_fonts:
        try:
            working_doc.subset_fonts()
        except Exception as exc:
            logger.warning("subset_fonts 失敗: %s", model._safe_exc_message(exc))

    if options.optimize_images:
        model._rewrite_images_with_pillow(working_doc, options, source_path=source_path)


def image_rewrite_settings(options: PdfOptimizeOptions) -> dict[str, int | bool]:
    return {
        "image_dpi_target": max(int(options.image_dpi_target), 1),
        "image_dpi_threshold": max(int(options.image_dpi_threshold), max(int(options.image_dpi_target), 1)),
        "image_jpeg_quality": min(max(int(options.image_jpeg_quality), 0), 100),
        "optimize_color_images": bool(options.optimize_color_images),
        "optimize_gray_images": bool(options.optimize_gray_images),
        "optimize_bitonal_images": bool(options.optimize_bitonal_images),
    }


def parallel_image_worker_count(image_count: int) -> int:
    cpu_count = os.cpu_count() or 1
    return max(1, min(image_count, max(cpu_count - 1, 1), _MAX_PARALLEL_IMAGE_WORKERS))


def can_use_parallel_image_rewrite() -> bool:
    if os.name != "nt":
        return True
    main_module = sys.modules.get("__main__")
    main_file = getattr(main_module, "__file__", None)
    if not main_file:
        return False
    try:
        return Path(main_file).exists()
    except OSError:
        return False


def rewrite_images_serially(
    model: PDFModel,
    working_doc: fitz.Document,
    image_usage: dict[int, dict[str, float | int]],
    options: PdfOptimizeOptions,
) -> None:
    settings = model._image_rewrite_settings(options)
    for xref, usage in image_usage.items():
        try:
            image_info = working_doc.extract_image(xref)
            image_bytes = image_info.get("image")
            rewritten = _transcode_image_payload(image_bytes, float(usage["max_dpi"]), settings)
            if not rewritten:
                continue
            working_doc[int(usage["page_index"])].replace_image(xref, stream=rewritten)
        except Exception as exc:
            logger.warning("rewrite image 失敗 (xref=%s): %s", xref, model._safe_exc_message(exc))


def collect_extracted_images(
    model: PDFModel,
    working_doc: fitz.Document,
    image_usage: dict[int, dict[str, float | int]],
) -> list[tuple[int, int, float, bytes]]:
    extracted_images: list[tuple[int, int, float, bytes]] = []
    for xref, usage in image_usage.items():
        try:
            image_info = working_doc.extract_image(xref)
            image_bytes = image_info.get("image")
            if not image_bytes:
                continue
            extracted_images.append(
                (
                    int(xref),
                    int(usage["page_index"]),
                    float(usage["max_dpi"]),
                    image_bytes,
                )
            )
        except Exception as exc:
            logger.warning("extract image 失敗 (xref=%s): %s", xref, model._safe_exc_message(exc))
    return extracted_images


def rewrite_images_from_source_in_parallel(
    model: PDFModel,
    working_doc: fitz.Document,
    image_usage: dict[int, dict[str, float | int]],
    options: PdfOptimizeOptions,
    source_path: Path,
) -> None:
    worker_count = model._parallel_image_worker_count(len(image_usage))
    if worker_count <= 1:
        model._rewrite_images_serially(working_doc, image_usage, options)
        return

    settings = model._image_rewrite_settings(options)
    tasks = [(int(xref), float(usage["max_dpi"]), settings) for xref, usage in image_usage.items()]
    try:
        with ProcessPoolExecutor(
            max_workers=worker_count,
            initializer=_init_image_rewrite_worker,
            initargs=(str(source_path),),
        ) as executor:
            for xref, rewritten, error in executor.map(_rewrite_source_image_task, tasks):
                if error:
                    logger.warning("rewrite image 失敗 (xref=%s): %s", xref, error)
                    continue
                if not rewritten:
                    continue
                owner_page_index = int(image_usage[int(xref)]["page_index"])
                working_doc[owner_page_index].replace_image(int(xref), stream=rewritten)
    except Exception as exc:
        logger.warning("parallel rewrite image 失敗，改回序列模式: %s", model._safe_exc_message(exc))
        model._rewrite_images_serially(working_doc, image_usage, options)


def rewrite_extracted_images_in_parallel(
    model: PDFModel,
    working_doc: fitz.Document,
    extracted_images: list[tuple[int, int, float, bytes]],
    options: PdfOptimizeOptions,
) -> None:
    worker_count = model._parallel_image_worker_count(len(extracted_images))
    if worker_count <= 1:
        image_usage = {
            int(xref): {"page_index": int(page_index), "max_dpi": float(max_dpi)}
            for xref, page_index, max_dpi, _image_bytes in extracted_images
        }
        model._rewrite_images_serially(working_doc, image_usage, options)
        return

    settings = model._image_rewrite_settings(options)
    tasks = [
        (int(xref), int(page_index), float(max_dpi), image_bytes, settings)
        for xref, page_index, max_dpi, image_bytes in extracted_images
    ]
    try:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            for xref, page_index, rewritten, error in executor.map(_rewrite_extracted_image_task, tasks):
                if error:
                    logger.warning("rewrite image 失敗 (xref=%s): %s", xref, error)
                    continue
                if not rewritten:
                    continue
                working_doc[int(page_index)].replace_image(int(xref), stream=rewritten)
    except Exception as exc:
        logger.warning("parallel rewrite extracted image 失敗，改回序列模式: %s", model._safe_exc_message(exc))
        image_usage = {
            int(xref): {"page_index": int(page_index), "max_dpi": float(max_dpi)}
            for xref, page_index, max_dpi, _image_bytes in extracted_images
        }
        model._rewrite_images_serially(working_doc, image_usage, options)


def rewrite_images_with_pillow(
    model: PDFModel,
    working_doc: fitz.Document,
    options: PdfOptimizeOptions,
    source_path: Path | None = None,
) -> None:
    if Image is None:
        raise RuntimeError("圖像最佳化需要 Pillow，請先安裝 optional-requirements.txt。")

    dpi_target = max(int(options.image_dpi_target), 1)
    image_usage: dict[int, dict[str, float | int]] = {}
    for page_index in range(len(working_doc)):
        page = working_doc[page_index]
        for item in page.get_images(full=True):
            xref = int(item[0])
            width = int(item[2])
            height = int(item[3])
            try:
                bbox = page.get_image_bbox(item)
            except Exception:
                continue
            rect_width = max(float(bbox.width), 1.0)
            rect_height = max(float(bbox.height), 1.0)
            max_dpi = max(
                width / (rect_width / 72.0),
                height / (rect_height / 72.0),
            )
            existing = image_usage.get(xref)
            if existing is None:
                image_usage[xref] = {"page_index": page_index, "max_dpi": max_dpi}
            else:
                existing["max_dpi"] = max(float(existing["max_dpi"]), max_dpi)

    if not image_usage:
        return
    # Parallel rewrite is only enabled when we have enough images to amortize overhead,
    # and when the current runtime can safely spawn worker processes (Windows is strict here).
    if (
        source_path is not None
        and len(image_usage) >= _MIN_PARALLEL_IMAGE_REWRITES
        and model._can_use_parallel_image_rewrite()
    ):
        model._rewrite_images_from_source_in_parallel(working_doc, image_usage, options, source_path)
        return
    if len(image_usage) >= _MIN_PARALLEL_IMAGE_REWRITES and model._can_use_parallel_image_rewrite():
        extracted_images = model._collect_extracted_images(working_doc, image_usage)
        if extracted_images:
            model._rewrite_extracted_images_in_parallel(working_doc, extracted_images, options)
            return
    model._rewrite_images_serially(working_doc, image_usage, options)


def requires_post_save_packaging(options: PdfOptimizeOptions) -> bool:
    return bool(options.linearize or options.use_object_streams)


def fast_save_kwargs(options: PdfOptimizeOptions) -> dict[str, int]:
    return {
        "garbage": 1 if int(options.garbage_level) > 0 else 0,
        "clean": 0,
        "deflate": int(bool(options.deflate_streams or options.deflate_images or options.deflate_fonts)),
        "deflate_images": 0,
        "deflate_fonts": 0,
        "linear": 0,
        "use_objstms": 0,
        "compression_effort": 0,
    }


def postprocess_optimized_pdf_with_pikepdf(
    model: PDFModel,
    source_path: Path,
    options: PdfOptimizeOptions,
) -> None:
    if pikepdf is None:
        raise RuntimeError("目前環境缺少 pikepdf，無法套用 linearize / object streams。")
    repacked_path = source_path.with_name(f"{source_path.stem}_packed_{uuid.uuid4().hex}.pdf")
    try:
        with pikepdf.open(str(source_path)) as pdf:
            pdf.save(
                str(repacked_path),
                compress_streams=bool(options.deflate_streams or options.deflate_images or options.deflate_fonts),
                object_stream_mode=(
                    pikepdf.ObjectStreamMode.generate
                    if options.use_object_streams
                    else pikepdf.ObjectStreamMode.preserve
                ),
                linearize=bool(options.linearize),
                recompress_flate=False,
            )
        os.replace(str(repacked_path), str(source_path))
    finally:
        if repacked_path.exists():
            try:
                repacked_path.unlink()
            except OSError:
                pass


def save_optimized_working_doc(
    model: PDFModel,
    working_doc: fitz.Document,
    temp_save: Path,
    options: PdfOptimizeOptions,
) -> None:
    if model._requires_post_save_packaging(options) and pikepdf is None:
        working_doc.save(
            str(temp_save),
            garbage=max(0, int(options.garbage_level)),
            clean=0,
            deflate=int(bool(options.deflate_streams)),
            deflate_images=int(bool(options.deflate_images)),
            deflate_fonts=int(bool(options.deflate_fonts)),
            linear=int(bool(options.linearize)),
            use_objstms=int(bool(options.use_object_streams)),
            compression_effort=max(0, int(options.compression_effort)),
        )
        return
    working_doc.save(str(temp_save), **model._fast_save_kwargs(options))
    if model._requires_post_save_packaging(options):
        model._postprocess_optimized_pdf_with_pikepdf(temp_save, options)


def save_optimized_copy(
    model: PDFModel,
    new_path: str,
    options: PdfOptimizeOptions | None = None,
) -> PdfOptimizationResult:
    if not model.doc:
        raise RuntimeError("沒有可最佳化的 PDF")

    active_sid = model.get_active_session_id()
    canonical_new = model._canonicalize_path(new_path)
    current_meta = model.get_session_meta(active_sid) if active_sid else None
    current_canonical = model._canonicalize_path(current_meta["path"]) if current_meta and current_meta.get("path") else None
    existing_sid = model._path_to_session_id.get(canonical_new)
    if existing_sid is not None or (current_canonical and canonical_new == current_canonical):
        raise RuntimeError("最佳化副本必須使用新的輸出路徑，且不能覆蓋已開啟的檔案。")

    resolved_options = model._normalize_optimize_options(options or model.preset_optimize_options("平衡"))
    optimize_source_path = model._resolve_file_backed_optimize_source(active_sid)
    original_bytes = model._current_document_size_bytes(active_sid)
    working_doc = model._build_working_doc_for_optimized_copy(active_sid)
    temp_save = Path(model.temp_dir.name) / f"optimized_{uuid.uuid4()}.pdf"
    try:
        model._apply_optimize_options(working_doc, resolved_options, source_path=optimize_source_path)
        model._save_optimized_working_doc(working_doc, temp_save, resolved_options)
        Path(new_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_save), new_path)
        optimized_bytes = Path(new_path).stat().st_size
        bytes_saved = max(0, original_bytes - optimized_bytes)
        summary: list[str] = [resolved_options.preset]
        if resolved_options.optimize_images:
            summary.append(f"圖像 {resolved_options.image_dpi_target}dpi / JPEG {resolved_options.image_jpeg_quality}")
        if resolved_options.subset_fonts:
            summary.append("字體子集化")
        if resolved_options.remove_metadata or resolved_options.remove_xml_metadata:
            summary.append("移除 metadata")
        return PdfOptimizationResult(
            output_path=str(new_path),
            original_bytes=original_bytes,
            optimized_bytes=optimized_bytes,
            bytes_saved=bytes_saved,
            percent_saved=(bytes_saved / original_bytes * 100.0) if original_bytes else 0.0,
            applied_preset=resolved_options.preset,
            applied_summary=summary,
        )
    except Exception as exc:
        if temp_save.exists():
            try:
                temp_save.unlink()
            except OSError:
                pass
        raise RuntimeError(f"最佳化 PDF 失敗: {model._safe_exc_message(exc)}") from exc
    finally:
        working_doc.close()


__all__ = [
    "PdfAuditItem",
    "PdfAuditReport",
    "PdfOptimizationResult",
    "PdfOptimizeOptions",
    "apply_optimize_options",
    "blank_metadata_dict",
    "build_pdf_audit_report",
    "build_working_doc_for_optimized_copy",
    "can_use_parallel_image_rewrite",
    "collect_extracted_images",
    "current_document_size_bytes",
    "fast_save_kwargs",
    "image_rewrite_settings",
    "make_active_audit_cache_key",
    "normalize_optimize_options",
    "parallel_image_worker_count",
    "postprocess_optimized_pdf_with_pikepdf",
    "preset_optimize_options",
    "requires_post_save_packaging",
    "resolve_file_backed_optimize_source",
    "rewrite_extracted_images_in_parallel",
    "rewrite_images_from_source_in_parallel",
    "rewrite_images_serially",
    "rewrite_images_with_pillow",
    "save_optimized_copy",
    "save_optimized_working_doc",
    "xref_size_bytes",
]

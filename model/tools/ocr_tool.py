from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Callable, Iterable

from .base import ToolExtension
from .ocr_types import (
    OcrAvailability,
    OcrDevice,
    OcrLanguage,
    OcrSpan,
)

if TYPE_CHECKING:
    from model.pdf_model import PDFModel

logger = logging.getLogger(__name__)


OCR_RENDER_SCALE = 2.0
_INSTALL_HINT = "pip install surya-ocr"


def _check_surya_import() -> tuple[bool, str]:
    try:
        importlib.import_module("surya")
        return True, ""
    except ImportError as exc:
        return False, f"surya 未安裝 ({exc})"


def is_device_available(device: str) -> bool:
    """Return True iff the requested torch device is usable right now."""
    normalized = OcrDevice.from_code(device).value
    if normalized in (OcrDevice.AUTO.value, OcrDevice.CPU.value):
        return True
    try:
        torch = importlib.import_module("torch")
    except ImportError:
        return False
    if normalized == OcrDevice.CUDA.value:
        cuda_mod = getattr(torch, "cuda", None)
        return bool(cuda_mod and cuda_mod.is_available())
    if normalized == OcrDevice.MPS.value:
        backends = getattr(torch, "backends", None)
        mps_mod = getattr(backends, "mps", None) if backends else None
        return bool(mps_mod and getattr(mps_mod, "is_available", lambda: False)())
    return False


def _empty_torch_cache(device: str) -> None:
    """Release torch's per-device allocator cache after an OCR run."""
    if device not in (OcrDevice.CUDA.value, OcrDevice.MPS.value):
        return
    try:
        torch = importlib.import_module("torch")
    except ImportError:
        return
    submodule_name = "cuda" if device == OcrDevice.CUDA.value else "mps"
    submodule = getattr(torch, submodule_name, None)
    empty_cache = getattr(submodule, "empty_cache", None) if submodule else None
    if not callable(empty_cache):
        return
    if device == OcrDevice.CUDA.value:
        is_available = getattr(submodule, "is_available", None)
        if callable(is_available) and not is_available():
            return
    try:
        empty_cache()
    except Exception:
        logger.debug("Failed to empty %s cache", device, exc_info=True)


def _resolve_torch_device(device: str) -> str:
    """Map a user device preference to a concrete torch device string.

    ``auto`` prefers CUDA, then MPS (Apple Silicon), then CPU.
    """
    normalized = OcrDevice.from_code(device).value
    if normalized == OcrDevice.CPU.value:
        return OcrDevice.CPU.value
    if normalized == OcrDevice.AUTO.value:
        try:
            torch = importlib.import_module("torch")
        except ImportError:
            return OcrDevice.CPU.value
        if getattr(torch, "cuda", None) is not None and torch.cuda.is_available():
            return OcrDevice.CUDA.value
        mps_mod = getattr(getattr(torch, "backends", None), "mps", None)
        if mps_mod is not None and getattr(mps_mod, "is_available", lambda: False)():
            return OcrDevice.MPS.value
        return OcrDevice.CPU.value

    if not is_device_available(normalized):
        label = "CUDA" if normalized == OcrDevice.CUDA.value else "MPS"
        raise RuntimeError(
            f"已選擇 {label} 但目前 torch 無法使用該裝置；請改選「自動」或「CPU」，"
            "或安裝支援該裝置的 torch 版本。"
        )
    return normalized


class _SuryaAdapter:
    """Lazy adapter around Surya's detection + recognition predictors."""

    def __init__(self, device: str) -> None:
        self._requested_device = device
        self._resolved_device: str | None = None
        self._detector = None
        self._recognizer = None

    @property
    def device(self) -> str:
        return self._resolved_device or self._requested_device

    def _ensure_loaded(self) -> None:
        if self._recognizer is not None:
            return
        torch_device = _resolve_torch_device(self._requested_device)
        logger.info("Initializing Surya predictors on device=%s", torch_device)
        try:
            detection_mod = importlib.import_module("surya.detection")
            recognition_mod = importlib.import_module("surya.recognition")
        except ImportError as exc:
            raise RuntimeError(
                f"Surya 模組載入失敗；請確認已安裝 surya-ocr。({exc})"
            ) from exc
        # Surya ≥ 0.7 introduced FoundationPredictor; RecognitionPredictor now wraps it.
        FoundationPredictor = getattr(recognition_mod, "FoundationPredictor", None)
        try:
            if FoundationPredictor is not None:
                fp = FoundationPredictor(device=torch_device)
                self._recognizer = recognition_mod.RecognitionPredictor(fp)
                self._detector = detection_mod.DetectionPredictor(device=torch_device)
            else:
                # Surya ≤ 0.6: device kwarg on both predictors.
                self._detector = detection_mod.DetectionPredictor(device=torch_device)
                self._recognizer = recognition_mod.RecognitionPredictor(device=torch_device)
        except TypeError:
            self._detector = detection_mod.DetectionPredictor()
            self._recognizer = recognition_mod.RecognitionPredictor()
        self._resolved_device = torch_device

    def ocr(self, image, languages: list[str]) -> list[tuple[tuple[float, float, float, float], str, float]]:
        self._ensure_loaded()
        # Surya ≥ 0.7 removed the language param; use TaskNames to select the OCR task.
        recognition_mod = importlib.import_module("surya.recognition")
        TaskNames = getattr(recognition_mod, "TaskNames", None)
        if TaskNames is not None:
            predictions = self._recognizer(
                [image],
                task_names=[TaskNames.ocr_without_boxes],
                det_predictor=self._detector,
            )
        else:
            predictions = self._recognizer([image], [list(languages)], self._detector)
        if not predictions:
            return []
        text_lines = getattr(predictions[0], "text_lines", None) or []
        out: list[tuple[tuple[float, float, float, float], str, float]] = []
        for line in text_lines:
            bbox = getattr(line, "bbox", None)
            if bbox is None:
                continue
            text = getattr(line, "text", "") or ""
            if not text.strip():
                continue
            confidence = getattr(line, "confidence", None)
            out.append(
                (
                    tuple(float(v) for v in bbox),
                    str(text),
                    float(confidence) if confidence is not None else 0.0,
                )
            )
        return out


def _create_surya_adapter(device: str) -> _SuryaAdapter:
    return _SuryaAdapter(device)


def _pixmap_to_image(pix):
    """Convert a fitz.Pixmap to a PIL Image (RGB) for Surya consumption."""
    import numpy as np
    from PIL import Image

    buf = np.frombuffer(pix.samples, dtype=np.uint8)
    arr = buf.reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        arr = arr[:, :, :3]
    elif pix.n == 1:
        arr = np.repeat(arr, 3, axis=2)
    return Image.fromarray(arr, mode="RGB")


class OcrTool(ToolExtension):
    def __init__(self, model: PDFModel) -> None:
        self._model = model

    def availability(self) -> OcrAvailability:
        ok, reason = _check_surya_import()
        if ok:
            return OcrAvailability(available=True)
        return OcrAvailability(
            available=False,
            reason=reason or "Surya 未安裝",
            install_hint=_INSTALL_HINT,
        )

    def ocr_pages(
        self,
        pages: list[int],
        languages: Iterable[str] = ("en",),
        *,
        device: str = "auto",
        on_progress: Callable[[int, int, int], None] | None = None,
    ) -> dict[int, list[OcrSpan]]:
        """Run Surya OCR on the given 1-based page numbers.

        Returns ``{page_num: [OcrSpan, ...]}`` with bboxes in **visual page
        coordinates** (not raster pixels).
        """
        if not self._model.doc:
            return {}

        lang_list = [OcrLanguage.from_code(code).value for code in languages]
        if not lang_list:
            raise ValueError("OCR 語言清單不可為空")

        page_nums = list(pages)
        total_pages = len(self._model.doc)
        for page_num in page_nums:
            if page_num < 1 or page_num > total_pages:
                raise ValueError(f"無效 OCR 頁碼: {page_num}")

        ok, reason = _check_surya_import()
        if not ok:
            raise RuntimeError(reason or "Surya 未安裝；請先執行 pip install surya-ocr")

        adapter = _create_surya_adapter(device)
        render_scale = float(OCR_RENDER_SCALE)
        results: dict[int, list[OcrSpan]] = {}
        try:
            for done, page_num in enumerate(page_nums, start=1):
                pix = self._model.tools.render_page_pixmap(
                    page_num,
                    scale=render_scale,
                    annots=False,
                    purpose="ocr",
                )
                image = _pixmap_to_image(pix)
                try:
                    raw_spans = adapter.ocr(image, lang_list)
                except Exception as exc:
                    logger.exception("Surya OCR failed on page %s", page_num)
                    raise RuntimeError(f"Surya OCR 在第 {page_num} 頁失敗: {exc}") from exc

                page_spans: list[OcrSpan] = []
                for bbox, text, confidence in raw_spans:
                    x0, y0, x1, y1 = bbox
                    page_spans.append(
                        OcrSpan(
                            bbox=(
                                float(x0) / render_scale,
                                float(y0) / render_scale,
                                float(x1) / render_scale,
                                float(y1) / render_scale,
                            ),
                            text=text,
                            confidence=confidence,
                        )
                    )
                results[page_num] = page_spans
                if on_progress is not None:
                    on_progress(page_num, done, len(page_nums))
            return results
        finally:
            cleanup_device = getattr(adapter, "device", device)
            adapter = None  # drop strong ref before empty_cache
            _empty_torch_cache(cleanup_device)

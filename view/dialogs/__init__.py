from __future__ import annotations

_EXPORTS: dict[str, str] = {
    "AuditStackedBar": "audit",
    "ExportPagesDialog": "export",
    "MergePdfDialog": "merge",
    "OcrDialog": "ocr",
    "OptimizePdfDialog": "optimize",
    "PDFPasswordDialog": "password",
    "PdfAuditReportDialog": "audit",
    "WatermarkDialog": "watermark",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> object:
    if name in _EXPORTS:
        import importlib
        mod = importlib.import_module(f"view.dialogs.{_EXPORTS[name]}")
        obj = getattr(mod, name)
        globals()[name] = obj
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

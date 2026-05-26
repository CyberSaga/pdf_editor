"""Surya predictors must be loaded once and cached, not reloaded per page.

Mission #8: OCR shows the progress bar then sits idle (CPU/GPU not moving) for a
long time before anything happens. Root cause: the per-page OCR worker recreates
a `_SuryaAdapter` for every page, and `_ensure_loaded` constructed the (expensive,
weight-loading) predictors per instance — so models reloaded on every page and on
every run. Caching the predictors at module level means the load happens once.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from model.tools import ocr_tool as ocr_tool_module  # noqa: E402


def test_predictors_constructed_once_across_adapters(monkeypatch):
    construct_counts = {"detector": 0, "recognizer": 0}

    class _FakeDetector:
        def __init__(self, *args, **kwargs):
            construct_counts["detector"] += 1

    class _FakeRecognizer:
        def __init__(self, *args, **kwargs):
            construct_counts["recognizer"] += 1

    # Fake surya modules without FoundationPredictor (legacy device-kwarg branch).
    fake_detection = type(sys)("surya.detection")
    fake_detection.DetectionPredictor = _FakeDetector
    fake_recognition = type(sys)("surya.recognition")
    fake_recognition.RecognitionPredictor = _FakeRecognizer

    def _fake_import(name, *args, **kwargs):
        if name == "surya.detection":
            return fake_detection
        if name == "surya.recognition":
            return fake_recognition
        raise ImportError(name)

    monkeypatch.setattr(ocr_tool_module.importlib, "import_module", _fake_import)
    monkeypatch.setattr(ocr_tool_module, "_resolve_torch_device", lambda dev: "cpu")
    # Start from a clean cache so the test is deterministic.
    monkeypatch.setattr(ocr_tool_module, "_PREDICTOR_CACHE", {}, raising=False)

    # Simulate the per-page worker loop: a fresh adapter per page.
    for _ in range(3):
        adapter = ocr_tool_module._SuryaAdapter("cpu")
        adapter._ensure_loaded()

    assert construct_counts["detector"] == 1, (
        f"detector constructed {construct_counts['detector']} times; expected 1 (cached)"
    )
    assert construct_counts["recognizer"] == 1, (
        f"recognizer constructed {construct_counts['recognizer']} times; expected 1 (cached)"
    )

from __future__ import annotations

from dataclasses import dataclass
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import fitz
import pytest

from model.tools import ocr_tool as ocr_tool_module
from model.tools.ocr_tool import OcrTool
from model.tools.ocr_types import OcrSpan


class _FakePixmap:
    """Minimal stand-in for fitz.Pixmap with a numpy-friendly buffer."""

    def __init__(self, width: int, height: int, n: int = 3) -> None:
        self.width = width
        self.height = height
        self.n = n
        self.alpha = n == 4
        self.stride = width * n
        self.samples = bytes([0] * (width * height * n))


@dataclass
class _FakeAdapter:
    pages_seen: list = None
    languages_seen: list = None
    device: str = "auto"

    def __post_init__(self):
        if self.pages_seen is None:
            self.pages_seen = []
        if self.languages_seen is None:
            self.languages_seen = []

    def ocr(self, image, languages):
        self.pages_seen.append(image)
        self.languages_seen.append(list(languages))
        return [
            ((10.0, 20.0, 60.0, 50.0), "hello", 0.95),
            ((100.0, 200.0, 220.0, 240.0), "world", 0.88),
        ]


class _FakeDoc:
    def __init__(self, page_count: int) -> None:
        self._page_count = page_count

    def __len__(self) -> int:
        return self._page_count

    def __bool__(self) -> bool:
        return True


def _make_tool_with_fake(monkeypatch, fake_adapter: _FakeAdapter | None = None) -> OcrTool:
    fake = fake_adapter or _FakeAdapter()
    monkeypatch.setattr(ocr_tool_module, "_create_surya_adapter", lambda device: fake)
    monkeypatch.setattr(
        ocr_tool_module,
        "_check_surya_import",
        lambda: (True, ""),
    )

    model = MagicMock()
    model.doc = _FakeDoc(5)
    pix = _FakePixmap(200, 100)
    model.tools = SimpleNamespace(render_page_pixmap=MagicMock(return_value=pix))

    tool = OcrTool(model)
    tool._adapter_factory_for_test = fake  # noqa: SLF001
    return tool


def test_availability_reports_missing_when_surya_not_installed(monkeypatch):
    monkeypatch.setattr(
        ocr_tool_module,
        "_check_surya_import",
        lambda: (False, "surya not installed"),
    )
    tool = OcrTool(MagicMock(doc=None))
    avail = tool.availability()
    assert avail.available is False
    assert "surya" in avail.reason.lower()
    assert "pip install" in avail.install_hint.lower()


def test_availability_reports_present_when_module_imports(monkeypatch):
    monkeypatch.setattr(
        ocr_tool_module,
        "_check_surya_import",
        lambda: (True, ""),
    )
    tool = OcrTool(MagicMock(doc=None))
    avail = tool.availability()
    assert avail.available is True
    assert avail.reason == ""


def test_ocr_pages_returns_visual_coords_scaled_by_render_scale(monkeypatch):
    fake = _FakeAdapter()
    tool = _make_tool_with_fake(monkeypatch, fake)
    monkeypatch.setattr(ocr_tool_module, "OCR_RENDER_SCALE", 2.0, raising=False)

    result = tool.ocr_pages([1], languages=["en"])
    assert 1 in result
    spans = result[1]
    assert all(isinstance(s, OcrSpan) for s in spans)
    # Pixel bboxes (10,20,60,50) and (100,200,220,240) are in raster space at scale=2.
    # Expected visual page coords are halved.
    assert spans[0].bbox == (5.0, 10.0, 30.0, 25.0)
    assert spans[0].text == "hello"
    assert spans[0].confidence == pytest.approx(0.95)
    assert spans[1].bbox == (50.0, 100.0, 110.0, 120.0)


def test_ocr_pages_forwards_languages_to_adapter(monkeypatch):
    fake = _FakeAdapter()
    tool = _make_tool_with_fake(monkeypatch, fake)

    tool.ocr_pages([1, 2], languages=["en", "zh-Hant"])
    assert fake.languages_seen == [["en", "zh-Hant"], ["en", "zh-Hant"]]


def test_ocr_pages_rejects_unknown_language_before_adapter_call(monkeypatch):
    fake = _FakeAdapter()
    tool = _make_tool_with_fake(monkeypatch, fake)

    with pytest.raises(ValueError):
        tool.ocr_pages([1], languages=["en", "klingon"])
    assert fake.pages_seen == []


def test_ocr_pages_emits_progress_per_page(monkeypatch):
    fake = _FakeAdapter()
    tool = _make_tool_with_fake(monkeypatch, fake)
    progress: list[tuple[int, int, int]] = []

    tool.ocr_pages(
        [1, 2, 3],
        languages=["en"],
        on_progress=lambda page, done, total: progress.append((page, done, total)),
    )
    assert [p[2] for p in progress] == [3, 3, 3]
    assert [p[1] for p in progress] == [1, 2, 3]
    assert [p[0] for p in progress] == [1, 2, 3]


def test_ocr_pages_uses_render_page_pixmap_with_purpose_ocr(monkeypatch):
    fake = _FakeAdapter()
    tool = _make_tool_with_fake(monkeypatch, fake)

    tool.ocr_pages([2], languages=["en"])
    render = tool._model.tools.render_page_pixmap
    render.assert_called_once()
    args, kwargs = render.call_args
    assert args[0] == 2
    assert kwargs.get("purpose") == "ocr"
    assert kwargs.get("annots") is False


def test_ocr_pages_passes_device_to_adapter_factory(monkeypatch):
    captured: dict = {}

    def fake_factory(device):
        captured["device"] = device
        return _FakeAdapter()

    monkeypatch.setattr(ocr_tool_module, "_create_surya_adapter", fake_factory)
    monkeypatch.setattr(ocr_tool_module, "_check_surya_import", lambda: (True, ""))

    model = MagicMock()
    model.doc = _FakeDoc(5)
    model.tools = SimpleNamespace(render_page_pixmap=MagicMock(return_value=_FakePixmap(50, 50)))

    tool = OcrTool(model)
    tool.ocr_pages([1], languages=["en"], device="cuda")
    assert captured["device"] == "cuda"


def test_ocr_pages_raises_for_invalid_page_number(monkeypatch):
    tool = _make_tool_with_fake(monkeypatch)
    with pytest.raises(ValueError):
        tool.ocr_pages([0], languages=["en"])
    with pytest.raises(ValueError):
        tool.ocr_pages([99], languages=["en"])


def test_ocr_pages_returns_empty_when_no_doc(monkeypatch):
    monkeypatch.setattr(ocr_tool_module, "_check_surya_import", lambda: (True, ""))
    monkeypatch.setattr(ocr_tool_module, "_create_surya_adapter", lambda device: _FakeAdapter())
    model = MagicMock()
    model.doc = None
    tool = OcrTool(model)
    assert tool.ocr_pages([1], languages=["en"]) == {}


def test_ocr_pages_raises_runtime_error_when_surya_missing(monkeypatch):
    monkeypatch.setattr(
        ocr_tool_module,
        "_check_surya_import",
        lambda: (False, "surya not installed"),
    )
    model = MagicMock()
    model.doc = _FakeDoc(1)
    tool = OcrTool(model)
    with pytest.raises(RuntimeError):
        tool.ocr_pages([1], languages=["en"])


def test_ocr_pages_pixmap_to_image_strips_alpha(monkeypatch):
    fake = _FakeAdapter()
    tool = _make_tool_with_fake(monkeypatch, fake)
    pix = _FakePixmap(40, 30, n=4)
    tool._model.tools.render_page_pixmap = MagicMock(return_value=pix)

    tool.ocr_pages([1], languages=["en"])
    # Adapter receives a PIL Image (or numpy array) in RGB form (no alpha).
    img = fake.pages_seen[0]
    if hasattr(img, "mode"):
        assert img.mode == "RGB"
    else:
        # numpy fallback: shape (H, W, 3)
        assert img.shape[-1] == 3


def test_real_pixmap_round_trip(monkeypatch):
    fake = _FakeAdapter()
    monkeypatch.setattr(ocr_tool_module, "_create_surya_adapter", lambda device: fake)
    monkeypatch.setattr(ocr_tool_module, "_check_surya_import", lambda: (True, ""))

    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text(fitz.Point(50, 100), "x")
    pix = page.get_pixmap()

    model = MagicMock()
    model.doc = doc
    model.tools = SimpleNamespace(render_page_pixmap=MagicMock(return_value=pix))

    tool = OcrTool(model)
    result = tool.ocr_pages([1], languages=["en"])
    assert 1 in result
    doc.close()


def test_resolve_torch_device_explicit_cuda_unavailable_raises(monkeypatch):
    """Explicit cuda selection without CUDA torch must raise a clear error."""
    real_import_module = importlib.import_module
    fake_torch = type(sys)("torch")
    fake_torch.cuda = type(sys)("cuda")
    fake_torch.cuda.is_available = lambda: False
    fake_torch.backends = type(sys)("backends")
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: fake_torch if name == "torch" else real_import_module(name),
    )

    from model.tools.ocr_tool import _resolve_torch_device

    with pytest.raises(RuntimeError, match="CUDA"):
        _resolve_torch_device("cuda")


def test_resolve_torch_device_explicit_mps_unavailable_raises(monkeypatch):
    """Explicit mps selection without MPS must raise a clear error."""
    real_import_module = importlib.import_module
    fake_torch = type(sys)("torch")
    fake_torch.cuda = type(sys)("cuda")
    fake_torch.cuda.is_available = lambda: False
    fake_torch.backends = type(sys)("backends")
    fake_torch.backends.mps = type(sys)("mps")
    fake_torch.backends.mps.is_available = lambda: False
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: fake_torch if name == "torch" else real_import_module(name),
    )

    from model.tools.ocr_tool import _resolve_torch_device

    with pytest.raises(RuntimeError, match="MPS"):
        _resolve_torch_device("mps")


def test_resolve_torch_device_explicit_cpu_always_returns_cpu():
    from model.tools.ocr_tool import _resolve_torch_device

    assert _resolve_torch_device("cpu") == "cpu"


def test_is_device_available_cpu_always_true():
    from model.tools.ocr_tool import is_device_available

    assert is_device_available("cpu") is True
    assert is_device_available("auto") is True


def test_is_device_available_cuda_reflects_torch(monkeypatch):
    real_import_module = importlib.import_module
    fake_torch = type(sys)("torch")
    fake_torch.cuda = type(sys)("cuda")
    fake_torch.cuda.is_available = lambda: True
    fake_torch.backends = type(sys)("backends")
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: fake_torch if name == "torch" else real_import_module(name),
    )

    from model.tools.ocr_tool import is_device_available

    assert is_device_available("cuda") is True


def test_ocr_pages_calls_cuda_empty_cache(monkeypatch):
    """After successful OCR on a CUDA device, torch.cuda.empty_cache must be called."""
    calls = {"empty": 0}
    real_import_module = importlib.import_module
    fake_torch = type(sys)("torch")
    fake_torch.cuda = type(sys)("cuda")
    fake_torch.cuda.is_available = lambda: True
    fake_torch.cuda.empty_cache = lambda: calls.__setitem__("empty", calls["empty"] + 1)
    fake_torch.backends = type(sys)("backends")
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: fake_torch if name == "torch" else real_import_module(name),
    )

    tool = _make_tool_with_fake(monkeypatch, _FakeAdapter(device="cuda"))
    tool.ocr_pages([1], languages=["en"], device="cuda")
    assert calls["empty"] == 1


def test_ocr_pages_skips_empty_cache_on_cpu(monkeypatch):
    """No CUDA cleanup attempted when running on CPU."""
    calls = {"empty": 0}
    real_import_module = importlib.import_module
    fake_torch = type(sys)("torch")
    fake_torch.cuda = type(sys)("cuda")
    fake_torch.cuda.is_available = lambda: False
    fake_torch.cuda.empty_cache = lambda: calls.__setitem__("empty", calls["empty"] + 1)
    fake_torch.backends = type(sys)("backends")
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: fake_torch if name == "torch" else real_import_module(name),
    )

    tool = _make_tool_with_fake(monkeypatch, _FakeAdapter(device="cpu"))
    tool.ocr_pages([1], languages=["en"], device="cpu")
    assert calls["empty"] == 0

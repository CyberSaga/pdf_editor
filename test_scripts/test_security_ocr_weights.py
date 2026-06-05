"""Security finding F9 (CWE-494): OCR weight revision pin + SHA256 verification.

surya downloads detection/recognition weights with no content-hash check and only a
loosely-pinned dated S3 path. These tests lock the verification layer added in
``model/tools/ocr_weights.py`` and its wiring into the OCR adapter: a mismatched (or
missing) weight hash must refuse loading; a matching hash must be allowed.
"""

from __future__ import annotations

import hashlib

import pytest

from model.tools import ocr_tool, ocr_weights
from model.tools.ocr_weights import (
    OcrWeightsError,
    enforce_weights_policy,
    pinned_checkpoints,
    resolve_weights_dir,
    sha256_file,
    verify_weights_dir,
)

_REL = "text_recognition/model.safetensors"


def _make_bundle(tmp_path, payload: bytes = b"weights-bytes") -> tuple[str, str]:
    """Create a bundle dir with one weight file; return (dir, sha256)."""
    weight = tmp_path / _REL
    weight.parent.mkdir(parents=True, exist_ok=True)
    weight.write_bytes(payload)
    return str(tmp_path), hashlib.sha256(payload).hexdigest()


def test_sha256_file_matches_hashlib(tmp_path) -> None:
    p = tmp_path / "w.bin"
    p.write_bytes(b"abc123")
    assert sha256_file(p) == hashlib.sha256(b"abc123").hexdigest()


def test_resolve_weights_dir_from_env() -> None:
    assert resolve_weights_dir({}) is None
    got = resolve_weights_dir({"PDF_EDITOR_OCR_WEIGHTS_DIR": "/bundle"})
    assert got is not None and got.name == "bundle"


def test_pinned_checkpoints_default_pins_three_models() -> None:
    cps = pinned_checkpoints({})
    assert set(cps) == {
        "DETECTOR_MODEL_CHECKPOINT",
        "FOUNDATION_MODEL_CHECKPOINT",
        "RECOGNITION_MODEL_CHECKPOINT",
    }
    assert all(v for v in cps.values())


def test_pinned_checkpoints_revision_override_targets_ocr_only() -> None:
    cps = pinned_checkpoints({"PDF_EDITOR_OCR_REVISION": "s3://text_recognition/2099_01_01"})
    assert cps["RECOGNITION_MODEL_CHECKPOINT"] == "s3://text_recognition/2099_01_01"
    assert cps["FOUNDATION_MODEL_CHECKPOINT"] == "s3://text_recognition/2099_01_01"
    # Detection is a separate model and keeps its own pinned revision.
    assert cps["DETECTOR_MODEL_CHECKPOINT"] != "s3://text_recognition/2099_01_01"


def test_verify_weights_dir_accepts_matching_hash(tmp_path) -> None:
    bundle_dir, sha = _make_bundle(tmp_path)
    verify_weights_dir(bundle_dir, {_REL: sha})  # must not raise


def test_verify_weights_dir_rejects_mismatched_hash(tmp_path) -> None:
    bundle_dir, _sha = _make_bundle(tmp_path)
    with pytest.raises(OcrWeightsError, match="hash mismatch"):
        verify_weights_dir(bundle_dir, {_REL: "0" * 64})


def test_verify_weights_dir_rejects_missing_file(tmp_path) -> None:
    bundle_dir, _sha = _make_bundle(tmp_path)
    with pytest.raises(OcrWeightsError, match="missing"):
        verify_weights_dir(bundle_dir, {"text_recognition/absent.bin": "0" * 64})


def test_verify_weights_dir_empty_manifest_fails_closed(tmp_path) -> None:
    bundle_dir, _sha = _make_bundle(tmp_path)
    with pytest.raises(OcrWeightsError, match="WEIGHTS_MANIFEST is empty"):
        verify_weights_dir(bundle_dir, {})


def test_verify_weights_dir_missing_directory(tmp_path) -> None:
    with pytest.raises(OcrWeightsError, match="does not exist"):
        verify_weights_dir(tmp_path / "nope", {_REL: "0" * 64})


def test_enforce_policy_no_bundle_pins_revisions_online() -> None:
    env: dict[str, str] = {}
    applied = enforce_weights_policy(env)
    assert applied["RECOGNITION_MODEL_CHECKPOINT"].startswith("s3://")
    # Revision pins are written into the PASSED env (not os.environ) for surya.
    assert env["RECOGNITION_MODEL_CHECKPOINT"].startswith("s3://")
    # Online path: offline flags are NOT forced.
    assert env.get("HF_HUB_OFFLINE") in (None, "0", "")


def test_enforce_policy_does_not_mutate_os_environ() -> None:
    """Passing a synthetic env must not touch the real process environment."""
    import os

    before = dict(os.environ)
    enforce_weights_policy({})
    assert dict(os.environ) == before


def test_enforce_policy_bundle_mismatch_refuses(tmp_path, monkeypatch) -> None:
    bundle_dir, _sha = _make_bundle(tmp_path)
    monkeypatch.setattr(ocr_weights, "WEIGHTS_MANIFEST", {_REL: "0" * 64})
    with pytest.raises(OcrWeightsError, match="hash mismatch"):
        enforce_weights_policy({"PDF_EDITOR_OCR_WEIGHTS_DIR": bundle_dir})


def test_enforce_policy_bundle_match_allows_offline(tmp_path, monkeypatch) -> None:
    bundle_dir, sha = _make_bundle(tmp_path)
    monkeypatch.setattr(ocr_weights, "WEIGHTS_MANIFEST", {_REL: sha})
    env = {"PDF_EDITOR_OCR_WEIGHTS_DIR": bundle_dir}
    applied = enforce_weights_policy(env)
    # Checkpoints now point inside the local bundle (no s3://).
    assert applied["RECOGNITION_MODEL_CHECKPOINT"].endswith("text_recognition")
    assert bundle_dir in applied["RECOGNITION_MODEL_CHECKPOINT"]
    # Offline loading is forced so no network fetch can happen.
    assert env.get("HF_HUB_OFFLINE") == "1"
    assert env.get("TRANSFORMERS_OFFLINE") == "1"


def test_adapter_refuses_load_on_weight_failure(monkeypatch) -> None:
    """_SuryaAdapter._ensure_loaded must enforce weight policy BEFORE importing
    surya, so a verification failure refuses the load."""
    monkeypatch.setattr(ocr_tool, "_PREDICTOR_CACHE", {})

    def _boom(*_a, **_k):
        raise OcrWeightsError("tampered weights")

    monkeypatch.setattr(ocr_tool, "enforce_weights_policy", _boom)

    adapter = ocr_tool._SuryaAdapter("cpu")
    with pytest.raises(OcrWeightsError, match="tampered weights"):
        adapter._ensure_loaded()

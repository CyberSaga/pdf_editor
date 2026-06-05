"""OCR model-weight integrity policy (finding F9, CWE-494).

Surya fetches its detection/recognition weights from datalab's S3 host on first
use (``surya.common.s3``). That path performs **no content-hash verification** and
the checkpoints are only loosely pinned by a dated S3 path that a surya upgrade can
silently change. This module adds a verification layer the OCR adapter calls before
any predictor is constructed:

* **Revision pinning** — the surya checkpoint settings (``DETECTOR_MODEL_CHECKPOINT``,
  ``FOUNDATION_MODEL_CHECKPOINT``, ``RECOGNITION_MODEL_CHECKPOINT``) are pinned to
  explicit, known values via environment variables that surya's ``BaseSettings``
  reads at import time. An upgrade therefore cannot move us to different weights
  without an explicit pin change here.
* **Offline / bundled loading** — when ``PDF_EDITOR_OCR_WEIGHTS_DIR`` points at a
  local bundle, the checkpoints are redirected to subdirectories of that bundle and
  surya/transformers are forced offline, so no network fetch happens at all.
* **SHA256 verification** — before a bundle is used, every file named in
  :data:`WEIGHTS_MANIFEST` is hashed and compared to its pinned digest. Any missing
  file or mismatch raises :class:`OcrWeightsError` and loading is refused.

The expected hashes and how to (re)generate them are documented in
``docs/ocr-weights-verification.md``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# --- Public configuration knobs (environment variables) ----------------------

#: Points at a local, vetted weights bundle. When set, weights load offline from
#: here and are SHA256-verified against :data:`WEIGHTS_MANIFEST` before use.
WEIGHTS_DIR_ENV = "PDF_EDITOR_OCR_WEIGHTS_DIR"

#: Optional override of the pinned recognition/foundation checkpoint id. Accepts a
#: full surya checkpoint string (e.g. ``s3://text_recognition/2026_01_01``) or a
#: local path. Detection keeps its own pinned checkpoint.
REVISION_ENV = "PDF_EDITOR_OCR_REVISION"

# --- Pinned revisions --------------------------------------------------------

# Default surya checkpoints, pinned explicitly so an upstream bump cannot move us
# to different weights without editing this file. These mirror the validated
# surya-ocr 0.17.x defaults (date-versioned S3 paths == the upstream "revision").
_DETECTOR_CHECKPOINT = "s3://text_detection/2025_05_07"
_RECOGNITION_CHECKPOINT = "s3://text_recognition/2025_09_23"

#: surya settings field name -> pinned checkpoint value.
PINNED_CHECKPOINTS: dict[str, str] = {
    "DETECTOR_MODEL_CHECKPOINT": _DETECTOR_CHECKPOINT,
    "FOUNDATION_MODEL_CHECKPOINT": _RECOGNITION_CHECKPOINT,
    "RECOGNITION_MODEL_CHECKPOINT": _RECOGNITION_CHECKPOINT,
}

# Subdirectory layout expected inside a local bundle (PDF_EDITOR_OCR_WEIGHTS_DIR).
# Mirrors the model-name prefix surya derives from each S3 checkpoint path.
_BUNDLE_SUBDIRS: dict[str, str] = {
    "DETECTOR_MODEL_CHECKPOINT": "text_detection",
    "FOUNDATION_MODEL_CHECKPOINT": "text_recognition",
    "RECOGNITION_MODEL_CHECKPOINT": "text_recognition",
}

# --- Pinned weight digests ---------------------------------------------------

#: Bundle-relative file path -> expected lowercase hex SHA256.
#:
#: Empty by default: no vetted bundle ships with the repo yet (see TODOS.md "F9
#: bundle distribution"). Populate this when a bundle is vetted — see
#: docs/ocr-weights-verification.md for how to compute the digests. While empty,
#: configuring PDF_EDITOR_OCR_WEIGHTS_DIR fails closed (loading is refused), since
#: there is nothing to verify the bundle against.
WEIGHTS_MANIFEST: dict[str, str] = {}


class OcrWeightsError(RuntimeError):
    """Raised when OCR weights fail integrity verification (refuse to load)."""


def sha256_file(path: str | os.PathLike[str], *, chunk_size: int = 1 << 20) -> str:
    """Return the lowercase hex SHA256 of a file, read in streamed chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_weights_dir(env: dict[str, str] | None = None) -> Path | None:
    """Return the configured local bundle directory, or ``None`` if unset."""
    environ = os.environ if env is None else env
    raw = (environ.get(WEIGHTS_DIR_ENV) or "").strip()
    return Path(raw) if raw else None


def pinned_checkpoints(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return the checkpoint map to enforce, applying the optional revision override."""
    environ = os.environ if env is None else env
    resolved = dict(PINNED_CHECKPOINTS)
    override = (environ.get(REVISION_ENV) or "").strip()
    if override:
        # The override targets the OCR (recognition/foundation) weights only;
        # detection is a separate model with its own pinned revision.
        resolved["FOUNDATION_MODEL_CHECKPOINT"] = override
        resolved["RECOGNITION_MODEL_CHECKPOINT"] = override
    return resolved


def verify_weights_dir(
    weights_dir: str | os.PathLike[str], manifest: dict[str, str] | None = None
) -> None:
    """Verify every manifest file under ``weights_dir`` by SHA256.

    Fails closed: an empty manifest, a missing file, or any digest mismatch raises
    :class:`OcrWeightsError`. Returns ``None`` when all listed files match.
    """
    manifest = WEIGHTS_MANIFEST if manifest is None else manifest
    base = Path(weights_dir)
    if not base.is_dir():
        raise OcrWeightsError(f"OCR weights directory does not exist: {base}")
    if not manifest:
        raise OcrWeightsError(
            "OCR weights bundle configured but WEIGHTS_MANIFEST is empty; "
            "cannot verify integrity. Populate the pinned SHA256 digests "
            "(see docs/ocr-weights-verification.md) before enabling the bundle."
        )
    for rel_path, expected in manifest.items():
        target = base / rel_path
        if not target.is_file():
            raise OcrWeightsError(f"OCR weight file missing from bundle: {rel_path}")
        actual = sha256_file(target)
        if actual.lower() != expected.lower():
            raise OcrWeightsError(
                f"OCR weight hash mismatch for {rel_path}: "
                f"expected {expected.lower()}, got {actual.lower()}"
            )
    logger.info("Verified %d OCR weight file(s) under %s", len(manifest), base)


def _apply_settings(checkpoints: dict[str, str], *, offline: bool) -> None:
    """Push checkpoint values into the environment and any live surya settings.

    surya's ``settings`` is a pydantic ``BaseSettings`` instantiated at first import
    of ``surya.settings``. Setting the env vars before that import is enough in the
    normal flow (surya is imported lazily by the OCR adapter); we also patch a live
    settings object defensively in case something imported it earlier.
    """
    for field, value in checkpoints.items():
        os.environ[field] = value
    if offline:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    settings_mod = sys.modules.get("surya.settings")
    live = getattr(settings_mod, "settings", None) if settings_mod else None
    if live is not None:
        for field, value in checkpoints.items():
            try:
                setattr(live, field, value)
            except (AttributeError, ValueError, TypeError):
                logger.debug("Could not patch live surya setting %s", field, exc_info=True)


def enforce_weights_policy(env: dict[str, str] | None = None) -> dict[str, str]:
    """Apply the OCR weight integrity policy and return the enforced checkpoint map.

    * No bundle configured: pin the checkpoint revisions (network fetch stays
      enabled but is revision-locked) and return.
    * Bundle configured (``PDF_EDITOR_OCR_WEIGHTS_DIR``): SHA256-verify it, redirect
      checkpoints to its local subdirectories, and force offline loading. Raises
      :class:`OcrWeightsError` if verification fails (loading is refused).
    """
    environ = os.environ if env is None else env
    checkpoints = pinned_checkpoints(environ)
    weights_dir = resolve_weights_dir(environ)

    if weights_dir is None:
        _apply_settings(checkpoints, offline=False)
        logger.debug("OCR weights: revision-pinned online load (no bundle configured)")
        return checkpoints

    verify_weights_dir(weights_dir, WEIGHTS_MANIFEST)
    local = {
        field: str(weights_dir / subdir)
        for field, subdir in _BUNDLE_SUBDIRS.items()
    }
    _apply_settings(local, offline=True)
    logger.info("OCR weights: verified offline bundle load from %s", weights_dir)
    return local

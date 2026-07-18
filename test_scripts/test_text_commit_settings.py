"""Red-light tests for the Qt-free text-commit settings DTO (Task 5)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import TextCommitSettings  # noqa: E402


def test_default_settings_stay_legacy_and_off():
    settings = TextCommitSettings()
    assert settings.engine == "legacy"
    assert settings.max_tier == 0
    assert settings.strict is False
    assert settings.preview == "legacy"
    assert settings.telemetry == "off"


def test_from_env_parses_valid_values():
    settings = TextCommitSettings.from_env(
        {
            "TEXT_COMMIT_ENGINE": "shadow",
            "TEXT_COMMIT_MAX_TIER": "1",
            "TEXT_COMMIT_STRICT": "1",
            "TEXT_COMMIT_PREVIEW": "plan",
            "TEXT_COMMIT_TELEMETRY": "local",
        }
    )
    assert settings.engine == "shadow"
    assert settings.max_tier == 1
    assert settings.strict is True
    assert settings.preview == "plan"
    assert settings.telemetry == "local"


def test_from_env_invalid_values_fall_back_to_defaults():
    settings = TextCommitSettings.from_env(
        {
            "TEXT_COMMIT_ENGINE": "warp-speed",
            "TEXT_COMMIT_MAX_TIER": "9",
            "TEXT_COMMIT_STRICT": "yes-please",
            "TEXT_COMMIT_PREVIEW": "hologram",
            "TEXT_COMMIT_TELEMETRY": "cloud",
        }
    )
    assert settings == TextCommitSettings()


def test_from_env_empty_environment_is_default():
    assert TextCommitSettings.from_env({}) == TextCommitSettings()


def test_pdf_model_accepts_settings_dto():
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="shadow"))
    try:
        assert model.text_commit_settings.engine == "shadow"
    finally:
        model.close()


def test_pdf_model_defaults_to_legacy_settings():
    model = PDFModel()
    try:
        assert model.text_commit_settings == TextCommitSettings()
        assert model.last_commit_outcome is None
    finally:
        model.close()

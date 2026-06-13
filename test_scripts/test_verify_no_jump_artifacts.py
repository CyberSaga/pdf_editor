import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import verify_no_jump  # noqa: E402


def _write_metrics(base: Path, test_id: str, metrics: dict) -> None:
    case_dir = base / test_id
    case_dir.mkdir(parents=True)
    (case_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")


def test_negative_control_artifacts_use_negative_control_schema(tmp_path, monkeypatch):
    run_id = "run-negative-control-schema"
    artifact_dir = tmp_path / "no_jump"
    artifact_dir.mkdir()
    monkeypatch.setattr(verify_no_jump, "ARTIFACT_DIR", artifact_dir)

    _write_metrics(
        artifact_dir,
        "geom_negative_control",
        {
            "run_id": run_id,
            "injected_x_offset": 2.0,
            "detected_drift": 2.0,
        },
    )
    _write_metrics(
        artifact_dir,
        "geom_neg_fontsize_cjk",
        {
            "run_id": run_id,
            "font_case": "cjk",
            "correct_size": 14.0,
            "wrong_size": 12.0,
            "bad_fs_ratio": 0.8571428571428571,
        },
    )
    _write_metrics(
        artifact_dir,
        "geom_neg_fontsize_unknown_font",
        {
            "run_id": run_id,
            "font_case": "unknown_font",
            "correct_size": 10.0,
            "wrong_size": 12.0,
            "bad_fs_ratio": 1.2,
        },
    )

    manifest = [
        "geom_negative_control",
        "geom_neg_fontsize_cjk",
        "geom_neg_fontsize_unknown_font",
    ]

    assert verify_no_jump._check_artifacts(run_id, manifest, set(manifest))

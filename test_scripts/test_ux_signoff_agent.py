from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.ux_signoff_agent as signoff_mod


def test_main_fails_closed_without_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    signoff_path = tmp_path / "signoff.json"
    evidence_dir = tmp_path / "cua_evidence"

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(signoff_mod, "OpenAI", object())
    monkeypatch.setattr(signoff_mod, "SIGNOFF_FILE", signoff_path)
    monkeypatch.setattr(signoff_mod, "CUA_EVIDENCE_DIR", evidence_dir)

    rc = signoff_mod.main()

    assert rc == 1
    assert not signoff_path.exists()


def test_main_isolates_each_pdf_run_and_continues_after_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signoff_path = tmp_path / "signoff.json"
    evidence_dir = tmp_path / "cua_evidence"
    reference_pdfs = ["first.pdf", "second.pdf"]

    class _FakeProc:
        def __init__(self, idx: int) -> None:
            self.pid = idx
            self.terminated = False
            self.wait_calls = 0

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float | None = None) -> None:
            self.wait_calls += 1

    launched_procs: list[_FakeProc] = []
    run_agent_calls: list[str] = []

    def _fake_popen(args, cwd=None):
        proc = _FakeProc(len(launched_procs) + 1)
        launched_procs.append(proc)
        return proc

    def _fake_assert_app_window(pid: int, expected_filename: str) -> None:
        if expected_filename == "first.pdf":
            raise RuntimeError("boom on first pdf")

    def _fake_run_agent(client, pdf_path: str, pdf_evidence_dir: Path):
        run_agent_calls.append(pdf_path)
        return "{}", [{"action": "click", "x": 11, "y": 22}], []

    def _fake_validate(raw: str, trace: list[dict], expected_pdf_name: str):
        return {
            "pdf": expected_pdf_name,
            "checklist": [
                {
                    "item_number": 1,
                    "item_label": "single-line Latin text (small font ≤12pt)",
                    "verdict": "PASS",
                    "observation": "No visible glyph-size jump detected at click target.",
                    "click_x": 11,
                    "click_y": 22,
                    "before_screenshot_taken": True,
                    "after_screenshot_taken": True,
                }
            ],
            "overall": "PASS",
        }

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(signoff_mod, "OpenAI", lambda api_key=None: object())
    monkeypatch.setattr(signoff_mod, "REFERENCE_PDFS", reference_pdfs)
    monkeypatch.setattr(signoff_mod, "SIGNOFF_FILE", signoff_path)
    monkeypatch.setattr(signoff_mod, "CUA_EVIDENCE_DIR", evidence_dir)
    monkeypatch.setattr(signoff_mod, "_git_head", lambda: "deadbeef")
    monkeypatch.setattr(signoff_mod, "_collect_artifact_hashes", lambda: {})
    monkeypatch.setattr(signoff_mod.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(signoff_mod, "_assert_app_window_shows_pdf", _fake_assert_app_window)
    monkeypatch.setattr(signoff_mod, "_run_agent_on_pdf", _fake_run_agent)
    monkeypatch.setattr(signoff_mod, "_validate_signoff_report", _fake_validate)

    rc = signoff_mod.main()

    assert rc == 1  # first PDF failed, so overall verdict must fail
    assert len(launched_procs) == 2
    assert all(proc.terminated for proc in launched_procs)
    assert all(proc.wait_calls == 1 for proc in launched_procs)
    assert run_agent_calls == ["second.pdf"]

    signoff = json.loads(signoff_path.read_text(encoding="utf-8"))
    results = signoff["checklist_results"]
    assert set(results.keys()) == set(reference_pdfs)
    assert results["first.pdf"]["overall"] == "FAIL"
    assert "runtime_error" in results["first.pdf"]["error"]
    assert results["second.pdf"]["overall"] == "PASS"

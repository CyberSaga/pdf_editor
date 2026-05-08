# scripts/ux_signoff_agent.py
"""
GPT-5.4/5.5 computer-use UX signoff for AC 6.

Normally invoked by scripts/verify_no_jump.py after both pytest runs complete,
which guarantees the signoff timestamp postdates artifact collection.
Can also be run standalone for debugging, but verify_no_jump.py is the gate.

Usage:  python scripts/ux_signoff_agent.py
Output: test_artifacts/signoff.json  (outside test_artifacts/no_jump/ so the
        pytest-artifact wipe in verify_no_jump.py never deletes it)

Requires: OPENAI_API_KEY environment variable, pip install openai
"""
from __future__ import annotations
import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
import textwrap
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: pip install openai pyautogui pillow")
    sys.exit(1)

try:
    import pyautogui
    from PIL import Image as _PILImage
except ImportError:
    print("ERROR: pip install pyautogui pillow")
    sys.exit(1)

REPO_ROOT    = Path(__file__).parent.parent
ARTIFACT_DIR = REPO_ROOT / "test_artifacts" / "no_jump"
# Outside ARTIFACT_DIR — verify_no_jump.py wipes ARTIFACT_DIR between runs.
SIGNOFF_FILE    = REPO_ROOT / "test_artifacts" / "signoff.json"
# CUA before/after screenshots — automation-layer evidence, not model-reported booleans.
# Lives outside ARTIFACT_DIR (not wiped between runs) so it survives until signoff check.
CUA_EVIDENCE_DIR = REPO_ROOT / "test_artifacts" / "cua_evidence"
REFERENCE_PDFS = [
    "test_files/test-colored-background.pdf",
    "test_files/test-complexed-layout.pdf",
]
MODEL = "gpt-5.4"          # update to gpt-5.5 when available
CHECKLIST = [
    "single-line Latin text (small font ≈8pt)",
    "single-line Latin text (large font ≥18pt)",
    "CJK heading",
    "CJK body text",
    "multi-line paragraph",
    "text near left page margin",
    "text near right page margin",
    "text with non-black color",
    "text on page 2 (if present, else skip)",
    "text at bottom quarter of the page",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def _git_head() -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "unknown"


_IMAGE_ARTIFACT_IDS: frozenset[str] = frozenset({
    # Cases that produce before/after/diff images — must match the verifier's expected key set.
    # Add new pixel/e2e cases here AND in verify_no_jump.py's _check_signoff() filter.
    "e2e_click_to_edit",
    "e2e_qtest_click_to_edit",
})


def _has_image_artifacts(tid: str) -> bool:
    """Return True for test IDs that produce before/after/diff PNG images."""
    return tid.startswith("pixel_") or tid in _IMAGE_ARTIFACT_IDS


def _collect_artifact_hashes() -> dict[str, str]:
    """Hash every pixel-case, end-to-end image artifact, and CUA screenshot pair.

    Keys are relative to REPO_ROOT/test_artifacts/ so the verifier can resolve
    them against its own ARTIFACT_DIR and CUA_EVIDENCE_DIR roots.

    Uses _has_image_artifacts() for pytest-case artifacts — the same predicate that
    verify_no_jump.py uses, so any drift causes a key-set mismatch at gate time.

    CUA evidence PNGs are discovered by walking CUA_EVIDENCE_DIR.
    """
    hashes: dict[str, str] = {}

    # Pytest image artifacts (pixel_* and e2e_* cases)
    if ARTIFACT_DIR.exists():
        for case_dir in sorted(ARTIFACT_DIR.iterdir()):
            if not case_dir.is_dir():
                continue
            tid = case_dir.name
            if not _has_image_artifacts(tid):
                continue
            for fname in ("before.png", "after.png", "diff.png"):
                p = case_dir / fname
                if p.exists():
                    hashes[f"no_jump/{tid}/{fname}"] = _sha256(p)

    # CUA before/after screenshots — automation-layer evidence, not model boolean flags
    if CUA_EVIDENCE_DIR.exists():
        for png in sorted(CUA_EVIDENCE_DIR.rglob("*.png")):
            rel = png.relative_to(REPO_ROOT / "test_artifacts")
            hashes[str(rel).replace("\\", "/")] = _sha256(png)

    return hashes


SYSTEM_PROMPT = textwrap.dedent("""\
    You are a visual QA agent performing a no-jump test on a PDF text editor.

    For each PDF session, you must:
    1. Take a screenshot to see the current state.
    2. Confirm the title bar shows the expected PDF filename. If it does not,
       output the literal string WRONG_PDF: <title bar text> and stop.
    3. Switch the editor to text-edit mode if not already active.
    4. For EACH checklist item:
       a. Take a screenshot BEFORE clicking (before_screenshot_taken = true).
       b. Click the matching text span; record click_x and click_y.
       c. Take a screenshot AFTER clicking (after_screenshot_taken = true).
       d. Observe whether glyphs shift size or position when the editor opens.
          Any visible shift — even 1 pixel — is a FAIL for that item.
    5. After completing all items, output ONLY a single JSON object — no
       surrounding prose, no markdown fences — matching this exact schema:

    {
      "pdf": "<filename>",
      "checklist": [
        {
          "item_number": <1-10>,
          "item_label": "<exact label from checklist>",
          "verdict": "PASS" | "FAIL" | "SKIP",
          "observation": "<one-sentence description of what you saw>",
          "click_x": <integer screen x, 0 if SKIP>,
          "click_y": <integer screen y, 0 if SKIP>,
          "before_screenshot_taken": true | false,
          "after_screenshot_taken": true | false
        }
      ],
      "overall": "PASS" | "FAIL"
    }

    Rules:
    - "overall" is "PASS" only when zero items have verdict "FAIL".
    - "overall" is "FAIL" if ANY item has verdict "FAIL".
    - At least 8 of the 10 items must be non-SKIP.
    - Non-SKIP items MUST have click_x > 0, click_y > 0, both screenshot
      flags true, and a non-empty observation.
    - Output ONLY the JSON object. Nothing before or after it.
""")


MAX_CUA_TURNS = 40  # hard cap to prevent runaway loops

_CUA_TOOL = [{
    "type": "computer_use_preview",
    "display_width":  1920,
    "display_height": 1080,
    "environment":    "windows",
}]


def _screenshot_b64() -> str:
    """Capture the full screen and return it as a base64-encoded PNG string."""
    img = pyautogui.screenshot()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _execute_cua_action(action: object) -> None:
    """Execute one computer_call action against the real desktop."""
    # action is an object; use getattr for safety
    atype = getattr(action, "type", None)
    if atype == "click":
        btn = getattr(action, "button", "left") or "left"
        pyautogui.click(action.x, action.y, button=btn)
    elif atype == "double_click":
        pyautogui.doubleClick(action.x, action.y)
    elif atype == "scroll":
        pyautogui.scroll(getattr(action, "delta_y", 0), x=action.x, y=action.y)
    elif atype == "type":
        pyautogui.typewrite(action.text, interval=0.02)
    elif atype == "key":
        keys = getattr(action, "keys", [])
        if keys:
            pyautogui.hotkey(*keys)
    elif atype == "move":
        pyautogui.moveTo(action.x, action.y)
    # "screenshot" type — no execution needed; screenshot captured after the loop step


def _extract_text(response: object) -> str:
    """Pull all text content out of a Responses API response."""
    text = ""
    for block in (getattr(response, "output", None) or []):
        if getattr(block, "type", None) == "computer_call":
            continue
        for attr in ("content", "text"):
            val = getattr(block, attr, None)
            if isinstance(val, str):
                text += val
            elif isinstance(val, list):
                for c in val:
                    if hasattr(c, "text"):
                        text += c.text
    return text.strip()


def _b64_to_png(b64_data: str, dest: Path) -> None:
    """Decode a base64 PNG string and write it to dest."""
    import base64 as _b64
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_b64.b64decode(b64_data))


def _assert_app_window_shows_pdf(pid: int, expected_filename: str) -> None:
    """Independently verify the launched process's window title contains the expected PDF.

    This is an OS-level check, not a model-reported assertion.  The CUA model
    can misreport the PDF it sees, but this check reads the real window title
    from the OS process list before the CUA loop begins.  If the window is not
    found within 20 seconds, we raise to abort the signoff — the gate cannot
    record PASS evidence for a PDF that was never displayed in the tested window.

    Uses PowerShell Get-Process.MainWindowTitle which works on Windows without
    third-party dependencies.  On non-Windows, falls back to a psutil-based check
    (not required for the plan, but noted for portability).
    """
    import time as _time
    deadline = _time.time() + 20
    last_title = ""
    while _time.time() < deadline:
        r = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).MainWindowTitle",
            ],
            capture_output=True, text=True,
        )
        last_title = r.stdout.strip()
        if expected_filename in last_title:
            print(f"[signoff] OS window title confirmed: {last_title!r}")
            return
        _time.sleep(0.5)
    raise RuntimeError(
        f"[signoff] FAIL — PID {pid} window title does not contain "
        f"{expected_filename!r} after 20 s.  Last title: {last_title!r}.  "
        f"The PDF was not loaded in the target window; CUA run aborted."
    )


def _run_agent_on_pdf(
    client: OpenAI, pdf_path: str, pdf_evidence_dir: Path
) -> tuple[str, list[dict], list[dict]]:
    """Drive a real computer-use agentic loop for one PDF session.

    Protocol (required by OpenAI CUA):
      1. Seed with an initial screenshot so the model sees the current state.
      2. On each turn, execute every computer_call action against the desktop.
      3. Take a post-action screenshot and return it as computer_call_output.
      4. Continue until the response contains no computer_call items.

    Returns (raw_text, action_trace, screenshot_pairs) where:
      - action_trace is an independent record of every pyautogui click.
      - screenshot_pairs is a list of {turn, clicks, before_path, after_path} dicts
        for every turn that contained click actions.  The before/after PNGs are
        saved to pdf_evidence_dir using our code — not the model's boolean flags —
        providing automation-layer evidence that real screenshots were captured.

    The model's observation text is supplemental.  The primary acceptance evidence
    is: (a) action_trace click coords matching checklist reports, and (b) screenshot
    pairs whose hashes are bound to the tamper-evident signoff.

    Fails fast if the model outputs WRONG_PDF (title bar mismatch).
    """
    pdf_evidence_dir.mkdir(parents=True, exist_ok=True)
    pdf_name = Path(pdf_path).name
    prompt = (
        f"The PDF editor should be displaying: {pdf_name}  (full path: {pdf_path})\n\n"
        f"First verify the title bar matches, then run this checklist:\n"
        + "\n".join(f"{i+1}. {item}" for i, item in enumerate(CHECKLIST))
    )

    # Seed: give the model an initial view of the screen
    init_shot = _screenshot_b64()
    response = client.responses.create(
        model=MODEL,
        tools=_CUA_TOOL,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
            {
                "type":    "computer_call_output",
                "call_id": "init_screenshot",
                "output":  {"type": "input_image",
                            "image_url": f"data:image/png;base64,{init_shot}"},
            },
        ],
        truncation="auto",
    )

    # Independent execution trace — records every real pyautogui click.
    action_trace: list[dict] = []
    # Per-turn screenshot pairs for turns that contained click actions.
    # Our code saves these PNGs — not model-reported boolean flags.
    screenshot_pairs: list[dict] = []
    prev_screenshot_b64 = init_shot   # screenshot immediately before this turn's actions

    for _turn in range(MAX_CUA_TURNS):
        computer_calls = [
            item for item in (getattr(response, "output", None) or [])
            if getattr(item, "type", None) == "computer_call"
        ]
        if not computer_calls:
            break   # model is done — no more actions

        before_b64 = prev_screenshot_b64  # capture before any action this turn
        turn_clicks: list[dict] = []

        # Execute every action, record clicks in the independent trace
        for call in computer_calls:
            action = getattr(call, "action", None) or call
            _execute_cua_action(action)
            atype = getattr(action, "type", None)
            if atype in ("click", "double_click"):
                entry = {
                    "action": atype,
                    "x": int(getattr(action, "x", 0)),
                    "y": int(getattr(action, "y", 0)),
                    "t": time.time(),
                }
                action_trace.append(entry)
                turn_clicks.append({"x": entry["x"], "y": entry["y"]})
            time.sleep(0.25)

        screenshot = _screenshot_b64()
        prev_screenshot_b64 = screenshot   # becomes "before" for the next turn

        # Save before/after PNGs for every turn that had real clicks.
        # These are NOT the model's boolean flags — they are our captured evidence.
        if turn_clicks:
            before_path = pdf_evidence_dir / f"turn_{_turn:02d}_before.png"
            after_path  = pdf_evidence_dir / f"turn_{_turn:02d}_after.png"
            _b64_to_png(before_b64, before_path)
            _b64_to_png(screenshot, after_path)
            screenshot_pairs.append({
                "turn":        _turn,
                "clicks":      turn_clicks,
                "before_path": str(before_path.relative_to(REPO_ROOT / "test_artifacts")),
                "after_path":  str(after_path.relative_to(REPO_ROOT / "test_artifacts")),
            })

        # Feed screenshot back as the result of the last computer_call
        response = client.responses.create(
            model=MODEL,
            tools=_CUA_TOOL,
            previous_response_id=response.id,
            input=[{
                "type":    "computer_call_output",
                "call_id": computer_calls[-1].call_id,
                "output":  {"type": "input_image",
                            "image_url": f"data:image/png;base64,{screenshot}"},
            }],
            truncation="auto",
        )
    else:
        print(f"[signoff] WARNING: hit MAX_CUA_TURNS={MAX_CUA_TURNS} for {pdf_name} — "
              f"treating as FAIL")
        return (
            "OVERALL: FAIL\n[CUA loop exceeded max turns without completing checklist]",
            action_trace, screenshot_pairs,
        )

    return _extract_text(response), action_trace, screenshot_pairs


def _validate_trace_vs_checklist(
    items: list[dict], trace: list[dict], errors: list[str]
) -> None:
    """Cross-check reported click coordinates against the independently recorded action trace.

    Uses 1:1 ordered matching: each non-SKIP checklist item that reports click_x/y > 0
    must consume a DISTINCT real click from the trace.  Pool-any matching (where every
    item can reuse the same single click) is rejected, so a model that made one real
    click but reported eight PASS items at the same coordinates will fail.

    A model that hallucinated a PASS JSON without ever clicking cannot satisfy this
    check, because the trace is populated by our own pyautogui calls — not by the
    model's output.
    """
    # Build ordered pool of real clicks (trace is already time-ordered)
    available_clicks = [
        (e["x"], e["y"]) for e in trace
        if e.get("action") in ("click", "double_click")
    ]

    non_skip_with_click = [
        i for i in items
        if i.get("verdict") != "SKIP" and i.get("click_x", 0) > 0
    ]
    if non_skip_with_click and not available_clicks:
        errors.append(
            "  execution trace contains ZERO recorded clicks, but non-SKIP items "
            "claim clicks were made — model self-reported without performing real actions"
        )
        return

    remaining = list(available_clicks)   # consumed 1:1; reuse is blocked
    for item in non_skip_with_click:
        n  = item.get("item_number", "?")
        cx = int(item.get("click_x", 0))
        cy = int(item.get("click_y", 0))
        # Find the FIRST unconsumed trace click within 15px
        matched_idx = next(
            (i for i, (tx, ty) in enumerate(remaining)
             if abs(tx - cx) <= 15 and abs(ty - cy) <= 15),
            None,
        )
        if matched_idx is None:
            errors.append(
                f"  item {n}: no unmatched recorded click within 15px of ({cx}, {cy}) — "
                f"click may be hallucinated or was already consumed by an earlier item. "
                f"Remaining unconsumed clicks: {remaining[:5]}{'…' if len(remaining) > 5 else ''}"
            )
        else:
            remaining.pop(matched_idx)   # consume — prevents one click matching many items


def _validate_signoff_report(
    raw: str, trace: list[dict], expected_pdf_name: str
) -> dict | None:
    """Parse and schema-validate the JSON checklist report emitted by the CUA agent.

    Returns the validated dict on success, or None (printing errors) on failure.
    Rejects: missing fields, empty observations, zero click coords on non-SKIP
    items, missing screenshot flags, < 8 non-SKIP items, any FAIL item, an overall
    verdict that is not exactly "PASS", a `pdf` field that does not match
    `expected_pdf_name`, duplicate or out-of-range item_number values, item_label
    values that do not match the CHECKLIST entry, or checklist items whose
    reported click coordinates do not match any real click in the independent
    execution trace.
    """
    import re as _re, json as _json

    if "WRONG_PDF:" in raw:
        print("[signoff] ERROR: agent reported wrong PDF loaded")
        return None

    # Strip optional markdown code fences
    text = raw.strip()
    fence = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, _re.DOTALL)
    json_str = fence.group(1) if fence else text

    try:
        data = _json.loads(json_str)
    except _json.JSONDecodeError as exc:
        print(f"[signoff] ERROR: JSON parse failed: {exc}")
        print(f"  Raw output (first 400 chars): {raw[:400]}")
        return None

    errors: list[str] = []

    # Verify the JSON's pdf field matches the PDF we actually launched.
    # Without this, a stale result from a previous PDF session can be keyed
    # under the wrong pdf_path without the validator catching it.
    reported_pdf = data.get("pdf", "")
    if reported_pdf != expected_pdf_name:
        errors.append(
            f"pdf field {reported_pdf!r} does not match expected {expected_pdf_name!r} — "
            f"wrong window was focused or model omitted WRONG_PDF"
        )

    if not isinstance(data.get("checklist"), list):
        errors.append("'checklist' field missing or not a list")
        print("[signoff] FAIL —", "\n  ".join(errors))
        return None

    items: list[dict] = data["checklist"]
    non_skip = [i for i in items if i.get("verdict") != "SKIP"]
    if len(non_skip) < 8:
        errors.append(f"at least 8 non-SKIP items required; got {len(non_skip)}")

    # item_number must be unique, within 1..10, and item_label must match CHECKLIST
    seen_numbers: set[int] = set()
    for item in items:
        n = item.get("item_number")
        if not isinstance(n, int) or not (1 <= n <= 10):
            errors.append(f"item_number {n!r} out of range 1–10")
        elif n in seen_numbers:
            errors.append(f"duplicate item_number {n} — model repeated the same slot")
        else:
            seen_numbers.add(n)
            expected_label = CHECKLIST[n - 1]
            actual_label = item.get("item_label", "")
            if actual_label != expected_label:
                errors.append(
                    f"item {n}: item_label {actual_label!r} does not match "
                    f"CHECKLIST entry {expected_label!r}"
                )

    for item in items:
        n = item.get("item_number", "?")
        v = item.get("verdict")
        if v not in ("PASS", "FAIL", "SKIP"):
            errors.append(f"item {n}: verdict must be PASS/FAIL/SKIP, got {v!r}")
        if v == "FAIL":
            errors.append(f"item {n}: FAIL verdict — visible glyph jump detected")
        if v != "SKIP":
            obs = item.get("observation", "")
            if not (isinstance(obs, str) and obs.strip()):
                errors.append(f"item {n}: missing/empty observation")
            cx, cy = item.get("click_x", 0), item.get("click_y", 0)
            if not (isinstance(cx, (int, float)) and cx > 0):
                errors.append(f"item {n}: click_x must be > 0, got {cx!r}")
            if not (isinstance(cy, (int, float)) and cy > 0):
                errors.append(f"item {n}: click_y must be > 0, got {cy!r}")
            if not item.get("before_screenshot_taken"):
                errors.append(f"item {n}: before_screenshot_taken must be true")
            if not item.get("after_screenshot_taken"):
                errors.append(f"item {n}: after_screenshot_taken must be true")

    if data.get("overall") != "PASS":
        errors.append(f"overall verdict is {data.get('overall')!r}, expected 'PASS'")

    # Cross-check: reported click coords must match the independent execution trace.
    # This cannot be forged because the trace is populated by our pyautogui calls.
    _validate_trace_vs_checklist(items, trace, errors)

    if errors:
        print("[signoff] FAIL — schema validation errors:")
        for e in errors:
            print(f"  {e}")
        return None
    return data


def main() -> int:
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    git_commit = _git_head()
    timestamp  = time.time()
    parsed_results: dict[str, dict] = {}
    overall_verdict = "PASS"

    # Wipe CUA evidence from any previous run before starting a new one.
    if CUA_EVIDENCE_DIR.exists():
        shutil.rmtree(CUA_EVIDENCE_DIR)
    CUA_EVIDENCE_DIR.mkdir(parents=True)

    for pdf_path in REFERENCE_PDFS:
        pdf_slug = Path(pdf_path).stem.replace(" ", "_")
        pdf_evidence_dir = CUA_EVIDENCE_DIR / pdf_slug

        print(f"[signoff] Launching app with {pdf_path} ...")
        app_proc = subprocess.Popen(
            [sys.executable, "main.py", pdf_path], cwd=REPO_ROOT
        )
        try:
            _assert_app_window_shows_pdf(app_proc.pid, Path(pdf_path).name)
            print(f"[signoff] Running CUA checklist for {pdf_path} ...")
            raw, trace, screenshot_pairs = _run_agent_on_pdf(client, pdf_path, pdf_evidence_dir)
            print(f"[signoff] Execution trace: {len(trace)} click(s), "
                  f"{len(screenshot_pairs)} screenshot pair(s) saved")
            pdf_name = Path(pdf_path).name
            validated = _validate_signoff_report(raw, trace, expected_pdf_name=pdf_name)
            if validated is None:
                print(f"[signoff] FAIL — schema validation failed for {pdf_path}")
                overall_verdict = "FAIL"
                parsed_results[pdf_path] = {
                    "overall": "FAIL", "error": "schema_invalid",
                    "action_trace": trace,
                    "screenshot_pairs": screenshot_pairs,
                }
            else:
                print(f"[signoff] {pdf_path}: {validated['overall']}")
                validated["action_trace"]      = trace
                validated["screenshot_pairs"]  = screenshot_pairs
                parsed_results[pdf_path] = validated
                if validated.get("overall") != "PASS":
                    overall_verdict = "FAIL"
        finally:
            app_proc.terminate()
            try:
                app_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                app_proc.kill()

    signoff = {
        "model":             MODEL,
        "git_commit":        git_commit,
        "timestamp":         timestamp,
        "pdfs_tested":       REFERENCE_PDFS,
        "checklist_results": parsed_results,
        "artifact_hashes":   _collect_artifact_hashes(),
        "verdict":           overall_verdict,
    }
    SIGNOFF_FILE.parent.mkdir(parents=True, exist_ok=True)
    SIGNOFF_FILE.write_text(json.dumps(signoff, indent=2), encoding="utf-8")
    print(f"\n[signoff] Written to {SIGNOFF_FILE}")
    print(f"[signoff] VERDICT: {overall_verdict}")
    return 0 if overall_verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

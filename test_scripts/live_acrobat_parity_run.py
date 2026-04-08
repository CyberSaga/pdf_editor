from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import time
from collections.abc import Callable
from ctypes import windll
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pyautogui
import pygetwindow as gw
import pyperclip
import win32com.client
import win32gui
import win32ui
from PIL import Image, ImageChops, ImageGrab, ImageStat

__test__ = False


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "test_scripts" / "test_outputs" / "live_parity"
ACROBAT_LABEL = "acrobat"
EDITOR_LABEL = "pdf_editor"


@dataclass(frozen=True)
class AppWindow:
    label: str
    title_substring: str


@dataclass(frozen=True)
class AppSnapshot:
    label: str
    title: str
    hwnd: int
    rect: tuple[int, int, int, int]


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    app: str
    start_time: str
    end_time: str
    verdict: str
    friction_notes: str
    saved_output_path: str = ""


TaskAction = Callable[[AppSnapshot, Path], tuple[str, str]]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_output_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def minimize_noise_windows() -> None:
    for target in ("Codex", "Gemini - Google Chrome", "聊天 | 陳俐安 冠呈 | Microsoft Teams"):
        for window in gw.getWindowsWithTitle(target):
            try:
                window.minimize()
            except Exception:
                continue


def resolve_window(snapshot: AppWindow) -> AppSnapshot:
    matches: list[tuple[int, str]] = []

    def enum(hwnd: int, _: object) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if snapshot.title_substring in title:
            matches.append((hwnd, title))

    win32gui.EnumWindows(enum, None)
    if not matches:
        raise RuntimeError(f"Could not find window containing title substring: {snapshot.title_substring!r}")
    hwnd, title = matches[0]
    rect = win32gui.GetWindowRect(hwnd)
    return AppSnapshot(label=snapshot.label, title=title, hwnd=hwnd, rect=rect)


def activate_window(app: AppSnapshot) -> tuple[int, int]:
    shell = win32com.client.Dispatch("WScript.Shell")
    shell.AppActivate(app.title)
    time.sleep(0.6)
    left, top, right, bottom = app.rect
    width = right - left
    height = bottom - top
    click_x = left + max(160, min(width // 2, width - 120))
    click_y = top + max(140, min(height // 2, height - 120))
    pyautogui.click(click_x, click_y)
    time.sleep(0.5)
    return click_x, click_y


def capture_window(app: AppSnapshot, path: Path) -> Path:
    left, top, right, bottom = app.rect
    width = right - left
    height = bottom - top
    hwnd_dc = win32gui.GetWindowDC(app.hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
    save_dc.SelectObject(bitmap)
    print_result = windll.user32.PrintWindow(app.hwnd, save_dc.GetSafeHdc(), 0)
    if print_result != 1:
        image = ImageGrab.grab(bbox=(left, top, right, bottom))
        image.save(path)
    else:
        bitmap_info = bitmap.GetInfo()
        bitmap_bytes = bitmap.GetBitmapBits(True)
        image = Image.frombuffer(
            "RGB",
            (bitmap_info["bmWidth"], bitmap_info["bmHeight"]),
            bitmap_bytes,
            "raw",
            "BGRX",
            0,
            1,
        )
        image.save(path)
    win32gui.DeleteObject(bitmap.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(app.hwnd, hwnd_dc)
    return path


def diff_ratio(before: Path, after: Path) -> float:
    before_image = Image.open(before).convert("RGB")
    after_image = Image.open(after).convert("RGB")
    width = min(before_image.width, after_image.width)
    height = min(before_image.height, after_image.height)
    before_image = before_image.crop((0, 0, width, height))
    after_image = after_image.crop((0, 0, width, height))
    diff = ImageChops.difference(before_image, after_image)
    if diff.getbbox() is None:
        return 0.0
    stat = ImageStat.Stat(diff)
    return sum(channel_mean / 255 for channel_mean in stat.mean) / 3


def run_task(app: AppSnapshot, output_dir: Path, task_id: str, action: TaskAction) -> TaskResult:
    start_time = now_iso()
    before = output_dir / f"{task_id}_{app.label}_before.png"
    after = output_dir / f"{task_id}_{app.label}_after.png"
    capture_window(app, before)
    verdict, friction = action(app, after)
    end_time = now_iso()
    return TaskResult(
        task_id=task_id,
        app=app.label,
        start_time=start_time,
        end_time=end_time,
        verdict=verdict,
        friction_notes=friction,
    )


def page_navigation_action(app: AppSnapshot, after_path: Path) -> tuple[str, str]:
    activate_window(app)
    for _ in range(3):
        pyautogui.press("pagedown")
        time.sleep(0.35)
    time.sleep(0.7)
    capture_window(app, after_path)
    ratio = diff_ratio(after_path.with_name(after_path.name.replace("_after", "_before")), after_path)
    verdict = "PASS" if ratio > 0.015 else "FAIL"
    note = f"Three PageDown presses; before/after diff ratio={ratio:.4f}."
    return verdict, note


def zoom_flow_action(app: AppSnapshot, after_path: Path) -> tuple[str, str]:
    activate_window(app)
    pyautogui.hotkey("ctrl", "+")
    time.sleep(0.5)
    pyautogui.hotkey("ctrl", "-")
    time.sleep(0.5)
    pyautogui.hotkey("ctrl", "0")
    time.sleep(0.5)
    pyautogui.press("pagedown")
    time.sleep(0.7)
    capture_window(app, after_path)
    ratio = diff_ratio(after_path.with_name(after_path.name.replace("_after", "_before")), after_path)
    verdict = "PASS" if ratio > 0.008 else "FAIL"
    note = f"Ctrl+plus, Ctrl+minus, Ctrl+0, then PageDown; diff ratio={ratio:.4f}."
    return verdict, note


def reading_state_action(app: AppSnapshot, after_path: Path) -> tuple[str, str]:
    activate_window(app)
    pyautogui.hotkey("alt", "tab")
    time.sleep(0.7)
    activate_window(app)
    time.sleep(0.6)
    capture_window(app, after_path)
    ratio = diff_ratio(after_path.with_name(after_path.name.replace("_after", "_before")), after_path)
    verdict = "PASS" if ratio < 0.02 else "FAIL"
    note = f"Focus switched away and back; viewport stability diff ratio={ratio:.4f}."
    return verdict, note


def selection_copy_action(app: AppSnapshot, after_path: Path) -> tuple[str, str]:
    activate_window(app)
    left, top, right, bottom = app.rect
    width = right - left
    height = bottom - top
    start_x = left + int(width * 0.28)
    start_y = top + int(height * 0.34)
    end_x = left + int(width * 0.58)
    end_y = start_y
    pyperclip.copy("")
    pyautogui.moveTo(start_x, start_y, duration=0.2)
    pyautogui.dragTo(end_x, end_y, duration=0.35, button="left")
    time.sleep(0.5)
    pyautogui.hotkey("ctrl", "c")
    time.sleep(0.6)
    capture_window(app, after_path)
    clipboard = pyperclip.paste().strip()
    verdict = "PASS" if clipboard else "FAIL"
    note = (
        "Horizontal drag selection then Ctrl+C. "
        f"Clipboard length={len(clipboard)}."
    )
    return verdict, note


def blocked_action(reason: str) -> TaskAction:
    def _run(_: AppSnapshot, after_path: Path) -> tuple[str, str]:
        # Keep an after-capture so the evidence pack still has a complete row.
        _.rect  # keep signature use explicit
        capture_window(_, after_path)
        return "BLOCKED", reason

    return _run


def render_markdown(results: list[TaskResult], output_dir: Path, recording_path: Path | None) -> str:
    lines = [
        "# Focused Live Acrobat-vs-Editor Parity Run",
        "",
        "## Evidence Pack",
        f"- Output directory: `{output_dir.relative_to(REPO_ROOT).as_posix()}`",
    ]
    if recording_path is not None:
        lines.append(f"- Screen recording: `{recording_path.relative_to(REPO_ROOT).as_posix()}`")
    lines.extend(
        [
            "",
            "## Results",
            "| task_id | app | start_time | end_time | verdict | friction_notes | saved_output_path |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for row in results:
        lines.append(
            f"| `{row.task_id}` | `{row.app}` | `{row.start_time}` | `{row.end_time}` | `{row.verdict}` | {row.friction_notes} | `{row.saved_output_path}` |"
        )
    return "\n".join(lines)


def write_csv(results: list[TaskResult], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "task_id",
                "app",
                "start_time",
                "end_time",
                "verdict",
                "friction_notes",
                "saved_output_path",
            ],
        )
        writer.writeheader()
        for row in results:
            writer.writerow(row.__dict__)


def ffmpeg_path() -> str | None:
    for candidate in (shutil.which("ffmpeg"), r"C:\yt-dlp\ffmpeg\bin\ffmpeg.exe"):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def start_recording(output_path: Path) -> subprocess.Popen[str] | None:
    binary = ffmpeg_path()
    if not binary:
        return None
    command = [
        binary,
        "-y",
        "-f",
        "gdigrab",
        "-framerate",
        "15",
        "-i",
        "desktop",
        str(output_path),
    ]
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop_recording(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a focused live Acrobat-vs-editor parity pass.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--acrobat-title", default="Adobe Acrobat Pro")
    parser.add_argument("--editor-title", default="視覺化 PDF 編輯器")
    args = parser.parse_args(argv)

    pyautogui.PAUSE = 0.2
    pyautogui.FAILSAFE = True

    output_dir = ensure_output_dir(args.output_dir)
    minimize_noise_windows()

    acrobat = resolve_window(AppWindow(label=ACROBAT_LABEL, title_substring=args.acrobat_title))
    editor = resolve_window(AppWindow(label=EDITOR_LABEL, title_substring=args.editor_title))

    recording_path = output_dir / "screen_recording.mp4"
    recording_process = start_recording(recording_path)

    task_plan: list[tuple[str, TaskAction]] = [
        ("navigation.page_down", page_navigation_action),
        ("navigation.zoom_flow", zoom_flow_action),
        ("navigation.reading_state_continuity", reading_state_action),
        ("selection.copy", selection_copy_action),
        (
            "edit.discard",
            blocked_action("Blocked: existing-text edit entry is not exposed through a reliably comparable workflow in both apps for this scripted pass."),
        ),
        (
            "edit.commit",
            blocked_action("Blocked: existing-text commit interaction is not safely comparable in both apps for this scripted pass."),
        ),
        (
            "edit.undo_redo",
            blocked_action("Blocked: undo/redo parity depends on the blocked commit-edit scenario."),
        ),
        (
            "persistence.save_as",
            blocked_action("Blocked: Save As persistence parity depends on the blocked commit-edit scenario."),
        ),
    ]

    results: list[TaskResult] = []
    try:
        for task_id, action in task_plan:
            # Reacquire windows before each task in case the window handle changes.
            acrobat = resolve_window(AppWindow(label=ACROBAT_LABEL, title_substring=args.acrobat_title))
            editor = resolve_window(AppWindow(label=EDITOR_LABEL, title_substring=args.editor_title))
            results.append(run_task(acrobat, output_dir, task_id, action))
            results.append(run_task(editor, output_dir, task_id, action))
            time.sleep(1.0)
    finally:
        stop_recording(recording_process)

    csv_path = output_dir / "results.csv"
    markdown_path = output_dir / "report.md"
    write_csv(results, csv_path)
    markdown_path.write_text(render_markdown(results, output_dir, recording_path if recording_process else None), encoding="utf-8")

    print(f"Wrote CSV: {csv_path}")
    print(f"Wrote report: {markdown_path}")
    if recording_process:
        print(f"Wrote screen recording: {recording_path}")
    else:
        print("Screen recording not started because ffmpeg was unavailable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

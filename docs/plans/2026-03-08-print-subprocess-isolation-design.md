# Print Subprocess Isolation Design

## Goal

Keep the main window responsive during the full Windows print lifecycle, including driver submission stalls, by isolating raster print execution in a helper subprocess while preserving deferred close behavior and clear UI feedback.

## Root Cause

The current background `QThread` removes direct work from the GUI thread, but the Windows print submission still runs inside the main app process through `src/printing/qt_bridge.py`. That leaves the app vulnerable to process-wide stalls in the Qt/GDI print path even after progress reaches the `submitting print job` phase.

## Chosen Approach

Use a controller-managed helper subprocess for Windows print submission.

- the main app prepares an immutable print job bundle in a temp directory
- the helper subprocess owns snapshot rendering, watermark application, and `QPrinter` / `QPainter` submission end-to-end
- the main process observes child lifecycle through `QProcess` and line-delimited JSON events on `stdout`
- the controller keeps the existing deferred-close model, but now tracks an active child process and a hang watchdog

## IPC Contract

The helper receives a single JSON job file path on startup.

The job file contains:

- `job_id`
- `input_pdf_path`
- `watermarks`
- normalized print options
- heartbeat interval metadata

The helper emits newline-delimited JSON events to `stdout`:

- `started`
- `progress`
- `heartbeat`
- `succeeded`
- `failed`

Each event includes `job_id`, `event`, `message`, and any error payload needed by the controller for logs and UI.

## Hang Detection Policy

The main controller records the last helper activity timestamp from any progress or heartbeat event.

- if the helper stays silent for 30 seconds, the controller enters a `print subsystem not responding` UI state
- the progress dialog message changes to a dedicated stalled message
- the user may terminate only the child process
- terminating the child cleans up temp files, IPC, watchdog timers, and returns the app to normal without restarting the window

## Lifecycle Handling

Close deferral now covers the full duration from print click until helper exit.

- while the helper is active, normal close is deferred
- once the user requests close, the status text changes to the existing closing-pending message
- success and error dialogs are suppressed after close is pending
- when the helper exits and cleanup completes, the controller auto-closes the window

If the helper is terminated after a hang:

- the controller logs the stall and termination
- the view returns to the non-printing state
- the window remains usable

## Testing

Add controller regressions for:

- subprocess-backed print start returning immediately
- close deferral while helper is still active
- watchdog transition into stalled UI after missing heartbeats
- terminating the helper clears print state without closing the app
- success cleanup still restores the regular status bar message

Add helper-level tests for:

- JSON event encoding
- success and failure result mapping

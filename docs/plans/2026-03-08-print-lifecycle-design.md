# Print Lifecycle Rebuild Design

## Goal

Rebuild print submission from commit `892c069033e33ff683a55477a3969e06bbbbdc82` so that:

- snapshot generation no longer blocks the UI thread
- closing during print submission defers shutdown safely and auto-closes after submission completes
- print status messaging does not wipe the normal status bar state

## Chosen Approach

Use a controller-owned background worker running in a `QThread`.

The UI thread captures immutable print input before the worker starts:

- document snapshot bytes from the active PDF
- a copied list of watermark definitions for print overlays
- normalized print options

The worker opens the captured bytes in its own `fitz.Document`, applies copied watermark overlays, submits the print job through `PrintDispatcher.print_pdf_bytes()`, and emits success or failure back to the controller.

## Lifecycle Handling

When the user closes the window during an active print submission:

- the close event is ignored for that attempt
- the controller enters a `closing pending` state
- the print status message changes from `列印中...` to `正在完成最後工作，請稍候...`
- interactive print entry points remain disabled
- once the worker finishes and controller cleanup is complete, the controller triggers `view.close()` again

This avoids blocking inside `closeEvent()` while still honoring the user’s intent to close the app once background work is finished.

## Status Bar Strategy

The view gets a print-status override API instead of direct `status_bar.clearMessage()`.

- normal document state remains computed by `_update_status_bar()`
- print submission sets an override message
- clearing the override restores the regular computed status text

This prevents print cleanup from erasing unrelated document/search/page state.

## Testing

Add controller-level regression coverage for:

- no snapshot build before the dialog is accepted
- snapshot generation happens off-thread while the UI remains responsive
- closing during a blocked print submission defers shutdown, updates the status message, and auto-closes after completion
- print cleanup restores the normal status bar message instead of leaving it blank

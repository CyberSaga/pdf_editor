# B1 — Delete app-image via invocation removal (design)

**PR-15 of Milestone 2.** Design-only; no production or test code lands in this PR.
Parent plan: `plans/milestone-2-bugs-security.md` §4. Implementation follows in PR-16.

Verified against HEAD `4a8e171`, PyMuPDF **1.27.1** (the `.venv` version — the system
Python's 1.25.5 is not authoritative here).

---

## 1. The bug, measured

`_delete_object_impl`'s image branch (`model/pdf_object_ops.py:885-893`) deletes an
app-inserted image by redacting its rectangle:

```python
if payload["kind"] == "image":
    old_rect = fitz.Rect(payload.get("rect") or annot.rect)
    page.add_redact_annot(old_rect)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)
```

`apply_redactions` is a *geometric* operation: it destroys everything the rectangle
touches, not the one object the user selected. Move and rotate were converted away from
this in `c099b28`; delete was not.

I measured the blast radius directly (PyMuPDF 1.27.1, scratch probe, not a fixture):

| Collateral | Setup | Before | After deleting the image |
|---|---|---|---|
| **Overlapping image** | A at `(10,10,80,80)`, B at `(40,40,110,110)`, distinct pixels → distinct xrefs | 2 invocations | **0 invocations** — A destroyed with B |
| **Text under the image** | `"UNDER THE IMAGE"` drawn at `(45,70)`, image rect `(40,40,110,110)` | `"UNDER THE IMAGE\nFAR AWAY"` | **`"AGE\nFAR AWAY"`** — partial glyph removal |
| **Vector art touching the rect** | two `draw_line`s, one crossing the image rect | 2 drawings | **1 drawing** |

So the TODOS framing ("can remove overlapping neighbor images") **understates the defect**.
Deleting an app-image silently corrupts *text* and *line art* under it as well. All three
vectors have the same root cause and the same fix; PR-16 pins all three.

The redaction call is also inconsistent with the neighbouring branches: the
`native_image` branch (`:869-875`) already deletes via `_remove_native_image_invocation`,
and `move_object`/`rotate` resolve through `_resolve_marker_image_invocation` +
`_rewrite_native_image_matrix`. The app-image delete branch is the last redaction holdout.

---

## 2. Resolution path

Reuse the move/rotate resolution verbatim. `_resolve_marker_image_invocation`
(`:256-279`) is xref-drift tolerant and digest-verified, and it backfills a drifted
`xref`/`image_digest` into the payload:

```python
invocation = _resolve_marker_image_invocation(model, request.page_num, payload, old_rect)
if invocation is None:
    return False
if not _remove_native_image_invocation(model, invocation):
    return False
_delete_app_object_annots(model, request.page_num, request.object_id, expected_kind="image")
return True
```

`_remove_native_image_invocation` (`:281-324`) already does exactly the right thing:
it excises the `q … cm … /Name Do … Q` token range from the invocation's own content
stream, then nulls `Resources/XObject/<name>` **only if the name is no longer referenced
by any of the page's content streams**.

**Ordering.** Resolve *before* deleting the marker annot — the marker's payload
(`xref`, `image_digest`, `rect`, `rotation`) is the resolution input. `update_stream` and
`xref_set_key` do not invalidate annotation handles, but PR-16 re-finds the annot through
`_delete_app_object_annots` rather than reusing the handle, matching the existing style
and staying robust to a future PyMuPDF that does invalidate.

---

## 3. Ambiguity fallback — decision: **fail-safe, no redaction fallback**

`_find_app_image_invocation` returns `None` when it cannot uniquely identify the
placement (geometric fallback with >1 same-digest candidate, or >1 candidate and no
digest). On `None`, delete **returns `False`**. No redaction fallback.

Rationale:

1. **Redaction is the data-loss vector being removed.** Keeping it as a fallback keeps
   the bug, merely rarer and harder to reproduce.
2. **It is exactly what move and rotate already do.** `move_object` (`:715-716`) and the
   rotate path (`:815-822`) both `return False` on an unresolvable app-image. Delete
   adopting the same failure mode introduces no new *class* of behavior.
3. **`False` is already a safe, wired-up outcome.** `delete_objects_atomic` (`:941-960`)
   restores the pre-delete snapshot and returns `False`; `PDFController.delete_object`
   (`controller/pdf_controller.py:1693-1694`) returns without recording a
   `SnapshotCommand`. Net effect: a silent no-op, document byte-identical, undo stack
   untouched.
4. The rejected alternative — "delete the marker only, leave the pixels" — is strictly
   worse: it leaves a visible image that is no longer selectable, so the user cannot
   even retry.

**Measured non-issue: identical twins are not ambiguous.** Two app-images with identical
bytes at an *identical* rect share one xref (`5`) but get distinct XObject names
(`fzImg0`, `fzImg1`) in distinct content streams (`8`, `9`). `_find_app_image_invocation`
takes the `xref_candidates` branch, digest-verifies both, and `min(…, key=_rect_dist)`
returns the first. Deleting either marker removes one placement and one marker — the
outcome is indistinguishable from "the right one". The `None` path is only reachable once
the recorded xref has drifted away from every live invocation (post-GC renumbering) *and*
two same-digest candidates sit within 2.0pt of the expected rect.

---

## 4. Marker + mutation bookkeeping

**Marker annot:** deleted via `_delete_app_object_annots(..., expected_kind="image")`.
Today's code re-finds it after `apply_redactions` (which invalidates handles) and calls
`delete_annot`; the helper does the same loop and is the established path.

**Mutation registration — deviation from the PR-15 brief, argued here.** The parent plan
says the new path "must keep both" marker deletion *and* `_register_mutation`. It must
**not** call `_register_mutation`.

`_remove_native_image_invocation` already performs that exact bookkeeping internally
(`:322-323`):

```python
model.pending_edits.append({"page_idx": invocation.page_num - 1, "rect": fitz.Rect(invocation.bbox)})
model.edit_count += 1
```

which is byte-for-byte what `_register_mutation` (`:674-677`) does. Calling both would
append a duplicate `pending_edits` entry and **double-increment `edit_count`**. Every
precedent agrees: the `native_image` delete branch calls `_remove_native_image_invocation`
and returns without registering; `move_object`'s image branch calls
`_rewrite_native_image_matrix` and returns without registering. Only the *redact*-based
textbox branches call `_register_mutation`, because redaction does no bookkeeping of its
own. Removing the redaction removes the need for the registration.

**R6-01 GC guarantee is unaffected.** It does not depend on `_register_mutation`:
`delete_objects_atomic` sets `model.secure_save_required = True` unconditionally
(`:959`), and the save path turns that into `_atomic_full_save(doc, path, garbage=4)`
(`model/pdf_model.py:2773-2775`). An image xref orphaned by invocation removal is
therefore reclaimed at save exactly as one orphaned by redaction was.

---

## 5. Shared-xref semantics

Two app-images inserted from **identical bytes** dedupe to one image xref. Measured:

```
[shared] invocations: [('fzImg0', xref=5, stream=8), ('fzImg1', xref=5, stream=9)]
[shared] get_images:  [(5, 'fzImg0'), (5, 'fzImg1')]
same xref? True   same name? False
```

Distinct XObject *names* pointing at one xref. So `_remove_native_image_invocation`'s
`still_referenced` scan — "does `/fzImg1` appear in any of the page's content streams
after the excision?" — correctly answers *no* for the deleted placement and nulls only
`Resources/XObject/fzImg1`. `fzImg0` keeps referencing xref 5, so **the xref survives
while the neighbour still uses it**, and is collected by the `garbage=4` save only once
the last name referencing it is gone.

No code change is needed for this; PR-16 pins it with
`test_delete_one_of_two_shared_xref_images_neighbor_survives`.

---

## 6. Undo interplay — unchanged

`_restore_delete_transaction` (`:906-920`) is snapshot-based: it restores the document
bytes, `pending_edits`, `edit_count`, and `secure_save_required`, then rebuilds the text
index. It is agnostic to *how* the delete mutated the document. Its two callers
(failure and exception inside `delete_objects_atomic`) are untouched.

The controller's undo record is likewise snapshot-based (`SnapshotCommand` with
`before_bytes`/`after_bytes`, `controller/pdf_controller.py:1692-1705`). Undo after an
invocation-removal delete restores the pre-delete bytes verbatim, so the image, its
marker, and any previously-collateral-damaged text/art all come back. Pinned by
`test_delete_app_image_then_undo_restores_both`.

---

## 7. Form-nested images

App images are inserted with `page.insert_image(...)` (`add_image_object`, `:441`),
which appends a page-level content stream. Measured: `is_form_nested=False`,
`cm_operator_index=1`, `q_image_invocation_count=1`, one fresh stream xref per insert
(page `/Contents` grew `[6] → [6,10,12]`).

So the app-image path cannot *originate* a form-nested invocation. It does not need to:
`_remove_native_image_invocation` already branches on `is_form_nested` (`:308-313`),
scanning the form's single stream and pruning from `resource_owner_xref` instead of the
page. If a future import/optimize pass ever wraps page content into a Form XObject, the
helper handles it and `_resolve_marker_image_invocation` still resolves by digest. No
extra handling; no guard needed.

---

## 8. Red-light tests PR-16 will write

All in `test_scripts/test_image_objects_model.py`, all synthesized in-test via the
existing `_png_bytes()` / `_make_pdf()` helpers — **no `test_files/` dependency**, so the
blocking Windows CI leg runs every one of them.

`_png_bytes()` currently takes no argument and always emits a red 1×1 PNG. PR-16 gives it
an optional `rgb=(255, 0, 0)` parameter (default preserves every existing caller) so
distinct-digest images can be synthesized.

| Test | Asserts | Expected red-light failure |
|---|---|---|
| `test_delete_overlapping_app_images_neighbor_survives` | A `(10,10,80,80)` red, B `(40,40,110,110)` blue; delete B → `discover_native_image_invocations` 2→1; A still hit-detectable at `(20,20)`; B's point `(100,100)` empty | `AssertionError: Expected 1 invocation after delete (A must survive), got 0` |
| `test_delete_app_image_preserves_underlying_text` | text `"UNDER THE IMAGE"` at `(45,70)` beneath image `(40,40,110,110)`; delete → `page.get_text()` still contains the full string | fails: text reads `"AGE"` (partial glyph removal) |
| `test_delete_app_image_preserves_underlying_vector_art` | a `draw_line` crossing the image rect; delete → `len(page.get_drawings())` unchanged | fails: `2 != 1` |
| `test_delete_one_of_two_shared_xref_images_neighbor_survives` | A and B from **identical** bytes (one xref, two names); delete B → 1 invocation remains **and** its `xref` still resolves to a live image stream | fails: 0 invocations |
| `test_delete_app_image_ambiguous_resolution_fails_safely` | twins at one rect; rewrite one marker's payload `xref` to a dead value to force the geometric+digest fallback to see 2 candidates → `delete_object` returns `False`, invocation count and marker count unchanged, no redaction fired | `AssertionError: ambiguous resolution must fail safe, not redact` — today's code returns `True` (it redacts without resolving) |
| `test_delete_app_image_then_undo_restores_both` | delete under overlap, `command_manager.undo()`, both images hit-detectable again | fails: A never survived the delete |
| `test_delete_overlapping_app_image_survives_save_reopen` | delete B, `save_as`, reopen, A still present and hit-detectable | fails: A gone before the save |

**Behavior pin — tightened.** `test_delete_image_object_removes_marker_and_page_image_ref`
asserted only `len(after_images) <= len(before_images)`, which holds vacuously. Measured
after the fix: nulling `Resources/XObject/<name>` **does** drop the entry, so the assertion
is now the exact `after_images == []`, plus `secure_save_required is True` to pin the R6-01
GC guarantee at its real source. Its stale comment (claiming delete forces an *immediate*
`garbage=4` round-trip that replaces `model.doc`) was corrected: the rewrite is deferred to
the save, via `secure_save_required`.

Measured bookkeeping after the fix: `edit_count == 2` for add-then-delete (one increment
each) — confirming the single-registration decision in §4 does not under- or over-count.

Also must stay green: `test_move_overlapping_app_images_both_survive`,
`test_rotate_overlapping_app_image_neighbour_survives`,
`test_move_second_of_identical_app_images_moves_correct_placement`.

---

## 9. Diff shape

Production diff is one file, `model/pdf_object_ops.py`, replacing lines 885-893:

```python
    if payload["kind"] == "image":
        old_rect = fitz.Rect(payload.get("rect") or annot.rect)
-       page.add_redact_annot(old_rect)
-       page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)
-       restored = _find_app_object_annot(model, request.page_num, request.object_id, "image")
-       if restored is not None:
-           restored[0].delete_annot(restored[1])
-       _register_mutation(model, request.page_num - 1, old_rect)
-       return True
+       if not int(payload.get("xref", 0) or 0):
+           return False
+       invocation = _resolve_marker_image_invocation(model, request.page_num, payload, old_rect)
+       if invocation is None:
+           return False
+       if not _remove_native_image_invocation(model, invocation):
+           return False
+       _delete_app_object_annots(model, request.page_num, request.object_id, expected_kind="image")
+       return True
```

The `xref` guard mirrors `move_object:712-713`. No new helper is introduced, so
`docs/ARCHITECTURE.md` needs no update (no public API change). `docs/PITFALLS.md` gains
one entry: *"`apply_redactions` is geometric — it destroys text and line art under the
rect, not just the targeted image."*

---

## 10. Rollback

Single-file production diff; `git revert` restores the redaction path exactly. The bug
then returns to its known, documented state (collateral destruction on overlap-delete)
rather than to something new. The analogous move/rotate conversion (`c099b28`) has been
stable since it landed.

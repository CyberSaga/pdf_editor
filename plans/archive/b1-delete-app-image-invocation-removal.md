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

## 10. Adversarial review findings (post-implementation, 2026-07-10)

An adversarial review of the landed diff raised three MAJOR findings against
`_remove_native_image_invocation` — the helper this PR newly routes app-image deletes
through. Each was reproduced (or refuted) by measurement rather than accepted on argument.

### 10.1 CONFIRMED — `/fzImg1` substring-matches `/fzImg10`

The retention check was `b"/fzImg1" in doc.xref_stream(x)`. PDF name tokens are delimited,
so with 11+ images on a page the token `/fzImg10` in a neighbour's stream makes `fzImg1`
look "still referenced" and its resource entry is never pruned.

**Reproduced:** 12 images, delete `fzImg1` → `page.get_images()` stays at 12.

**Reviewer's stated consequence was wrong.** It claimed the image bytes "survive the
`garbage=4` secure save … NO garbage level reclaims it". Measured: after `save_as` the
saved file lists 11 images and `fzImg1` is gone — mupdf's cleaning pass drops resource
entries no content stream references. **R6-01 held.** The real defect is a live document
that advertises an image it no longer draws, and an xref that lingers until save.

**Fixed** with `_stream_references_xobject`: match `/name` only when followed by a PDF
delimiter (§7.2.2 Tables 1-2) or end-of-stream.

### 10.2 CONFIRMED — `xref_set_key` fabricates a shadowing `/Resources`

`/Resources` is inheritable through `/Parent`. On a page that has none of its own,
PyMuPDF's `insert_image` registers the XObject in the *ancestor* dict, but the removal
code always pruned at `page.xref`. `xref_set_key` creates every missing link in the path,
so it wrote a direct `/Resources <</XObject<</fzImg0 null>>>>` onto the page — shadowing
the inherited dict.

**Reproduced** with a hand-built PDF (PyMuPDF always writes a page-level `/Resources`, so
the fixture has to be authored by hand): after delete, the page gained
`dict: <</XObject<</fzImg0 null>>>>` where `xref_get_key` had previously returned `null`,
and the real entry in the ancestor was never removed.

**Reviewer's predicted consequence — "the page renders broken" — did not occur:** the
inherited `/Font` no longer resolves through the shadow, but mupdf substitutes a fallback
font, so text still rendered and `get_text()` was unchanged. The corruption is real
(a spurious dict, an unpruned entry) but silent rather than catastrophic.

**Fixed** with `_resolve_xobject_resource_owner`: use the page's own `/Resources` when it
has one containing the name, else walk `/Parent` to the dict that actually holds it, else
prune nothing (never fabricate). When the owner is an inherited dict, sibling pages share
it, so the still-referenced scan widens to every page's content streams.

### 10.3 NOT ACTED ON — inline images (`BI … ID … EI`) in the tokenizer

`model/pdf_content_ops.py`'s tokenizer has no `BI/ID/EI` mode, so binary inline-image data
can lex as operators and a whole-stream re-serialize could corrupt it. Assessed and
deferred, with reasons:

- It is **pre-existing and not introduced here.** `_rewrite_native_image_matrix`
  (move/rotate, landed in `c099b28`) and the `native_image` delete branch already
  re-serialize the same streams through the same tokenizer.
- The app-image path cannot reach it directly: `insert_image` appends a *fresh* content
  stream per insert (measured: page `/Contents` grew `[6] → [6,10,12]`), which contains
  only `q cm /name Do Q`.
- The reviewer's reachability argument routes through `_redact_and_restore_textbox_region`
  consolidating page contents first, and even concedes it is unverified whether mupdf's
  redaction filter re-emits inline images as `BI…EI` at all.

Recorded in TODOS as a separate follow-up rather than smuggled into this PR. Fixing it
means teaching the tokenizer to treat `ID…EI` as one opaque token — a change to shared
content-stream machinery that deserves its own red-light suite covering move, rotate and
both delete branches.

### 10.4 Review process note

Two of the four planned reviewers (a third lens and the codex peer pass) died on the
session's agent limit — the failure mode CLAUDE.md §11 warns about. The two findings above
came from the two lenses that completed. The codex adversarial review the milestone plan
mandates for B1 is therefore **still outstanding**.

---

### 10.5 Second-lens findings (recovered from the workflow journal, 2026-07-10)

The contract-regression lens's output was **truncated in the notification and never read** when the
findings above were actioned. Recovered from `journal.jsonl`. Verdict: *sound-with-nits*. All
source-derived (that agent had no shell); **none executed**. Nothing below is fixed yet.

**MAJOR — unresolvable markers are now permanently undeletable "zombies".** §3's fail-safe returns
`False` *before* the marker deletion at `:901`, so a marker whose invocation cannot be resolved survives
forever. It stays hit-detectable (hit-testing is annot-payload based and never checks for an invocation),
still reports `supports_delete=True`, and no verb touches it — move and rotate already failed on this
population, and **delete was the last one that worked**. The user gets selection handles on an object
that silently refuses to die. Populations: (a) an external editor stripped the XObject but left our
hidden marker annot; (b) xref drift + two same-digest candidates within 2.0 pt; (c) payload `xref`
missing or `0`.

This is the cost of §3 that §3 did not price. Note (a) and (b) want *opposite* behavior: in (a) there
are no pixels left, so deleting the marker is exactly right; in (b) the pixels exist and deleting the
marker alone would orphan them. `_find_app_image_invocation` returns `None` for both, so a correct fix
must distinguish "no candidate at all" (clean up the marker) from "more than one candidate" (fail safe).

**MINOR — the `if not xref: return False` guard is strictly stronger than the resolver it gates.**
`_find_app_image_invocation` already handles `recorded_xref == 0` (empty `xref_candidates` → geometric
fallback, `:239-243`), and `_resolve_marker_image_invocation` would backfill `xref` + `image_digest`
(`:273-278`). The guard forecloses deletes that would otherwise succeed. Whether any shipped document
carries a version-1 image marker without `xref` is **unverified** (`_APP_OBJECT_VERSION` was never
bumped, so a pre-`c099b28` payload would pass the version gate).

**MINOR — `int(payload.get("xref", 0) or 0)` raises on a corrupt payload.** `"xref": "abc"` → `ValueError`,
which `delete_objects_atomic` re-raises after rollback (`:965-967`) and `PDFController.delete_object`
does not catch (`controller/pdf_controller.py:1692-1694`) — an unhandled exception in a Qt slot.

**MINOR — batch-delete amplification.** One unresolvable app-image in a multi-select rolls back the whole
batch (`:960-964`). The controller returns before `SnapshotCommand`/`show_page`, and the view has already
cleared the selection handles, so the user sees the handles vanish and *nothing else happen*: no toast,
no undo entry, four other objects silently not deleted. Atomicity is the documented design; the silent
failure is the contract change. `_show_edit_result_feedback` (`controller:1764-1771`) exists for text
edits and has no analogue here.

**MINOR — a failed delete swaps the live `fitz.Document` without render invalidation.** The rollback runs
`_restore_doc_from_snapshot`, which closes and reopens the document *even when zero mutations occurred*
(`pdf_model.py:2624-2635`), while the controller's `False` path skips `_invalidate_active_render_state()`.
Any cached `fitz.Page` now points at a closed document — the exact class in `PITFALLS.md:1329-1334`.
Pre-B1 this path was practically unreachable for app-images. Secondary: the restored doc has an empty
`doc.name`, so the next save silently degrades from incremental to full.

**NIT — marker-deletion failure still returns `True`.** `_delete_app_object_annots` swallows exceptions and
its count is ignored (`:899-902`), so a failed annot delete after a successful excision reports success.

**Explicitly verified as non-issues by that lens** (worth recording, since §4 argued one of them):
dropping `_register_mutation` is correct and the double-count reasoning holds; undo/redo is
snapshot-based and mechanism-agnostic; R6-01's `secure_save_required` latch is honoured at every
persistence boundary; the caller sweep found only `PDFController.delete_object` and
`view/object_selection.py`, both of which tolerate `False` without raising.

### 10.6 Fixes applied for §10.5 (2026-07-10)

Red-light first; all three new tests failed before the change and the `ValueError` reproduced verbatim
(`invalid literal for int() with base 10: 'abc'`). `test_image_objects_model.py` +
`test_pdf_object_ops_transactional.py`: **28 passed**.

**Zombie markers — FIXED.** §3's fail-safe collapsed two failures that want opposite handling. The delete
branch now asks `_app_image_invocation_candidates()` (a deliberate *superset* of what the resolver
accepts) when resolution returns `None`:

- **≥1 candidate → ambiguous.** The pixels exist; we cannot say which placement is ours. Return `False`,
  exactly as before. Deleting the marker alone would orphan visible content.
- **0 candidates → orphaned.** Nothing renders this image any more (an external editor stripped the
  XObject and left our hidden marker). Delete the marker and `_register_mutation`; return `True`.

This preserves the fail-safe where it was actually load-bearing and removes the undeletable object.
Pinned by `test_delete_orphaned_app_image_marker_cleans_up_the_marker`.

**`ValueError` on a corrupt payload — FIXED at the chokepoint, not per-site.** All four
`int(payload.get("xref", 0) or 0)` sites now route through `_marker_xref(payload)`, which returns `0` on
`TypeError`/`ValueError`. `0` is the correct degraded value: `_find_app_image_invocation` reads it as "no
recorded xref" and falls back to geometry + digest. Move and rotate become crash-safe with **no behavior
change** — their pre-existing `if not xref: return False` guard now sees `0` and takes the no-op it
already documented, instead of raising through `delete_objects_atomic`'s re-raise into an uncaught Qt
slot. Pinned by `test_delete_app_image_with_corrupt_xref_payload_does_not_raise`.

**Over-strong `if not xref` guard in delete — FIXED (delete only).** The guard was strictly stronger than
the resolver it gated, foreclosing deletes that geometry+digest would have resolved. Removed from the
delete branch. **Deliberately left in place in `move_object` and the rotate branch**: that guard predates
B1, no reported bug depends on it, and relaxing it is a behavior change to paths this PR does not
otherwise touch. Delete is therefore now slightly more permissive than move/rotate on legacy no-xref
markers, which is the right asymmetry — delete's job on an unresolvable object is cleanup. Pinned by
`test_delete_app_image_without_xref_in_payload_still_resolves`.

**Marker-deletion failure returning `True` — FIXED.** Both success paths now check
`_delete_app_object_annots`'s count and return `False` if the marker survived, so the snapshot rollback
restores the already-rewritten stream rather than leaving a phantom selectable object.

**Stale `fitz.Document` handle on a failed delete — FIXED, at the root cause.** `delete_objects_atomic`
unconditionally called `_restore_delete_transaction` on any `False`, and that closes and reopens
`model.doc` from the snapshot. Reproduced: after an ambiguous (zero-mutation) delete, `model.doc` was a
nameless `Document('pdf', <memory>)` and the previous handle was **closed** — any cached `fitz.Page`
would raise, the class documented at `PITFALLS.md:1329-1334`, and the empty `doc.name` silently degrades
the next save from incremental to full.

The rollback is now conditional on the document actually having been touched. Every mutating path bumps
`model.edit_count`, so comparing it against the transaction's opening value witnesses a mutation by the
failing request *or* by any earlier one in the batch. A pure no-op leaves the live handle untouched.
Belt-and-braces: `PDFController.delete_object` now also calls `_invalidate_active_render_state()` on the
`False` path, because a *genuine* partial-batch rollback still does reopen the document.

Pinned by `test_failed_delete_without_mutation_keeps_the_live_document_handle` (asserts
`model.doc is doc_before` and `doc.name` survives) and — guarding the optimisation against over-reach —
`test_failed_batch_delete_after_a_successful_one_still_rolls_back`, which drives a batch whose first
delete mutates the stream and whose second fails, and asserts the render digest and invocation count are
restored.

**Still open from §10.5** (recorded, not fixed):
- *Batch-delete amplification (UX).* One unresolvable app-image still rolls back a whole multi-select. The
  rollback itself is correct and is the documented atomicity design; what is missing is user feedback on
  the `False` path (`controller/pdf_controller.py`, both the batch and single branches), for which
  `_show_edit_result_feedback` is the existing precedent. The view has already cleared the selection
  handles by then, so today the user sees the handles vanish and nothing else happen. This is a view/UX
  change, not a correctness one, and it wants a deliberate message rather than a silent no-op.

## 11. Rollback

Single-file production diff; `git revert` restores the redaction path exactly. The bug
then returns to its known, documented state (collateral destruction on overlap-delete)
rather than to something new. The analogous move/rotate conversion (`c099b28`) has been
stable since it landed.

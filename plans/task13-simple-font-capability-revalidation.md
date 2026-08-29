# Task 13 — simple-font capability pull-revalidation

**Branch:** `task13/simple-font-capability-revalidation`, cut from
`task11/slice1-closure@0578866` (the P3-C merge).
**Kind:** correctness slice, sequenced BEFORE P3-D on purpose — seal the
known hole in `DocumentFontRegistry` before touching the
verification/interpretation pipeline, so P3-D evidence is not confounded.

## Goal

Close PITFALLS "Simple-font capabilities are served stale within a registry
generation" (P3-B review R1, pre-existing engine-path hole): the capability
cache key is `(generation, owner, name, xref)` and only Type0 hits carrying
a CID codec were evidence-digest revalidated. An in-place rewrite of a
simple font's `/Widths`, `/Encoding`, descriptor or program at the same xref
between two prepares sharing one registry served the OLD capability while
the page fingerprint was computed fresh — fresh-vs-fresh, so the apply-time
staleness gate could not catch it.

## Scope fence (user-set)

```
simple-font cache hit
→ re-derive / compare the evidence digest
→ unchanged: reuse the cached object
→ changed: rebuild the capability
```

NOT in this slice: P3-D DisplayList/TextPage reuse, `fitz.TOOLS` global
flag governance, dense-CJK growth admission, rollout.

## Design (as landed)

- `FontCapability.evidence_digest: str` — `field(default="", compare=False,
  repr=False)`; provenance, not identity (PITFALLS "Provenance fields on
  compared dataclasses silently break equality pins").
- `compute_simple_font_evidence_digest(doc, font_xref)` in `fonts.py` —
  same-document raw digest, enumerated (auditable against
  `_build_capability`): every key of the font dict; the indirect targets of
  `/Encoding` (its `/Differences`), `/Widths`, `/FirstChar`, `/LastChar`,
  `/FontDescriptor`; `FontDescriptor/Flags` (inline or indirect); raw bytes
  of `FontDescriptor/FontFile{,2,3}`. `font_xref <= 0` (inline resource
  dict) digests to a constant — the build is deterministic there.
- `compute_font_evidence_digest(doc, entry)` dispatches on the `get_fonts`
  entry's SUBTYPE: Type0 → existing `compute_cid_evidence_digest`,
  otherwise the simple-font digest. Keying on subtype rather than on
  `cached.cid is not None` also closes the same-class hole for a REJECTED
  Type0 (`cid is None`), which was served stale exactly like a simple font.
- `DocumentFontRegistry.page_capabilities`: digest computed on EVERY
  lookup, BEFORE the cache probe and BEFORE any rebuild; hit + mismatch →
  rebuild; the digest that was current before the build is stored, so a
  write racing the build is caught by the next lookup instead of being
  attested as current.
- `bump_generation` semantics unchanged; the engine still bumps only after
  a successful tiered commit.

## Cost

Base14 simple-font cache hit (`page_capabilities`, includes
`get_fonts(full=True)`): ~222 µs/lookup on the dev machine, fitz 1.27.1 —
noise against a warm preview render (hundreds of ms). Per-keystroke preview
uses its own scratch registry; nothing on that path changed shape.

## Red → Green

`test_scripts/test_text_commit_font_revalidation.py` — first draft 21
tests, 19 Red before implementation (2 are cache-reuse regression guards
that must hold on both sides); each review fix added its own Red tests
first (F1: 3, F2: 2 — one a guard, minor: 1). Final: 27 tests; Green 147
across the new file + `test_text_commit_fonts.py`,
`test_text_commit_font_widths.py`, `test_text_commit_cid_hex_tj.py`,
`test_text_commit_replay_reuse.py`; full single-process suite green.

## Review

Ultracode refute-first review (`wf_0e676ab2-88c`), three lenses (digest
closure completeness, cache/prepare semantics + cost, test validity + scope
fence); 7 raw findings, the 2 important ones independently re-verified with
executed probes, both CONFIRMED and fixed before commit:

- **F1 (important, digest closure):** the digest folded the font dict's
  raw `kind:value` text, but `_build_capability` consumes the
  MuPDF-RESOLVED `get_fonts` entry fields (ext, subtype, basefont,
  encoding). With `/BaseFont 8 0 R`, `/Subtype 9 0 R`, or an inline
  `/Encoding << /BaseEncoding 10 0 R >>`, rewriting the target changed the
  build but not the digest — probe: Helvetica→Wingdings served with the
  cached Helvetica face, Type1→Type3 served as simple, WinAnsi→MacExpert
  served as simple. Fix: `compute_font_evidence_digest` folds the four
  resolved entry fields ahead of the per-subtype object closure. Pinned by
  three `test_indirect_*_target_rewrite_rebuilds_the_capability` tests.
- **F2 (important, cost):** `capability(page, name)` went through
  `page_capabilities`, so every lookup digested EVERY font on the page;
  `prepare` resolves one resource per show → O(K·N) digests. Probe on
  `test-complexed-layout.pdf` p0 (98 fonts: 90 Type3 + 8 Type0): 1.45 s →
  10.3 s per `prepare_plan` (7.1×); 3-font page 3.6 → 10.6 ms. Fix:
  `capability()` locates the single matching entry (last wins, same answer
  as the dict) and resolves only it via the shared `_resolve`; Type3 gets a
  digest of exactly what its build reads (`FontDescriptor/Flags`). After:
  98-font page 340 ms (faster than the pre-slice 1.45 s — the old path
  built/looked up all 98 entries per call too), 3/5/7-font pages within
  noise (2.5 / 9.6 / 13.3 ms). Pinned by
  `test_single_resource_lookup_digests_only_that_resource` (exactly one
  digest per lookup on a 4-font page).
- **Minor, closed:** `FontFile*` was folded as raw bytes only; a `/Filter`
  rewrite on the stream dict changes what `extract_font` decodes from the
  same bytes. Now folds the stream dict too
  (`test_digest_covers_the_font_program_stream_dict`).
- **Minor, kept:** the two cache-reuse guards pass on baseline by design
  (they pin the no-thrash half of the contract, not the fix).
- **Refuted by probe:** pre-build digest ordering does not attest a racing
  write forever (next lookup rebuilds once, then stable); no thrash across
  18 corpus PDFs incl. inline dicts and the damaged file; Type0-with-codec
  path unchanged in value; no caller constructs `FontCapability` directly.
- **Out-of-fence correction (2026-08-27):** the initially recorded
  `inspect._update_font_dependencies` analogous gap is REFUTED by existing
  code plus end-to-end probes. `page_fingerprint()` independently folds the
  complete MuPDF-resolved `get_fonts(full=True)` entry before its canonical
  object-dependency closure. Green characterization pins now protect indirect
  `/BaseFont`, `/Subtype`, and inline `/BaseEncoding` target rewrites through
  KEEP-round-trip stability and `prepare -> mutation -> STALE_PLAN` with zero
  stream mutation. The genuine narrower follow-up was CLOSED 2026-08-27
  by `task13/cid-stream-evidence-attestation`: the Type0 digest now folds
  the builder-visible decoded bytes returned by `_stream_bytes()` for
  `FontFile2`, `CIDToGIDMap`, and `ToUnicode`. Six red pins cover direct and
  indirect `/Filter` target mutations with unchanged raw storage; an
  unchanged control plus exact read-count guard prevents cache thrash and
  per-hit amplification. Decoded-read+SHA probe p50 was 0.011 / 0.135 /
  3.617 ms respectively, so the implementation replaces raw hashing rather
  than hashing both forms.

## Decisions / dead ends

- Digest lives in `fonts.py`, not `inspect.py`: `inspect` imports `fonts`,
  so reusing `_update_font_dependencies` would be a cycle. The two contracts
  remain distinct: the registry digest is same-document pull-validation;
  the cross-document fingerprint already folds the complete resolved
  `get_fonts` entry plus its serialization-stable object closure.
- Raw program bytes are folded (not `/Length`): a same-length program
  rewrite must still invalidate — correctness slice, no shortcuts.

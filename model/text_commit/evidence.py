"""Task 13 P3-B: immutable replay evidence and session-scoped reuse.

One prepare reads the page's decoded content streams ONCE
(:func:`model.text_commit.inspect.capture_page_streams`), derives the
invalidation key from those fresh bytes, and resolves a
:class:`PageReplay` for them — either by replaying the snapshot, or by
reusing a retained :class:`ReplayEvidence` whose key digest-matches the
fresh read.  That fresh read + digest compare IS the lookup-time
pull-validation the P3-A census proved necessary (four mutation classes
change live content-stream bytes with no signal at all, and freed xref
numbers can be reused, so neither push hooks nor xref identity are
evidence of content).

Fail-closed contracts:

- A refused (over-budget) or malformed replay can NEVER be wrapped into
  :class:`ReplayEvidence` — construction raises (production analog of
  spike pin F4).  ``resolve_replay`` returns such replays with
  ``evidence=None`` so nothing retainable exists for them.
- ``resolve_replay`` re-compares the cached key against the snapshot key
  itself; a buggy cache handing back wrong-keyed evidence cannot cause a
  false hit.
- The cache is a SINGLE slot: storing replaces the previous entry, so the
  retained footprint is bounded by construction to one Shape A page
  (~0.78–1.19 MB on dense corpus pages per the P3-A record).

This module is pure (no ``fitz`` import): everything operates on already
read ``(xref, decoded_bytes)`` pairs, so the whole contract is testable
without a document.
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from model.text_commit.replay import PageReplay, replay_page_streams


@dataclass(frozen=True)
class ReplayEvidenceKey:
    """The P3-A §4 invalidation key.

    ``stream_digests`` (sha256 of each stream's DECODED bytes, in
    ``/Contents`` order) carries the correctness burden: xref numbers can
    be freed and reused, so identity alone is never evidence of content.
    Order is part of identity — graphics state carries across the page's
    stream sequence, so ``[a, b]`` and ``[b, a]`` are different pages.
    """

    page_xref: int
    stream_xrefs: tuple[int, ...]
    stream_digests: tuple[str, ...]


def compute_evidence_key(
    page_xref: int, streams: Sequence[tuple[int, bytes]]
) -> ReplayEvidenceKey:
    """Key for ``streams`` — ordered ``(xref, decoded_bytes)`` pairs."""
    return ReplayEvidenceKey(
        page_xref=page_xref,
        stream_xrefs=tuple(xref for xref, _ in streams),
        stream_digests=tuple(
            hashlib.sha256(data).hexdigest() for _, data in streams
        ),
    )


@dataclass(frozen=True)
class ReplayEvidence:
    """A retainable (key, production ``PageReplay``) pair — Shape A.

    The replay is retained VERBATIM (never a second data shape), so a
    validated hit is byte-equivalent to re-replaying the same input: the
    replay is a pure function of the ordered decoded stream bytes, and the
    key proves those bytes.  Construction refuses refused/malformed
    replays outright — there is no such thing as warm refusal evidence.
    """

    key: ReplayEvidenceKey
    replay: PageReplay

    def __post_init__(self) -> None:
        if self.replay.refusal_reason is not None:
            raise ValueError(
                "a refused replay must never become warm evidence: "
                f"{self.replay.refusal_reason}"
            )
        if self.replay.malformed:
            raise ValueError(
                "a malformed replay must never become warm evidence"
            )
        if self.replay.max_decoded_bytes is None:
            raise ValueError(
                "a diagnostic-unbounded replay must never become warm "
                "evidence"
            )
        if self.key.stream_xrefs != self.replay.stream_xrefs:
            raise ValueError(
                "evidence key does not match the replay's stream "
                "identity"
            )


@dataclass(frozen=True)
class PageStreamSnapshot:
    """One prepare's coherent stream read: ordered bytes plus their key.

    Built only by :func:`model.text_commit.inspect.capture_page_streams`
    (the ONE decoded read per prepare); the key is computed from exactly
    these bytes, which is what makes a later key match a pull-validation.
    Ephemeral by design — retaining decoded bytes would multiply the
    Shape A footprint by the page's decoded size for no benefit, since
    every lookup re-reads fresh bytes anyway.
    """

    page_xref: int
    streams: tuple[tuple[int, bytes], ...]
    key: ReplayEvidenceKey


@dataclass(frozen=True)
class ResolvedPageStreams:
    """The read+replay bundle one prepare consumes coherently.

    ``replay`` always corresponds to ``snapshot``'s bytes: either it was
    replayed from them here, or it came from evidence whose key equals the
    snapshot's key (sha256 over the same decoded bytes).  ``evidence`` is
    ``None`` exactly when the replay is refused or malformed.
    """

    snapshot: PageStreamSnapshot
    replay: PageReplay
    evidence: ReplayEvidence | None
    from_cache: bool


def resolve_replay(
    snapshot: PageStreamSnapshot, cached: ReplayEvidence | None
) -> ResolvedPageStreams:
    """Resolve a replay for ``snapshot`` — reuse ``cached`` only on proof.

    The key comparison happens HERE, against the snapshot's fresh-bytes
    key, regardless of how ``cached`` was looked up: the resolver never
    trusts a caller's cache discipline.  A mismatch (or no cache entry)
    replays the snapshot bytes under the DEFAULT budget — never the
    diagnostic-unbounded path.
    """
    if cached is not None and cached.key == snapshot.key:
        return ResolvedPageStreams(
            snapshot=snapshot,
            replay=cached.replay,
            evidence=cached,
            from_cache=True,
        )
    replay = replay_page_streams(list(snapshot.streams))
    evidence: ReplayEvidence | None = None
    if replay.refusal_reason is None and not replay.malformed:
        evidence = ReplayEvidence(key=snapshot.key, replay=replay)
    return ResolvedPageStreams(
        snapshot=snapshot,
        replay=replay,
        evidence=evidence,
        from_cache=False,
    )


class ReplayEvidenceCache:
    """Single-slot, session-scoped retention of one :class:`ReplayEvidence`.

    Owned by exactly one preview session (``PlanPreviewRenderer``); NOT
    thread-safe — same one-thread contract as its owner.  Bounded eviction
    is replacement: ``store`` drops the previous entry, so the live cache
    graph never exceeds one retained replay.  Counters exist for the
    acceptance harness and tests; they are not behavior.
    """

    __slots__ = ("_entry", "hits", "misses", "stores")

    def __init__(self) -> None:
        self._entry: ReplayEvidence | None = None
        self.hits = 0
        self.misses = 0
        self.stores = 0

    @property
    def entry_count(self) -> int:
        """0 or 1 — the whole point of the single slot."""
        return 0 if self._entry is None else 1

    def lookup(self, key: ReplayEvidenceKey) -> ReplayEvidence | None:
        """The entry when its key equals ``key``; counts a hit or miss."""
        entry = self._entry
        if entry is not None and entry.key == key:
            self.hits += 1
            return entry
        self.misses += 1
        return None

    def lookup_any(self) -> ReplayEvidence | None:
        """Introspection peek at the slot — no counter, no key proof.

        Never a substitute for :meth:`lookup`: reuse without a key match
        is exactly the false hit the contract forbids.
        """
        return self._entry

    def store(self, evidence: ReplayEvidence) -> None:
        """Replace the slot (the previous entry becomes unreachable)."""
        self._entry = evidence
        self.stores += 1

    def clear(self) -> None:
        """Drop the retained evidence (session close / doc replacement)."""
        self._entry = None

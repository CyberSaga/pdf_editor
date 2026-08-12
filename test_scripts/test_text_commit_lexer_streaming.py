"""Red-light tests for the P0-B streaming lexer (Task 12).

``lex_content_stream`` materializes the complete token list before replay
reads the first token: a measured ~72 MB decoded stream became ~54.7M
StreamToken objects (~174-202 B each with list+GC overhead) and ~10 GB of
RSS.  Replay consumes tokens in a single forward pass, drops trivia
immediately, and copies every offset the splice needs into ``ShowOp`` at
record time, so a plain generator preserves the exact-splice contract with
zero API change beyond iterator-ness.

Frozen acceptance (plan §6, 2026-08-12):

* ``lex_content_stream(...)`` returns an ITERATOR, not a list/Sequence.
* Peak RSS is measured in an ISOLATED SUBPROCESS (parent collects the
  result) — never in-process (allocator high-water pollution from earlier
  tests) and never via gc object counts (blind to non-GC allocations).
* The replay chokepoint must also stay bounded: a lexer that streams but a
  replay that secretly materializes would pass a lexer-only test.

Semantic preservation (ShowOp fields, splice offsets, digests, gap-free
tiling) is NOT re-pinned here: ``test_text_commit_replay.py``,
``test_text_commit_lexer.py`` (wrapped in ``list()`` at green), and the
Task 11 tier suites already pin those against source bytes on small
fixtures and re-run at green.

All fixtures are synthetic (generated vector-path operators).
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.pdf_lexer import lex_content_stream  # noqa: E402

_CHILD = Path(__file__).with_name("_streaming_memory_child.py")
_MIB = 8
# The list lexer peaks near ~1.1 GB on an 8 MiB stream (~6.2M tokens at
# ~180 B each); a streaming walk needs little more than the stream itself.
# 400 MB sits a safe 2.5x below red and ~8x above green.
_PEAK_CEILING_BYTES = 400 * 1024 * 1024


def _run_child(mode: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(_CHILD), "--mode", mode, "--mib", str(_MIB)],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(ROOT),
        check=False,
    )
    assert proc.returncode == 0, f"child failed:\n{proc.stderr[-2000:]}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_lex_returns_iterator_not_sequence():
    tokens = lex_content_stream(b"BT /F1 12 Tf (x) Tj ET")
    assert isinstance(tokens, Iterator)
    assert not isinstance(tokens, Sequence)


def test_raw_token_walk_peak_rss_bounded():
    result = _run_child("lex")
    # The walk really covered the stream (guards a trivially-lying child).
    assert result["token_count"] > 5_000_000
    assert result["last_end"] == result["stream_bytes"]
    peak = result["peak_rss"]
    assert peak < _PEAK_CEILING_BYTES, f"peak RSS {peak / 1048576:.0f} MB"


def test_replay_consumes_stream_without_materializing():
    result = _run_child("replay")
    assert result["shows"] == 0
    assert result["malformed"] is False
    # The walk must really have run: max_decoded_bytes=None disables the
    # guard, so a refusal here means None was coerced to the default budget
    # — and the low peak RSS below would be measuring a refused no-op.
    assert result["refusal_reason"] is None
    peak = result["peak_rss"]
    assert peak < _PEAK_CEILING_BYTES, f"peak RSS {peak / 1048576:.0f} MB"

"""Subprocess worker for the P0-B streaming-lexer memory tests.

Runs one full token walk (``--mode lex``) or one replay
(``--mode replay``) over a synthetic vector-path stream of ``--mib`` MiB,
then reports its own lifetime peak RSS as JSON on stdout.

Isolation is the point (Task 12 plan §6, frozen 2026-08-12): in-process
RSS deltas are polluted by the allocator's high-water behaviour from
earlier tests, and gc object counts miss non-GC allocations entirely.  A
fresh process's lifetime peak is attributable to exactly one walk.

Not a pytest module (no ``test_`` prefix): invoked by
``test_text_commit_lexer_streaming.py`` via ``sys.executable``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_PATH_CHUNK = b"10 20 m 30 40 l 50 60 70 80 90 100 c S\n"


def _peak_rss_bytes() -> int:
    """Lifetime peak resident set of THIS process, in bytes."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        fn = k32.K32GetProcessMemoryInfo
        fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
        fn.restype = wintypes.BOOL
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        if not fn(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            raise OSError(f"K32GetProcessMemoryInfo failed: {ctypes.get_last_error()}")
        return int(pmc.PeakWorkingSetSize)

    import resource

    ru_maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB, macOS reports bytes.
    return int(ru_maxrss) if sys.platform == "darwin" else int(ru_maxrss) * 1024


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("lex", "replay"), required=True)
    parser.add_argument("--mib", type=int, required=True)
    args = parser.parse_args()

    stream = _PATH_CHUNK * (args.mib * 1024 * 1024 // len(_PATH_CHUNK) + 1)

    from model.text_commit.pdf_lexer import lex_content_stream
    from model.text_commit.replay import replay_page_streams

    result: dict[str, object]
    if args.mode == "lex":
        count = 0
        last_end = 0
        for token in lex_content_stream(stream):
            count += 1
            last_end = token.end
        result = {"token_count": count, "last_end": last_end}
    else:
        replay = replay_page_streams([(1, stream)], max_decoded_bytes=None)
        # refusal_reason must be reported: a None-coerced-to-default
        # regression would refuse this over-default stream before lexing,
        # and the tiny resulting RSS would masquerade as a streaming pass.
        result = {
            "shows": len(replay.shows),
            "malformed": replay.malformed,
            "refusal_reason": replay.refusal_reason,
        }

    result["stream_bytes"] = len(stream)
    result["peak_rss"] = _peak_rss_bytes()
    print(json.dumps(result))


if __name__ == "__main__":
    main()

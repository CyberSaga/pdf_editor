"""Capability-driven text commit engine (V2).

Model-only package implementing the tiered Acrobat-stable commit path:
lossless lexing/splicing of content streams, text-state replay, per-xref
font capability, planning, patching, verification, and orchestration.
See plans/2026-07-18-acrobat-stable-text-commit-engine-v2.md.
"""
from __future__ import annotations

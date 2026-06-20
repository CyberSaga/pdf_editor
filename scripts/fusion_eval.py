"""Small deterministic scoring primitives for direct-versus-Fusion evaluations."""

from __future__ import annotations

import re
from dataclasses import dataclass


URL_PATTERN = re.compile(r"https?://[^\s)>\]}]+")


@dataclass(frozen=True)
class EvalCase:
    required_terms: tuple[str, ...]
    forbidden_terms: tuple[str, ...]
    require_links: bool = False


@dataclass(frozen=True)
class EvalScore:
    required_coverage: float
    forbidden_hits: tuple[str, ...]
    valid_links: tuple[str, ...]
    total: float


def score_answer(case: EvalCase, answer: str) -> EvalScore:
    lowered = answer.lower()
    matched = sum(1 for term in case.required_terms if term.lower() in lowered)
    coverage = matched / len(case.required_terms) if case.required_terms else 1.0
    forbidden = tuple(term for term in case.forbidden_terms if term.lower() in lowered)
    links = tuple(dict.fromkeys(URL_PATTERN.findall(answer)))
    missing_link_penalty = 0.25 if case.require_links and not links else 0.0
    total = max(0.0, min(1.0, coverage - 0.5 * len(forbidden) - missing_link_penalty))
    return EvalScore(coverage, forbidden, links, total)

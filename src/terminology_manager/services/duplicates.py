from __future__ import annotations

import difflib
from dataclasses import dataclass


@dataclass(slots=True)
class DuplicateSignal:
    reason: str
    value: str
    score: float


def normalize(text: str) -> str:
    return " ".join(text.casefold().strip().split())


def fuzzy_score(a: str, b: str) -> float:
    return difflib.SequenceMatcher(a=normalize(a), b=normalize(b)).ratio()


def find_fuzzy_matches(value: str, candidates: list[str], threshold: float = 0.9) -> list[DuplicateSignal]:
    hits: list[DuplicateSignal] = []
    n_value = normalize(value)
    if not n_value:
        return hits
    for candidate in candidates:
        score = fuzzy_score(n_value, candidate)
        if score >= threshold:
            hits.append(DuplicateSignal(reason="fuzzy", value=candidate, score=score))
    return sorted(hits, key=lambda s: s.score, reverse=True)

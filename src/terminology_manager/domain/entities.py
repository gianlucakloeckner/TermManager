from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Language = Literal["de", "en"]


@dataclass(slots=True)
class SearchResult:
    term_id: int
    de: str
    en: str
    chapter_de: str | None
    chapter_en: str | None
    chapter_visible: bool
    rank: float
    snippet_de: str
    snippet_en: str
    snippet_synonyms: str


@dataclass(slots=True)
class VersionRecord:
    id: int
    entity_type: str
    entity_id: int
    action: str
    changed_at: datetime
    before_json: str | None
    after_json: str | None

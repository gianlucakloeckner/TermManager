from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from terminology_manager.domain.entities import SearchResult, VersionRecord
from terminology_manager.persistence.database import session_scope
from terminology_manager.persistence.models import Chapter
from terminology_manager.persistence.repositories import (
    ChapterRepository,
    TermRepository,
    TermUpsert,
    VersionRepository,
    serialize_term,
)
from terminology_manager.services.duplicates import DuplicateSignal, find_fuzzy_matches, normalize
from terminology_manager.services.import_export import export_terms, import_terms


@dataclass(slots=True)
class DuplicateReport:
    exact_term_ids: list[int]
    exact_synonym_term_ids: list[int]
    fuzzy_hits: list[DuplicateSignal]


class TerminologyService:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory = session_factory

    def list_terms(self) -> list[dict[str, Any]]:
        with session_scope(self.session_factory) as session:
            terms = TermRepository(session).list_all()
            return [serialize_term(t) for t in terms]

    def get_term(self, term_id: int) -> dict[str, Any] | None:
        with session_scope(self.session_factory) as session:
            term = TermRepository(session).get(term_id)
            return None if term is None else serialize_term(term)

    def save_term(
        self,
        *,
        term_id: int | None,
        de: str,
        en: str,
        de_desc: str,
        en_desc: str,
        image: bytes | None,
        synonyms: list[dict[str, Any]],
        annotations: list[dict[str, Any]],
        chapter_ids: list[int],
    ) -> int:
        with session_scope(self.session_factory) as session:
            term_repo = TermRepository(session)
            version_repo = VersionRepository(session)
            payload = TermUpsert(de=de, en=en, de_desc=de_desc, en_desc=en_desc, image=image)

            if term_id is None:
                term = term_repo.create(payload)
                term_repo.replace_synonyms(term.id, synonyms)
                term_repo.replace_annotations(term.id, annotations)
                term_repo.assign_chapters(term.id, chapter_ids)
                term_after = term_repo.get(term.id)
                if term_after is not None:
                    version_repo.record(
                        entity_type="term",
                        entity_id=term.id,
                        action="create",
                        before=None,
                        after=serialize_term(term_after),
                    )
                return term.id

            before_term = term_repo.get(term_id)
            if before_term is None:
                raise ValueError("term not found")
            before_payload = serialize_term(before_term)

            term_repo.update(term_id, payload)
            term_repo.replace_synonyms(term_id, synonyms)
            term_repo.replace_annotations(term_id, annotations)
            term_repo.assign_chapters(term_id, chapter_ids)

            after_term = term_repo.get(term_id)
            if after_term is not None:
                version_repo.record(
                    entity_type="term",
                    entity_id=term_id,
                    action="update",
                    before=before_payload,
                    after=serialize_term(after_term),
                )
            return term_id

    def delete_term(self, term_id: int) -> None:
        with session_scope(self.session_factory) as session:
            term_repo = TermRepository(session)
            version_repo = VersionRepository(session)
            term = term_repo.get(term_id)
            if term is None:
                return
            before_payload = serialize_term(term)
            term_repo.delete(term_id)
            version_repo.record(
                entity_type="term",
                entity_id=term_id,
                action="delete",
                before=before_payload,
                after=None,
            )

    def search(self, query: str, include_hidden_chapters: bool = False) -> list[SearchResult]:
        with session_scope(self.session_factory) as session:
            return TermRepository(session).search_fts(
                query=query, include_hidden_chapters=include_hidden_chapters
            )

    def list_chapters(self) -> list[Chapter]:
        with session_scope(self.session_factory) as session:
            return ChapterRepository(session).list_all()

    def save_chapter(
        self,
        chapter_id: int | None,
        name_de: str,
        name_en: str,
        visible: bool,
        parent_id: int | None = None,
    ) -> int:
        with session_scope(self.session_factory) as session:
            chapter_repo = ChapterRepository(session)
            version_repo = VersionRepository(session)
            before: dict[str, Any] | None = None
            action = "create"
            if chapter_id is not None:
                chapter = chapter_repo.get(chapter_id)
                if chapter is None:
                    raise ValueError("chapter not found")
                before = {
                    "id": chapter.id,
                    "name_de": chapter.name_de,
                    "name_en": chapter.name_en,
                    "visible": chapter.visible,
                    "parent_id": chapter.parent_id,
                }
                action = "update"

            chapter = chapter_repo.upsert(
                chapter_id, name_de, name_en, visible, parent_id=parent_id
            )
            version_repo.record(
                entity_type="chapter",
                entity_id=chapter.id,
                action=action,
                before=before,
                after={
                    "id": chapter.id,
                    "name_de": chapter.name_de,
                    "name_en": chapter.name_en,
                    "visible": chapter.visible,
                    "parent_id": chapter.parent_id,
                },
            )
            return chapter.id

    def delete_chapter(self, chapter_id: int) -> None:
        with session_scope(self.session_factory) as session:
            chapter_repo = ChapterRepository(session)
            version_repo = VersionRepository(session)
            chapter = chapter_repo.get(chapter_id)
            if chapter is None:
                return
            before = {
                "id": chapter.id,
                "name_de": chapter.name_de,
                "name_en": chapter.name_en,
                "visible": chapter.visible,
                "parent_id": chapter.parent_id,
            }
            chapter_repo.delete(chapter_id)
            version_repo.record(
                entity_type="chapter",
                entity_id=chapter_id,
                action="delete",
                before=before,
                after=None,
            )

    def set_logo(self, logo_bytes: bytes | None) -> None:
        with session_scope(self.session_factory) as session:
            TermRepository(session).set_logo(logo_bytes)

    def get_logo(self) -> bytes | None:
        with session_scope(self.session_factory) as session:
            return TermRepository(session).get_logo()

    def detect_duplicates(self, de: str, en: str, synonyms: list[str]) -> DuplicateReport:
        with session_scope(self.session_factory) as session:
            candidates = TermRepository(session).duplicate_candidates(de, en, synonyms)

        exact_term_ids: list[int] = []
        exact_syn_term_ids: list[int] = []
        candidate_names: list[str] = []
        for candidate in candidates:
            candidate_names.extend([candidate.de, candidate.en])
            if normalize(candidate.de) == normalize(de) or normalize(candidate.en) == normalize(en):
                exact_term_ids.append(candidate.id)
            syns = [normalize(s.synonym) for s in candidate.synonyms]
            if any(normalize(s) in syns for s in synonyms if s.strip()):
                exact_syn_term_ids.append(candidate.id)

        fuzzy_hits = find_fuzzy_matches(de, candidate_names) + find_fuzzy_matches(
            en, candidate_names
        )
        return DuplicateReport(
            exact_term_ids=sorted(set(exact_term_ids)),
            exact_synonym_term_ids=sorted(set(exact_syn_term_ids)),
            fuzzy_hits=fuzzy_hits,
        )

    def export_all(self, target: Path) -> None:
        rows = self.list_terms()
        export_terms(rows, target)

    def import_file(self, source: Path) -> int:
        rows = import_terms(source)
        imported = 0
        for row in rows:
            self.save_term(
                term_id=None,
                de=row["de"],
                en=row["en"],
                de_desc=row.get("de_desc", ""),
                en_desc=row.get("en_desc", ""),
                image=None,
                synonyms=row.get("synonyms", []),
                annotations=row.get("annotations", []),
                chapter_ids=row.get("chapter_ids", []),
            )
            imported += 1
        return imported

    def history_for_term(self, term_id: int) -> list[VersionRecord]:
        with session_scope(self.session_factory) as session:
            return VersionRepository(session).list_for_entity("term", term_id)

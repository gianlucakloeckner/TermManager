from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select, text
from sqlalchemy.orm import Session, joinedload

from terminology_manager.domain.entities import SearchResult, VersionRecord
from terminology_manager.persistence.models import (
    Chapter,
    Setting,
    Synonym,
    Term,
    TermChapter,
    TermRecommendation,
    VersionEvent,
)


@dataclass(slots=True)
class TermUpsert:
    de: str
    en: str
    de_desc: str
    en_desc: str
    annotations: str
    image: bytes | None


class VersionRepository:
    def __init__(self, session: Session):
        self.session = session

    def record(
        self,
        *,
        entity_type: str,
        entity_id: int,
        action: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        self.session.add(
            VersionEvent(
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                before_json=json.dumps(before, ensure_ascii=False) if before is not None else None,
                after_json=json.dumps(after, ensure_ascii=False) if after is not None else None,
            )
        )

    def list_for_entity(self, entity_type: str, entity_id: int) -> list[VersionRecord]:
        stmt: Select[tuple[VersionEvent]] = (
            select(VersionEvent)
            .where(VersionEvent.entity_type == entity_type, VersionEvent.entity_id == entity_id)
            .order_by(VersionEvent.changed_at.desc())
        )
        rows = self.session.scalars(stmt).all()
        return [
            VersionRecord(
                id=r.id,
                entity_type=r.entity_type,
                entity_id=r.entity_id,
                action=r.action,
                changed_at=r.changed_at,
                before_json=r.before_json,
                after_json=r.after_json,
            )
            for r in rows
        ]


class ChapterRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[Chapter]:
        return list(self.session.scalars(select(Chapter).order_by(Chapter.name_de.asc())).all())

    def get(self, chapter_id: int) -> Chapter | None:
        return self.session.get(Chapter, chapter_id)

    def upsert(
        self,
        chapter_id: int | None,
        name_de: str,
        name_en: str,
        visible: bool,
        parent_id: int | None = None,
    ) -> Chapter:
        if chapter_id is not None and parent_id == chapter_id:
            raise ValueError("chapter cannot be parent of itself")
        if chapter_id is None:
            chapter = Chapter(
                name_de=name_de.strip(),
                name_en=name_en.strip(),
                visible=visible,
                parent_id=parent_id,
            )
            self.session.add(chapter)
            self.session.flush()
            return chapter
        chapter_opt = self.session.get(Chapter, chapter_id)
        if chapter_opt is None:
            raise ValueError("chapter not found")
        chapter = chapter_opt
        chapter.name_de = name_de.strip()
        chapter.name_en = name_en.strip()
        chapter.visible = visible
        chapter.parent_id = parent_id
        self.session.flush()
        return chapter

    def delete(self, chapter_id: int) -> None:
        chapter = self.session.get(Chapter, chapter_id)
        if chapter is not None:
            self.session.delete(chapter)

    def descendant_ids(self, chapter_id: int) -> list[int]:
        chapters = self.list_all()
        by_parent: dict[int | None, list[Chapter]] = {}
        for chapter in chapters:
            by_parent.setdefault(chapter.parent_id, []).append(chapter)

        out: list[int] = []

        def walk(parent_id: int) -> None:
            for child in by_parent.get(parent_id, []):
                out.append(child.id)
                walk(child.id)

        walk(chapter_id)
        return out


class TermRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[Term]:
        stmt: Select[tuple[Term]] = (
            select(Term)
            .options(joinedload(Term.synonyms), joinedload(Term.chapters))
            .order_by(Term.de.asc())
        )
        return list(self.session.scalars(stmt).unique().all())

    def get(self, term_id: int) -> Term | None:
        stmt: Select[tuple[Term]] = (
            select(Term)
            .where(Term.id == term_id)
            .options(joinedload(Term.synonyms), joinedload(Term.chapters))
        )
        return self.session.scalars(stmt).unique().one_or_none()

    def create(self, payload: TermUpsert) -> Term:
        term = Term(
            de=payload.de.strip(),
            en=payload.en.strip(),
            de_desc=payload.de_desc.strip(),
            en_desc=payload.en_desc.strip(),
            annotations=payload.annotations.strip(),
            image=payload.image,
        )
        self.session.add(term)
        self.session.flush()
        return term

    def update(self, term_id: int, payload: TermUpsert) -> Term:
        term = self.session.get(Term, term_id)
        if term is None:
            raise ValueError("term not found")
        term.de = payload.de.strip()
        term.en = payload.en.strip()
        term.de_desc = payload.de_desc.strip()
        term.en_desc = payload.en_desc.strip()
        term.annotations = payload.annotations.strip()
        term.image = payload.image
        self.session.flush()
        return term

    def delete(self, term_id: int) -> None:
        term = self.session.get(Term, term_id)
        if term is not None:
            self.session.delete(term)

    def delete_many(self, term_ids: list[int]) -> None:
        for term_id in sorted(set(term_ids)):
            term = self.session.get(Term, term_id)
            if term is not None:
                self.session.delete(term)
        self.session.flush()

    def term_ids_for_chapters(self, chapter_ids: list[int]) -> list[int]:
        if not chapter_ids:
            return []
        rows = self.session.execute(
            select(TermChapter.term_id).where(TermChapter.chapter_id.in_(chapter_ids))
        ).all()
        return sorted({int(term_id) for (term_id,) in rows})

    def replace_synonyms(self, term_id: int, rows: list[dict[str, Any]]) -> None:
        self.session.query(Synonym).where(Synonym.term_id == term_id).delete(
            synchronize_session=False
        )
        for row in rows:
            synonym = Synonym(
                term_id=term_id,
                lang=str(row["lang"]).strip(),
                synonym=str(row["synonym"]).strip(),
                allowed=bool(row.get("allowed", True)),
            )
            self.session.add(synonym)
        self.session.flush()

    def assign_chapters(self, term_id: int, chapter_ids: list[int]) -> None:
        self.session.query(TermChapter).where(TermChapter.term_id == term_id).delete(
            synchronize_session=False
        )
        for chapter_id in sorted(set(chapter_ids)):
            self.session.add(TermChapter(term_id=term_id, chapter_id=chapter_id))
        self.session.flush()

    def _set_setting_bytes(self, key: str, value: bytes | None) -> None:
        setting = self.session.get(Setting, key)
        if setting is None:
            setting = Setting(key=key, value=value)
            self.session.add(setting)
        else:
            setting.value = value
        self.session.flush()

    def _get_setting_bytes(self, key: str) -> bytes | None:
        setting = self.session.get(Setting, key)
        return None if setting is None else setting.value

    def set_logo(self, logo_bytes: bytes | None) -> None:
        self._set_setting_bytes("logo", logo_bytes)

    def get_logo(self) -> bytes | None:
        return self._get_setting_bytes("logo")

    def set_edit_pin(self, pin: str) -> None:
        self._set_setting_bytes("edit_pin", pin.encode("utf-8"))

    def get_edit_pin(self) -> str | None:
        raw = self._get_setting_bytes("edit_pin")
        if raw is None:
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def _build_fts_query(self, query: str) -> str:
        tokens = re.findall(r"[0-9A-Za-zÀ-ÿ]+", query.strip())
        if not tokens:
            return query.strip()
        # Prefix search for each token so "con" matches "conveyor".
        return " ".join(f"{token}*" for token in tokens)

    def search_fts(self, query: str, include_hidden_chapters: bool = True) -> list[SearchResult]:
        if not query.strip():
            return []
        fts_query = self._build_fts_query(query)
        sql = text("""
            SELECT
                t.id AS term_id,
                t.de AS de,
                t.en AS en,
                c.name_de AS chapter_de,
                c.name_en AS chapter_en,
                COALESCE(c.visible, 1) AS chapter_visible,
                bm25(term_fts, 1.5, 1.5, 0.9, 0.9, 1.1) AS rank,
                highlight(term_fts, 1, '<mark>', '</mark>') AS snippet_de,
                highlight(term_fts, 2, '<mark>', '</mark>') AS snippet_en,
                snippet(term_fts, 5, '<mark>', '</mark>', '...', 8) AS snippet_synonyms
            FROM term_fts
            JOIN terms t ON t.id = term_fts.term_id
            LEFT JOIN term_chapters tc ON tc.term_id = t.id
            LEFT JOIN chapters c ON c.id = tc.chapter_id
            WHERE term_fts MATCH :q
              AND (:include_hidden = 1 OR COALESCE(c.visible, 1) = 1)
            ORDER BY rank ASC, t.de ASC
            LIMIT 300;
            """)
        rows = (
            self.session.execute(
                sql,
                {"q": fts_query, "include_hidden": 1 if include_hidden_chapters else 0},
            )
            .mappings()
            .all()
        )
        seen: set[tuple[int, str | None]] = set()
        out: list[SearchResult] = []
        for row in rows:
            key = (int(row["term_id"]), row["chapter_de"])
            if key in seen:
                continue
            seen.add(key)
            out.append(
                SearchResult(
                    term_id=int(row["term_id"]),
                    de=str(row["de"]),
                    en=str(row["en"]),
                    chapter_de=row["chapter_de"],
                    chapter_en=row["chapter_en"],
                    chapter_visible=bool(row["chapter_visible"]),
                    rank=float(row["rank"]),
                    snippet_de=str(row["snippet_de"] or ""),
                    snippet_en=str(row["snippet_en"] or ""),
                    snippet_synonyms=str(row["snippet_synonyms"] or ""),
                )
            )
        return out

    def duplicate_candidates(self, de: str, en: str, synonyms: list[str]) -> list[Term]:
        normalized_syns = [s.strip().lower() for s in synonyms if s.strip()]
        stmt: Select[tuple[Term]] = (
            select(Term)
            .options(joinedload(Term.synonyms))
            .where((Term.de.ilike(de.strip())) | (Term.en.ilike(en.strip())))
        )
        terms = list(self.session.scalars(stmt).unique().all())

        if normalized_syns:
            syn_stmt: Select[tuple[Term]] = (
                select(Term)
                .join(Synonym, Synonym.term_id == Term.id)
                .where(Synonym.synonym.in_(normalized_syns))
                .options(joinedload(Term.synonyms))
            )
            terms.extend(list(self.session.scalars(syn_stmt).unique().all()))

        uniq: dict[int, Term] = {term.id: term for term in terms}
        return list(uniq.values())


class TermRecommendationRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, de: str, en: str) -> TermRecommendation:
        rec = TermRecommendation(de=de.strip(), en=en.strip())
        self.session.add(rec)
        self.session.flush()
        return rec

    def list_pending(self) -> list[TermRecommendation]:
        return list(
            self.session.scalars(
                select(TermRecommendation)
                .where(TermRecommendation.status == "pending")
                .order_by(TermRecommendation.created_at.asc())
            ).all()
        )

    def count_pending(self) -> int:
        result = self.session.scalar(
            select(func.count(TermRecommendation.id)).where(TermRecommendation.status == "pending")
        )
        return result or 0

    def accept(self, rec_id: int) -> TermRecommendation:
        rec = self.session.get(TermRecommendation, rec_id)
        if rec is None:
            raise ValueError("recommendation not found")
        rec.status = "accepted"
        rec.reviewed_at = datetime.utcnow()
        self.session.flush()
        return rec

    def deny(self, rec_id: int) -> TermRecommendation:
        rec = self.session.get(TermRecommendation, rec_id)
        if rec is None:
            raise ValueError("recommendation not found")
        rec.status = "denied"
        rec.reviewed_at = datetime.utcnow()
        self.session.flush()
        return rec


def serialize_term(term: Term) -> dict[str, Any]:
    return {
        "id": term.id,
        "de": term.de,
        "en": term.en,
        "de_desc": term.de_desc,
        "en_desc": term.en_desc,
        "annotations": term.annotations,
        "image": bool(term.image),
        "image_b64": base64.b64encode(term.image).decode("ascii") if term.image else "",
        "updated_at": (
            term.updated_at.isoformat() if isinstance(term.updated_at, datetime) else None
        ),
        "synonyms": [
            {"id": s.id, "lang": s.lang, "synonym": s.synonym, "allowed": s.allowed}
            for s in term.synonyms
        ],
        "chapter_ids": [tc.chapter_id for tc in term.chapters],
    }

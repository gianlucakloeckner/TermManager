from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Term(Base):
    __tablename__ = "terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    de: Mapped[str] = mapped_column(String(255), nullable=False)
    en: Mapped[str] = mapped_column(String(255), nullable=False)
    de_desc: Mapped[str] = mapped_column(Text, default="", nullable=False)
    en_desc: Mapped[str] = mapped_column(Text, default="", nullable=False)
    annotations: Mapped[str] = mapped_column(Text, default="", nullable=False)
    image: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())

    synonyms: Mapped[list[Synonym]] = relationship(
        back_populates="term", cascade="all, delete-orphan"
    )
    chapters: Mapped[list[TermChapter]] = relationship(
        back_populates="term", cascade="all, delete-orphan"
    )


class Synonym(Base):
    __tablename__ = "synonyms"
    __table_args__ = (UniqueConstraint("term_id", "lang", "synonym", name="uq_synonym_term_lang"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.id", ondelete="CASCADE"), nullable=False)
    lang: Mapped[str] = mapped_column(String(2), nullable=False)
    synonym: Mapped[str] = mapped_column(String(255), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    term: Mapped[Term] = relationship(back_populates="synonyms")


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name_de: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True
    )

    terms: Mapped[list[TermChapter]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan"
    )
    parent: Mapped[Chapter | None] = relationship(
        "Chapter", remote_side="Chapter.id", back_populates="children"
    )
    children: Mapped[list[Chapter]] = relationship("Chapter", back_populates="parent")


class TermChapter(Base):
    __tablename__ = "term_chapters"
    __table_args__ = (UniqueConstraint("term_id", "chapter_id", name="uq_term_chapter"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.id", ondelete="CASCADE"), nullable=False)
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )

    term: Mapped[Term] = relationship(back_populates="chapters")
    chapter: Mapped[Chapter] = relationship(back_populates="terms")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


class VersionEvent(Base):
    __tablename__ = "version_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class TermRecommendation(Base):
    __tablename__ = "term_recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    de: Mapped[str] = mapped_column(String(255), nullable=False)
    en: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

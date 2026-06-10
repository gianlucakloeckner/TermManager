from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from terminology_manager.persistence.models import Base


def create_sqlite_engine(database_url: str) -> Engine:
    engine = create_engine(database_url, future=True)

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()

    return engine


def initialize_database(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        term_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(terms)")).fetchall()]
        if "annotations" not in term_cols:
            conn.execute(text("ALTER TABLE terms ADD COLUMN annotations TEXT NOT NULL DEFAULT ''"))

        chapter_cols = [
            row[1] for row in conn.execute(text("PRAGMA table_info(chapters)")).fetchall()
        ]
        if "parent_id" not in chapter_cols:
            conn.execute(text("""
                    ALTER TABLE chapters
                    ADD COLUMN parent_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL
                    """))

        conn.execute(text("DROP TABLE IF EXISTS annotations"))

        conn.execute(text("""
                CREATE VIRTUAL TABLE IF NOT EXISTS term_fts USING fts5(
                    term_id UNINDEXED,
                    de,
                    en,
                    de_desc,
                    en_desc,
                    synonyms,
                    tokenize = 'unicode61 remove_diacritics 2'
                );
                """))
        conn.execute(text("DELETE FROM term_fts;"))
        conn.execute(text("""
                INSERT INTO term_fts(term_id, de, en, de_desc, en_desc, synonyms)
                SELECT t.id, t.de, t.en, t.de_desc, t.en_desc,
                       COALESCE((SELECT group_concat(s.synonym, ' ') FROM synonyms s WHERE s.term_id=t.id), '')
                FROM terms t;
                """))

        conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS terms_ai AFTER INSERT ON terms BEGIN
                    INSERT INTO term_fts(term_id, de, en, de_desc, en_desc, synonyms)
                    VALUES (
                        NEW.id,
                        NEW.de,
                        NEW.en,
                        NEW.de_desc,
                        NEW.en_desc,
                        COALESCE((SELECT group_concat(s.synonym, ' ') FROM synonyms s WHERE s.term_id=NEW.id), '')
                    );
                END;
                """))
        conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS terms_au AFTER UPDATE ON terms BEGIN
                    UPDATE term_fts
                    SET de=NEW.de,
                        en=NEW.en,
                        de_desc=NEW.de_desc,
                        en_desc=NEW.en_desc,
                        synonyms=COALESCE((SELECT group_concat(s.synonym, ' ') FROM synonyms s WHERE s.term_id=NEW.id), '')
                    WHERE term_id=NEW.id;
                END;
                """))
        conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS terms_ad AFTER DELETE ON terms BEGIN
                    DELETE FROM term_fts WHERE term_id=OLD.id;
                END;
                """))

        conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS synonyms_ai AFTER INSERT ON synonyms BEGIN
                    UPDATE term_fts
                    SET synonyms=COALESCE((SELECT group_concat(s.synonym, ' ') FROM synonyms s WHERE s.term_id=NEW.term_id), '')
                    WHERE term_id=NEW.term_id;
                END;
                """))
        conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS synonyms_au AFTER UPDATE ON synonyms BEGIN
                    UPDATE term_fts
                    SET synonyms=COALESCE((SELECT group_concat(s.synonym, ' ') FROM synonyms s WHERE s.term_id=NEW.term_id), '')
                    WHERE term_id=NEW.term_id;
                END;
                """))
        conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS synonyms_ad AFTER DELETE ON synonyms BEGIN
                    UPDATE term_fts
                    SET synonyms=COALESCE((SELECT group_concat(s.synonym, ' ') FROM synonyms s WHERE s.term_id=OLD.term_id), '')
                    WHERE term_id=OLD.term_id;
                END;
                """))


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ensure_data_dir(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

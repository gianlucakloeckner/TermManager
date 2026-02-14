from pathlib import Path

from terminology_manager.persistence.database import (
    create_sqlite_engine,
    initialize_database,
    make_session_factory,
)
from terminology_manager.services.terminology_service import TerminologyService


def _service(tmp_path: Path) -> TerminologyService:
    db = tmp_path / "test.sqlite3"
    engine = create_sqlite_engine(f"sqlite:///{db}")
    initialize_database(engine)
    return TerminologyService(make_session_factory(engine))


def test_history_and_search(tmp_path: Path) -> None:
    service = _service(tmp_path)
    chapter_id = service.save_chapter(None, "Elektrik", "Electrical", True)
    term_id = service.save_term(
        term_id=None,
        de="Generator",
        en="Generator",
        de_desc="Strom erzeuger",
        en_desc="Creates power",
        image=None,
        synonyms=[{"lang": "de", "synonym": "Dynamo", "allowed": True}],
        annotations=[],
        chapter_ids=[chapter_id],
    )

    results = service.search("Dynamo")
    assert any(r.term_id == term_id for r in results)

    service.save_term(
        term_id=term_id,
        de="Generator",
        en="Generator",
        de_desc="Stromerzeuger",
        en_desc="Creates electric power",
        image=None,
        synonyms=[{"lang": "de", "synonym": "Dynamo", "allowed": True}],
        annotations=[{"lang": "de", "note": "Neu", "allowed": True}],
        chapter_ids=[chapter_id],
    )

    history = service.history_for_term(term_id)
    assert len(history) >= 2


def test_prefix_search(tmp_path: Path) -> None:
    service = _service(tmp_path)
    term_id = service.save_term(
        term_id=None,
        de="Foerderband",
        en="Conveyor Belt",
        de_desc="",
        en_desc="",
        image=None,
        synonyms=[],
        annotations=[],
        chapter_ids=[],
    )
    results = service.search("con")
    assert any(r.term_id == term_id for r in results)


def test_duplicate_detection(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.save_term(
        term_id=None,
        de="Leitung",
        en="Cable",
        de_desc="",
        en_desc="",
        image=None,
        synonyms=[{"lang": "de", "synonym": "Kabel", "allowed": True}],
        annotations=[],
        chapter_ids=[],
    )
    report = service.detect_duplicates("Leitung", "Wire", ["Kabel"])
    assert report.exact_term_ids
    assert report.exact_synonym_term_ids

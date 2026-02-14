from __future__ import annotations

from terminology_manager.config import AppConfig
from terminology_manager.persistence.database import (
    create_sqlite_engine,
    ensure_data_dir,
    initialize_database,
    make_session_factory,
)
from terminology_manager.services.terminology_service import TerminologyService


def main() -> None:
    config = AppConfig()
    ensure_data_dir(config.database_path)
    engine = create_sqlite_engine(config.database_url)
    initialize_database(engine)
    service = TerminologyService(make_session_factory(engine))

    elect = service.save_chapter(None, "Elektrik", "Electrical", True)
    mech = service.save_chapter(None, "Mechanik", "Mechanics", True)

    service.save_term(
        term_id=None,
        de="Generator",
        en="Generator",
        de_desc="Erzeugt elektrische Energie.",
        en_desc="Produces electrical energy.",
        image=None,
        synonyms=[{"lang": "de", "synonym": "Dynamo", "allowed": True}],
        annotations=[{"lang": "de", "note": "Regelmäßig warten", "allowed": True}],
        chapter_ids=[elect],
    )

    service.save_term(
        term_id=None,
        de="Lager",
        en="Bearing",
        de_desc="Maschinenelement zur Führung.",
        en_desc="Machine element for guiding shafts.",
        image=None,
        synonyms=[{"lang": "en", "synonym": "Bush", "allowed": False}],
        annotations=[],
        chapter_ids=[mech],
    )


if __name__ == "__main__":
    main()

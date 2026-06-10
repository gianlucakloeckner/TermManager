from pathlib import Path

from terminology_manager.services.import_export import export_terms, import_terms


def _sample_rows() -> list[dict]:
    return [
        {
            "id": 1,
            "de": "Motor",
            "en": "Engine",
            "de_desc": "Beschreibung",
            "en_desc": "Description",
            "annotations": "Hinweis",
            "chapter_ids": [1],
            "synonyms": [{"lang": "de", "synonym": "Antrieb", "allowed": True}],
        }
    ]


def test_json_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "terms.json"
    export_terms(_sample_rows(), path)
    rows = import_terms(path)
    assert rows[0]["de"] == "Motor"


def test_csv_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "terms.csv"
    export_terms(_sample_rows(), path)
    rows = import_terms(path)
    assert rows[0]["en"] == "Engine"

from terminology_manager.services.duplicates import find_fuzzy_matches, normalize


def test_normalize() -> None:
    assert normalize("  Hallo   Welt ") == "hallo welt"


def test_fuzzy_matches() -> None:
    hits = find_fuzzy_matches("Generator", ["generator", "generate", "foo"], threshold=0.8)
    assert hits
    assert hits[0].value == "generator"

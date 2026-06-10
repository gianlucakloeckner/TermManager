# Terminology Manager

Desktop-Anwendung zur Verwaltung zweisprachiger Terminologie (PySide6 + SQLite/FTS5).

## Dokumentation
- Benutzerhandbuch: `docs/UserGuide.md`
- Entwicklerhandbuch: `docs/DeveloperGuide.md`

## Schnellstart
```bash
uv sync --frozen --extra dev
uv run terminology-manager
```

## Kernfunktionen
- Kapitelbasierte Begriffsverwaltung mit Unterkapiteln.
- Schnelle Suche mit erweitertem Treffer-Dropdown.
- Synonyme und Anmerkungen mit Zugelassen-Status.
- Versionshistorie mit Vorher/Nachher-Ansicht.
- Bildverwaltung mit integrierter Bearbeitung.
- Bearbeitungssperre per PIN.
- Optionale In-App-Updateprüfung über GitHub-Releases.

## Qualitätschecks
```bash
uv run ruff check .
uv run black --check .
uv run mypy src
uv run pytest -q
```

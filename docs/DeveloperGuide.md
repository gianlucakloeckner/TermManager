# Developer Guide

## Technologie-Stack
- Python 3.12
- PySide6 (Desktop-UI)
- SQLAlchemy + SQLite
- FTS5 für Volltextsuche
- `uv` für Abhängigkeitsmanagement
- PyInstaller für Packaging

## Projektstruktur
- `src/terminology_manager/main.py` App-Einstiegspunkt
- `src/terminology_manager/ui/main_window.py` Haupt-UI
- `src/terminology_manager/services/` Fachlogik
- `src/terminology_manager/persistence/` DB-Modelle/Repositories
- `src/terminology_manager/assets/` Icons und UI-Assets
- `tests/` Test-Suite
- `.github/workflows/` CI/CD-Pipelines

## Lokales Setup
```bash
uv sync --frozen --extra dev
uv run terminology-manager
```

## Qualitäts-Gates
```bash
uv run ruff check .
uv run black --check .
uv run mypy src
uv run pytest -q
```

## Versionierung
- Für ein Release beide Dateien anpassen:
  - `pyproject.toml` (`project.version`)
  - `src/terminology_manager/__init__.py` (`__version__`)
- `AppConfig.app_version` wird aus `__version__` gelesen.

## Konfiguration
- Laufzeit-Konfigurationsdatei: `data/app_settings.json`
- Dort persistent gespeichert:
  - `database_path`
  - `auto_update_check`
- In `AppConfig` hardcoded:
  - `update_repo_owner`
  - `update_repo_name`

## Datenbank-Hinweise
- Standard-DB-Pfad: `data/terminology.sqlite3`
- Beim ersten Start werden Schema und FTS5-Strukturen initialisiert.
- Die PIN wird zentral in der DB-Tabelle `settings` gespeichert, nicht lokal im JSON.

## Update-Service
- Quelle: GitHub `releases/latest` API.
- Manuelle und automatische Prüfungen laufen über die Einstellungen.
- In-App-Updater:
  - lädt passendes Release-Asset herunter
  - unter Windows mit Self-Replace + Neustart für gepackte Apps
  - auf anderen Plattformen Download mit manueller Installation

## Build
### Lokal
```bash
uv run pyinstaller --name TerminologyManager --windowed src/terminology_manager/main.py
```

### GitHub Actions
- `ci.yml`: Lint, Format-Check, Type-Check, Tests
- `nightly.yml`: Nightly-Artefakte für macOS und Windows
- `release.yml`: Tag-basierte Releases (`v*`)

Packaging-Details:
- macOS: onedir (`--windowed`)
- Windows: onefile (`--windowed --onefile`)
- Assets werden über `--add-data` mitgebündelt
- Windows-Icon wird aus PNG erzeugt und via `--icon` gesetzt
- Optionales Windows-Code-Signing über Repo-Secrets:
  - `CERTIFICATE_PFX_BASE64`
  - `CERTIFICATE_PASSWORD`

## Release-Ablauf
```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```
- Ein Tag-Push startet den Release-Workflow und veröffentlicht Artefakte.

# Terminology Manager

Modern PySide6 desktop app for bilingual terminology management.

## Features
- Lock/unlock editing from top bar (default locked).
- FTS5 search with highlighted snippets.
- Terms, chapters, synonyms, annotations, images.
- Duplicate detection (exact + fuzzy hints).
- Import/export: JSON, CSV, Excel.
- Version history with before/after snapshots.
- Inline image editor (crop/rotate/resize/compress).
- Keyboard power-user mode + command palette (`Ctrl+K`).

## Quick Start
```bash
uv sync --frozen --extra dev
uv run terminology-manager
```

## Development
```bash
uv run ruff check .
uv run black --check .
uv run mypy src
uv run pytest
```

## Build
```bash
uv run pyinstaller --name TerminologyManager --windowed --onefile src/terminology_manager/main.py
```

See `docs/` for architecture, database, testing, and release flow.

# Database

SQLite + SQLAlchemy.

Core tables:
- `terms`
- `synonyms`
- `chapters`
- `term_chapters`
- `settings`
- `version_events`

FTS:
- `term_fts` (FTS5 virtual table)
- triggers keep FTS rows synced when terms/synonyms change.

Versioning:
- `version_events` stores before/after JSON payload per entity action.

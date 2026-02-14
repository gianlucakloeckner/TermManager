# Architecture

- `ui/`: PySide6 views and dialogs.
- `services/`: application business logic.
- `persistence/`: SQLAlchemy models, repositories, DB setup.
- `domain/`: DTOs used across boundaries.

Flow:
1. UI triggers actions.
2. `TerminologyService` validates/orchestrates.
3. Repositories persist and query data.
4. Version snapshots are stored for create/update/delete.

# Development

## Setup
```bash
uv sync --extra dev
```

## Dependency Updates
```bash
uv lock
uv sync --extra dev
```

## Commands
```bash
uv run ruff check .
uv run black .
uv run mypy src
uv run pytest
```

## Running
```bash
uv run terminology-manager
```

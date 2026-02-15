from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AppConfig:
    app_name: str = "Terminologie-Manager"
    database_path: Path = Path("data/terminology.sqlite3")
    edit_pin: str = "1234"
    settings_path: Path = Path("data/app_settings.json")

    @classmethod
    def load(cls) -> AppConfig:
        cfg = cls()
        if not cfg.settings_path.exists():
            return cfg
        try:
            data: Any = json.loads(cfg.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cfg
        if not isinstance(data, dict):
            return cfg
        db_path = data.get("database_path")
        if isinstance(db_path, str) and db_path.strip():
            cfg.database_path = Path(db_path)
        return cfg

    def save(self) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "database_path": str(self.database_path),
        }
        self.settings_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

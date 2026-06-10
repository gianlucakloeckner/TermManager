from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from terminology_manager import __version__


@dataclass(slots=True)
class AppConfig:
    app_name: str = "Terminologie-Manager"
    app_version: str = __version__
    database_path: Path = Path("data/terminology.sqlite3")
    edit_pin: str = "1234"
    update_repo_owner: str = "gianlucakloeckner"
    update_repo_name: str = "TermManager"
    auto_update_check: bool = True
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
        auto_update = data.get("auto_update_check")
        if isinstance(auto_update, bool):
            cfg.auto_update_check = auto_update
        return cfg

    def save(self) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "database_path": str(self.database_path),
            "auto_update_check": self.auto_update_check,
        }
        self.settings_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

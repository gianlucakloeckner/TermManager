from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AppConfig:
    app_name: str = "Terminologie-Manager"
    database_path: Path = Path("data/terminology.sqlite3")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path

BACKUP_DIR_NAME = "backups"
DEFAULT_KEEP = 7


def create_daily_backup(db_path: Path, keep: int = DEFAULT_KEEP) -> Path | None:
    """Erstellt höchstens ein Backup pro Tag, mehrbenutzersicher.

    Die Datenbank liegt typischerweise auf einem Netzlaufwerk, auf das mehrere
    Benutzer zugreifen. Der Backup-Ordner liegt deshalb neben der Datenbank,
    und der Dateiname enthält das Datum: Existiert die heutige Backup-Datei
    bereits, hat ein anderer Benutzer schon gesichert. Gegen gleichzeitige
    Programmstarts schützt das atomare exklusive Anlegen der Zieldatei
    (O_CREAT|O_EXCL) — nur der erste Prozess gewinnt.

    Gibt den Pfad des erstellten Backups zurück, sonst None.
    """
    if not db_path.exists():
        return None
    backup_dir = db_path.parent / BACKUP_DIR_NAME
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    target = backup_dir / f"{db_path.stem}_{date.today().isoformat()}{db_path.suffix}"

    # Zieldatei exklusiv reservieren; verliert genau einer von mehreren
    # gleichzeitig startenden Prozessen nicht, gibt es heute schon ein Backup.
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        return None
    except OSError:
        return None

    tmp = backup_dir / f".{target.name}.{os.getpid()}.tmp"
    try:
        source = sqlite3.connect(str(db_path))
        try:
            destination = sqlite3.connect(str(tmp))
            try:
                # SQLite-Online-Backup: konsistent auch bei parallelen Schreibern.
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()
        os.replace(tmp, target)
    except (OSError, sqlite3.Error):
        tmp.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        return None

    _prune_old_backups(backup_dir, db_path, keep)
    return target


def _prune_old_backups(backup_dir: Path, db_path: Path, keep: int) -> None:
    if keep <= 0:
        return
    # ISO-Datum im Namen: alphabetische Sortierung ist chronologisch.
    backups = sorted(backup_dir.glob(f"{db_path.stem}_*{db_path.suffix}"))
    for old in backups[:-keep]:
        try:
            old.unlink()
        except OSError:
            # Ein anderer Benutzer hat die Datei evtl. gerade gelöscht.
            pass

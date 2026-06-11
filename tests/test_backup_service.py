import sqlite3
from datetime import date
from pathlib import Path

from terminology_manager.services.backup_service import create_daily_backup


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE terms (id INTEGER PRIMARY KEY, de TEXT)")
    conn.execute("INSERT INTO terms (de) VALUES ('Förderband')")
    conn.commit()
    conn.close()


def test_create_daily_backup(tmp_path: Path) -> None:
    db = tmp_path / "terminology.sqlite3"
    _make_db(db)

    result = create_daily_backup(db)

    expected = tmp_path / "backups" / f"terminology_{date.today().isoformat()}.sqlite3"
    assert result == expected
    assert expected.exists()

    conn = sqlite3.connect(str(expected))
    rows = conn.execute("SELECT de FROM terms").fetchall()
    conn.close()
    assert rows == [("Förderband",)]


def test_backup_only_once_per_day(tmp_path: Path) -> None:
    db = tmp_path / "terminology.sqlite3"
    _make_db(db)

    assert create_daily_backup(db) is not None
    # Zweiter Aufruf am selben Tag (z.B. anderer Benutzer): kein neues Backup.
    assert create_daily_backup(db) is None


def test_backup_missing_db(tmp_path: Path) -> None:
    assert create_daily_backup(tmp_path / "missing.sqlite3") is None


def test_backup_rotation(tmp_path: Path) -> None:
    db = tmp_path / "terminology.sqlite3"
    _make_db(db)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for day in ["2026-01-01", "2026-01-02", "2026-01-03"]:
        (backup_dir / f"terminology_{day}.sqlite3").write_bytes(b"old")

    result = create_daily_backup(db, keep=3)

    assert result is not None
    remaining = sorted(p.name for p in backup_dir.glob("terminology_*.sqlite3"))
    assert len(remaining) == 3
    assert "terminology_2026-01-01.sqlite3" not in remaining
    assert result.name in remaining

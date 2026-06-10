# User Guide
a
## Überblick
Der Terminologie-Manager ist eine Desktop-Anwendung zur Verwaltung deutsch/englischer Fachbegriffe mit Kapiteln, Bildern, Synonymen, Anmerkungen und Versionshistorie.

## Start und Sperre
- Die App startet im Nur-Lesen-Modus.
- Über das Schloss-Symbol kann die Bearbeitung entsperrt werden.
- Zum Entsperren ist eine 4-stellige PIN erforderlich.

## Standardablauf
1. Links im Kapitelbaum einen bestehenden Begriff auswählen.
2. Begriffsfelder bearbeiten:
   - `Deutsch`
   - `Englisch`
   - `Beschreibung (DE)`
   - `Beschreibung (EN)`
3. Kapitel im rechten Kapitelbaum zuweisen.
4. `Synonyme` und `Anmerkungen` pflegen.
5. `Speichern` klicken.

## Suche
- Das Suchfeld befindet sich in der Topbar.
- Treffer erscheinen als Dropdown mit:
  - Begriffstitel
  - Kapitel
  - Beginn der deutschen Beschreibung
  - Vorschaubild
- Mit `Enter` wird der erste Treffer geöffnet.

## Synonyme und Anmerkungen
- Sprache ist fest auf Deutsch.
- `Zugelassen` ist ein Dropdown:
  - `✓` = zugelassen (`1`)
  - `✗` = nicht zugelassen (`0`)

## Duplikatprüfung beim Speichern
- Beim Speichern wird automatisch auf mögliche Duplikate geprüft.
- Bei Treffern fragt die App, ob trotzdem gespeichert werden soll.

## Kapitelverwaltung
- Über `Kapitel verwalten` können Kapitel und Unterkapitel erstellt, bearbeitet und gelöscht werden.
- Beim Löschen eines Kapitels (inkl. Unterkapitel) gibt es zwei Optionen:
  - Kapitel und zugehörige Begriffe löschen
  - Begriffe behalten (werden dann ohne Kapitel geführt)

## Batch-Bearbeitung
- Mit `Batch bearbeiten` können mehrere Begriffe gleichzeitig verarbeitet werden.
- Mögliche Aktionen:
  - gemeinsame Kapitelzuweisung
  - gemeinsames Löschen

## Historie
- `Historie` zeigt nur relevante Änderungen.
- Bildänderungen werden als echte Bildvorschau dargestellt.

## Einstellungen
- In `Einstellungen` kann man:
  - den Datenbankpfad ändern
  - die PIN ändern
  - automatische Update-Prüfung beim Start aktivieren/deaktivieren
  - manuell nach Updates suchen

## Tastenkürzel
- `Ctrl+L` Bearbeitung sperren/entsperren
- `Ctrl+N` neuer Begriff
- `Ctrl+S` Begriff speichern
- `Ctrl+R` Begriff löschen
- `Ctrl+B` Batch-Bearbeitung
- `Ctrl+K` Kapitel verwalten
- `Ctrl+H` Historie
- `Ctrl+,` Einstellungen

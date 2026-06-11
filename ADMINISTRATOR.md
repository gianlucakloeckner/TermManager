# Terminologie-Manager – Administratorhandbuch

Dieses Handbuch beschreibt alle Funktionen, die nach dem **Entsperren per PIN**
zur Verfügung stehen. Die Grundfunktionen (Suche, Ansicht, Vorschläge einreichen)
sind in [USER.md](USER.md) beschrieben.

---

## An- und Abmelden

- **Entsperren**: Schloss-Symbol in der Topbar (Strg+L / Cmd+L) → 4-stellige PIN eingeben.
  Das Symbol wird grün, alle Bearbeitungsfunktionen erscheinen in der Topbar.
- **Sperren**: erneut auf das Schloss klicken.
- **PIN ändern**: Einstellungen → "Aktuelle PIN" + "Neue PIN" + Bestätigung eingeben.
  Die PIN wird in der Datenbank gespeichert und gilt damit für alle Benutzer
  der gemeinsamen Datenbank. Standard-PIN bei neuer Datenbank: `1234` –
  **bitte direkt nach der Einrichtung ändern.**

Im entsperrten Zustand erscheinen in der Topbar: **Neuer Begriff, Speichern, Löschen,
Batch bearbeiten, Kapitel verwalten** sowie die **Vorschläge-Glocke**. Der Punkt
"Vorschlag machen" wird ausgeblendet (Admins legen Begriffe direkt an).

---

## Begriffe bearbeiten

### Anlegen, Speichern, Löschen

| Aktion | Kürzel | Verhalten |
|---|---|---|
| Neuer Begriff | Strg+N | Leert den Editor für eine Neuanlage |
| Speichern | Strg+S | Validiert und speichert den Begriff |
| Löschen | Strg+R | Löscht den geöffneten Begriff (mit Rückfrage) |

- **Pflichtfelder**: Deutscher und englischer Begriff.
- **Duplikatprüfung beim Speichern**: Die App erkennt exakte Treffer (Begriffe und
  Synonyme) sowie ähnliche Schreibweisen und fragt nach, ob trotzdem gespeichert
  werden soll.
- **Ungespeicherte Änderungen**: Beim Wechsel zu einem anderen Begriff, bei "Neuer
  Begriff" und beim Schließen der App warnt die Anwendung und bietet
  **Speichern / Verwerfen / Abbrechen** an.

### Synonyme

In der Synonym-Tabelle über **+** hinzufügen und **−** entfernen. Pro Synonym lässt
sich der Status setzen: **✓ zugelassen** oder **✗ nicht zugelassen** (z.B. für
bekannte, aber unerwünschte Bezeichnungen). Synonyme werden von der Suche erfasst.

### Kapitelzuordnung

Im Kapitelbereich des Editors den/die Haken setzen – ein Begriff kann mehreren
Kapiteln zugeordnet sein. Das Filterfeld grenzt lange Kapitellisten ein.

### Bild

- **Bild wählen**: Bilddatei vom Rechner übernehmen.
- **Bild bearbeiten**: öffnet den integrierten Bildeditor:
  - **Zuschneiden**: Auswahl mit der Maus aufziehen, mit den 8 Anfassern justieren,
    verschieben; "Zuschnitt anwenden" übernimmt, Esc verwirft die Auswahl.
  - **↺/↻ 90°**: Drehen in beide Richtungen.
  - **⇆/⇅ Spiegeln**: horizontal und vertikal.
  - **Größe ändern**: Breite/Höhe mit optional gekoppeltem Seitenverhältnis.
  - **Rückgängig/Wiederholen** (Strg+Z / Strg+Shift+Z) und **Zurücksetzen**.
  - **JPEG-Qualität**: Slider unten; die Statuszeile zeigt Maße und voraussichtliche
    Dateigröße. Gespeichert wird erst beim Klick auf "Übernehmen" – Bearbeitungsschritte
    verschlechtern die Qualität also nicht mehrfach.
- **Leeren**: entfernt das Bild vom Begriff.

---

## Kapitel verwalten

Der Punkt **Kapitel verwalten** (Strg+K) öffnet die Kapitelverwaltung:

- **Links**: Kapitelbaum mit Filterfeld. Versteckte Kapitel sind grau markiert.
- **Rechts**: Bearbeitungspanel – ein Klick auf ein Kapitel lädt es sofort ins Formular
  (Name DE/EN, Elternkapitel, Sichtbarkeit). Enter speichert.
- **Neues Kapitel / Neues Unterkapitel**: legt ein Kapitel auf oberster Ebene bzw.
  unter dem ausgewählten Kapitel an.
- **Sichtbarkeit**: "In Suche sichtbar" abwählen, um ein Kapitel samt Begriffen aus
  der Suche auszublenden (z.B. in Vorbereitung befindliche Kapitel).
- **Löschen**: entfernt das Kapitel **inklusive aller Unterkapitel**. Dabei wird
  gefragt, was mit den zugeordneten Begriffen geschehen soll:
  - **Mit Begriffen löschen** – Begriffe werden mitgelöscht.
  - **Begriffe behalten (ohne Kapitel)** – Begriffe bleiben ohne Kapitelzuordnung erhalten.
- Schutz vor Zyklen: Ein Kapitel kann nicht unter sein eigenes Unterkapitel gehängt werden.

Alle Änderungen wirken sofort auf Sidebar und Suche.

---

## Batch-Bearbeitung

Der Punkt **Batch bearbeiten** (Strg+B) bearbeitet viele Begriffe auf einmal:

1. Links Begriffe filtern und mehrere auswählen (Strg/Shift-Klick).
2. **Kapitel zuweisen**: ordnet die Auswahl einem Kapitel zu.
3. **Begriffe löschen**: entfernt alle ausgewählten Begriffe (mit Rückfrage).

---

## Vorschläge prüfen

Die **Glocke** in der Topbar zeigt eingereichte Begriffsvorschläge:

- **Grau**: keine offenen Vorschläge. **Grün mit rotem Zähler**: Anzahl offener Vorschläge.
- Ein Klick öffnet die Prüfliste mit Begriff (DE/EN) und Einreichdatum:
  - **✓ Annehmen**: legt den Begriff sofort an und öffnet ihn im Editor zur
    Vervollständigung (Beschreibungen, Kapitel, Synonyme ergänzen, dann speichern).
  - **✗ Ablehnen**: verwirft den Vorschlag.

---

## Versionshistorie

**Historie** (Strg+H) zeigt für den geöffneten Begriff jede Änderung als Zeitleiste:
Erstellt (grün), Geändert (blau), Gelöscht (rot). Die Detailansicht stellt geänderte
Felder als Vorher/Nachher-Tabelle dar – inklusive Kapitelnamen, Synonymen und
Bildvergleich.

---

## Einstellungen

**Einstellungen** (Strg+,) enthält:

- **Datenbank-Datei**: Pfad zur gemeinsamen SQLite-Datenbank. Für den Mehrbenutzerbetrieb
  auf ein Netzlaufwerk legen, auf das alle Benutzer Zugriff haben. Nach einer Änderung
  ist ein Neustart der App erforderlich.
- **PIN ändern** (siehe oben).
- **Automatische Update-Prüfung** und **manueller Update-Check**.

---

## Automatische Backups

Die Anwendung sichert die Datenbank automatisch:

- **Wann**: einmal pro Tag, beim ersten Programmstart des Tages – egal welcher
  Benutzer. Mehrere Benutzer erzeugen keine doppelten Backups; auch bei gleichzeitigem
  Start entsteht genau ein Backup.
- **Wohin**: in den Ordner `backups/` **neben der Datenbank-Datei** (also auf dem
  Netzlaufwerk), benannt nach dem Schema `terminology_JJJJ-MM-TT.sqlite3`.
- **Aufbewahrung**: die letzten 7 Tagesbackups; ältere werden automatisch entfernt.
- **Konsistenz**: Die Sicherung nutzt die SQLite-Backup-Schnittstelle und ist auch dann
  konsistent, wenn andere Benutzer gerade arbeiten. Das Backup wird vor etwaigen
  Schema-Migrationen eines Updates erstellt.

**Wiederherstellen**: Alle Benutzer schließen die App → gewünschte Backup-Datei aus
`backups/` an den Ort der Datenbank-Datei kopieren (Original vorher umbenennen) →
App neu starten.

---

## Updates & Releases

- Die App prüft GitHub-Releases des Projekts. Neue Versionen werden beim Start
  (sofern aktiviert) oder über Einstellungen → "Jetzt nach Updates suchen" gefunden.
- Nach Bestätigung lädt die App das passende Paket (macOS/Windows), beendet sich,
  ersetzt sich selbst und startet in der neuen Version neu.
- Windows: Sollte ein Update fehlschlagen, liegt ein Protokoll unter
  `%TEMP%\terminology_manager_updates\<Version>\apply_update.log`.

---

## Tastaturkürzel (entsperrt)

| Kürzel | Funktion |
|---|---|
| Strg+L / Cmd+L | Bearbeitung sperren/entsperren |
| Strg+N / Cmd+N | Neuer Begriff |
| Strg+S / Cmd+S | Speichern |
| Strg+R / Cmd+R | Begriff löschen |
| Strg+B / Cmd+B | Batch-Bearbeitung |
| Strg+K / Cmd+K | Kapitel verwalten |
| Strg+H / Cmd+H | Historie |
| Strg+, / Cmd+, | Einstellungen |

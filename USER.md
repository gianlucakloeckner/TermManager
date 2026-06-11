# Terminologie-Manager – Benutzerhandbuch

Dieses Handbuch beschreibt alle Funktionen, die **ohne Anmeldung** zur Verfügung stehen.
Die Anwendung startet im gesperrten Modus: Alle Inhalte sind sichtbar, aber nicht veränderbar.
Funktionen für angemeldete Benutzer sind in [ADMINISTRATOR.md](ADMINISTRATOR.md) beschrieben.

---

## Aufbau der Oberfläche

| Bereich | Inhalt |
|---|---|
| **Topbar** | Logo, "Vorschlag machen", Suchfeld, Schloss-Symbol zum Entsperren |
| **Sidebar (links)** | Kapitel- und Begriffsbaum mit Filter und A-Z-Ansicht |
| **Detailbereich (rechts)** | Der ausgewählte Begriff mit allen Informationen |

---

## Begriffe finden

### Suche (Topbar)

Das Suchfeld oben rechts durchsucht live während der Eingabe:

- deutsche und englische Begriffe,
- beide Beschreibungstexte,
- alle Synonyme.

Schon Wortanfänge genügen ("con" findet "conveyor"). Die Treffer erscheinen in einem
Dropdown unter dem Suchfeld – mit hervorgehobenen Fundstellen, Kapitelzuordnung und
Vorschaubild. Ein Klick auf einen Treffer (oder **Enter** für den ersten Treffer) öffnet
den Begriff.

Begriffe aus Kapiteln, die als "versteckt" markiert sind, erscheinen nicht in der Suche.

### Sidebar

- **Kapitelbaum**: Begriffe sind nach Kapiteln und Unterkapiteln gegliedert. Ein Klick
  auf einen Begriff lädt ihn in den Detailbereich.
- **Kapitel filtern…**: Das Eingabefeld über dem Baum filtert die Kapitel nach Name
  (deutsch oder englisch); die Hierarchie bleibt dabei erhalten.
- **A-Z-Knopf**: Schaltet zwischen Kapitelansicht und einer flachen, alphabetisch
  sortierten Liste aller Begriffe um.

---

## Begriffsansicht

Für jeden Begriff werden angezeigt:

- **Begriff (DE/EN)** – das Begriffspaar in beiden Sprachen
- **Beschreibung (DE/EN)** – ausführliche Erläuterungen
- **Synonyme** – mit Status: **✓** zugelassen, **✗** nicht zugelassen
- **Anmerkungen** – interne Hinweise
- **Bild** – optionale Abbildung zum Begriff

Im gesperrten Modus sind alle Felder schreibgeschützt.

### Versionshistorie

Der Punkt **Historie** (Strg+H / Cmd+H) zeigt für den geöffneten Begriff alle
Änderungen: Wann wurde er erstellt, geändert oder gelöscht, und welche Felder sich
geändert haben – mit farbiger Vorher/Nachher-Gegenüberstellung inklusive Bildvergleich.

---

## Vorschlag machen

Über den Punkt **Vorschlag machen** (ganz links in der Topbar) kannst du neue Begriffe
vorschlagen, ohne angemeldet zu sein:

1. "Vorschlag machen" anklicken.
2. Deutschen und/oder englischen Begriff eingeben – **ein Feld genügt**.
3. "Vorschlag einreichen".

Der Vorschlag landet in der Prüfliste der Administratoren. Wird er angenommen,
erscheint der Begriff anschließend in der Datenbank.

---

## Einstellungen

Der Punkt **Einstellungen** (Strg+, / Cmd+,) bietet:

- **Datenbank-Datei**: Pfad zur gemeinsamen Datenbank (z.B. auf dem Netzlaufwerk).
- **PIN ändern**: erfordert die aktuelle PIN – siehe ADMINISTRATOR.md.
- **Automatische Update-Prüfung** beim Programmstart ein-/ausschalten.
- **Jetzt nach Updates suchen**: manueller Update-Check.

---

## Updates

Beim Start prüft die Anwendung (sofern aktiviert) automatisch auf neue Versionen.
Wird ein Update gefunden, erscheint eine Abfrage mit den Release Notes. Nach Bestätigung
lädt die App das Update herunter, beendet sich, ersetzt sich selbst und startet neu.

---

## Entsperren (Anmeldung)

Das **Schloss-Symbol** rechts in der Topbar (Strg+L / Cmd+L) entsperrt die Bearbeitung
nach Eingabe der 4-stelligen PIN. Erst dann erscheinen die Bearbeitungsfunktionen –
siehe [ADMINISTRATOR.md](ADMINISTRATOR.md).

---

## Tastaturkürzel (ohne Anmeldung)

| Kürzel | Funktion |
|---|---|
| Strg+L / Cmd+L | Bearbeitung entsperren/sperren |
| Strg+H / Cmd+H | Historie des geöffneten Begriffs |
| Strg+, / Cmd+, | Einstellungen |
| Enter (im Suchfeld) | Ersten Suchtreffer öffnen |

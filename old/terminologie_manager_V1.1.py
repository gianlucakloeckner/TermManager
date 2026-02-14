#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Terminologie-Manager — gruppierte Suche & Kapitel-Visibility
- DB: SQLite mit Bildern als BLOB
- DE/EN + Erklärungen, Synonyme (zugelassen/nicht)
- Login: Admin / User (User: nur Suche)
- Suche zeigt standardmäßig ALLE Begriffe, gruppiert nach Kapiteln
  -> Kopf jeder Gruppe: "Kapitel-DE | Chapter-EN"
  -> Ein Kapitel kann umbenannt und ein-/ausgeblendet werden
- Detail: links Deutsch + Erklärung, rechts Englisch + Erklärung, Bild mittig unten

Hinweise zur Migration bestehender DB:
- Tabelle "chapters" erhält bei Bedarf die Spalten name_en (TEXT) und visible (INTEGER, Default 1)
- Bestehende Spalte "name" bleibt als deutscher Name bestehen
"""


#TODO: 


import os
import sys
import traceback
from pathlib import Path
import io
from io import BytesIO
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog, Listbox
import sqlite3
import customtkinter as ctk
from PIL import Image
from customtkinter import CTkImage

# Pillow optional
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False


#Daniel Breuer's Programm
#Version 1.7

# ---------------- Config ----------------
APP_TITLE = "Terminologie-Manager"
# Passe DB-Pfad an - hier das gewünschte Netzlaufwerk
DB_NAME = r"./terminologie.db"
IMG_MAX_W = 420
IMG_MAX_H = 280


ADMIN_PASSWORD = "" # ggf. später in DB verschieben

# ---------------- Database helper ----------------
class DB:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        self._ensure_term_columns()
        self._ensure_chapter_columns()

    # -------- Schema initialisieren --------
    def _init_schema(self):
        with self.conn:
            # Terms
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS terms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    de TEXT NOT NULL,
                    en TEXT NOT NULL,
                    de_desc TEXT,
                    en_desc TEXT,
                    image BLOB
                );
            """)

            # Synonyms
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS synonyms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term_id INTEGER NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
                    lang TEXT NOT NULL,
                    synonym TEXT NOT NULL,
                    allowed INTEGER NOT NULL
                );
            """)

            # -------- Anmerkungen Tabelle --------
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS annotations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term_id INTEGER NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
                    lang TEXT NOT NULL,
                    note TEXT NOT NULL,
                    allowed INTEGER NOT NULL
                );
            """)

            # Kapitel (Basis – Migration ergänzt Spalten, falls alt)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS chapters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                );
            """)

            # Zuordnung Kapitel ↔ Begriffe
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS chapter_terms (
                    chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
                    term_id INTEGER NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
                    PRIMARY KEY (chapter_id, term_id)
                );
            """)

            # Settings (z.B. Logo)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value BLOB
                );
            """)

    def _ensure_term_columns(self):
        cursor = self.conn.execute("PRAGMA table_info(terms)")
        columns = [col[1] for col in cursor.fetchall()]
        with self.conn:
            if "de_desc" not in columns:
                self.conn.execute("ALTER TABLE terms ADD COLUMN de_desc TEXT")
            if "en_desc" not in columns:
                self.conn.execute("ALTER TABLE terms ADD COLUMN en_desc TEXT")
            if "image" not in columns:
                self.conn.execute("ALTER TABLE terms ADD COLUMN image BLOB")

    def _ensure_chapter_columns(self):
        cursor = self.conn.execute("PRAGMA table_info(chapters)")
        columns = {col[1] for col in cursor.fetchall()}
        with self.conn:
            if "name_en" not in columns:
                self.conn.execute("ALTER TABLE chapters ADD COLUMN name_en TEXT")
                self.conn.execute("UPDATE chapters SET name_en = name WHERE name_en IS NULL")
            if "visible" not in columns:
                self.conn.execute("ALTER TABLE chapters ADD COLUMN visible INTEGER NOT NULL DEFAULT 1")

    # -------- Logo (in settings) --------
    def set_logo(self, image_bytes: bytes):
        with self.conn:
            self.conn.execute(
                "REPLACE INTO settings (key, value) VALUES (?, ?)",
                ("logo", image_bytes)
            )

    def get_logo(self) -> bytes | None:
        cur = self.conn.execute("SELECT value FROM settings WHERE key=?", ("logo",))
        row = cur.fetchone()
        return row[0] if row else None


    # -------- Kapitelverwaltung --------
    def add_chapter(self, name_de: str, name_en: str | None = None):
        name_de = (name_de or "").strip()
        name_en = (name_en or "").strip()

        if not name_de:
            return None

        # Prüfen, ob Kapitel existiert
        cur = self.conn.execute(
            "SELECT id FROM chapters WHERE lower(name)=lower(?)",
            (name_de,)
        )
        if cur.fetchone():
            return None  # Existiert schon

        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO chapters(name, name_en, visible) VALUES(?,?,1)",
                (name_de, name_en)
            )
            return cur.lastrowid

    def update_chapter(self, chap_id: int, name_de: str, name_en: str):
        with self.conn:
            self.conn.execute(
                "UPDATE chapters SET name=?, name_en=? WHERE id=?",
                (name_de.strip(), name_en.strip(), chap_id)
            )

    def set_chapter_visibility(self, chap_id: int, visible: bool):
        with self.conn:
            self.conn.execute(
                "UPDATE chapters SET visible=? WHERE id=?",
                (1 if visible else 0, chap_id)
            )

    def delete_chapter(self, chap_id):
        with self.conn:
            self.conn.execute("DELETE FROM chapters WHERE id=?", (chap_id,))

    def list_chapters(self, only_visible: bool = False):
        if only_visible:
            cur = self.conn.execute(
                "SELECT id, name, name_en, visible FROM chapters WHERE visible=1 ORDER BY lower(name)"
            )
        else:
            cur = self.conn.execute(
                "SELECT id, name, name_en, visible FROM chapters ORDER BY lower(name)"
            )
        return cur.fetchall()

    def get_chapter_by_id(self, chap_id: int):
        cur = self.conn.execute(
            "SELECT id, name, name_en, visible FROM chapters WHERE id=?",
            (chap_id,)
        )
        return cur.fetchone()

    def assign_term_to_chapter(self, term_id: int, chap_id: int):
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO chapter_terms(chapter_id, term_id) VALUES(?,?)",
                (chap_id, term_id)
            )

    def remove_term_from_chapter(self, term_id: int, chap_id: int):
        with self.conn:
            self.conn.execute(
                "DELETE FROM chapter_terms WHERE chapter_id=? AND term_id=?",
                (chap_id, term_id)
            )

    def list_terms_in_chapter(self, chap_id: int):
        cur = self.conn.execute(
            """
            SELECT t.id, t.de, t.en
            FROM chapter_terms ct
            JOIN terms t ON t.id = ct.term_id
            WHERE ct.chapter_id=?
            ORDER BY lower(t.de)
            """,
            (chap_id,)
        )
        return cur.fetchall()

    def list_chapters_for_term(self, term_id: int):
        cur = self.conn.execute(
            """
            SELECT c.id, c.name, c.name_en, c.visible
            FROM chapter_terms ct
            JOIN chapters c ON c.id = ct.chapter_id
            WHERE ct.term_id=?
            ORDER BY lower(c.name)
            """,
            (term_id,)
        )
        return cur.fetchall()

    # -------- Terms CRUD --------
    def add_term(self, de, en, de_desc, en_desc, image_bytes):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO terms(de,en,de_desc,en_desc,image) VALUES(?,?,?,?,?)",
                (de.strip(), en.strip(), (de_desc or "").strip(), (en_desc or "").strip(), image_bytes)
            )
            return cur.lastrowid

    def get_term(self, term_id: int) -> dict | None:
        """Liest einen einzelnen Begriff inkl. Beschreibung & Bild aus der DB."""
        cur = self.conn.execute("""
            SELECT id, de, en, de_desc, en_desc, image
            FROM terms
            WHERE id = ?
        """, (term_id,))
        row = cur.fetchone()
        if not row:
            return None
        return dict(row)

    def update_term(self, term_id, de, en, de_desc, en_desc, image_bytes):
        with self.conn:
            self.conn.execute(
                "UPDATE terms SET de=?, en=?, de_desc=?, en_desc=?, image=? WHERE id=?",
                (de.strip(), en.strip(), (de_desc or "").strip(), (en_desc or "").strip(), image_bytes, term_id)
            )

    def delete_term(self, term_id):
        with self.conn:
            self.conn.execute("DELETE FROM terms WHERE id=?", (term_id,))

    def get_term_by_id(self, term_id):
        cur = self.conn.execute("SELECT * FROM terms WHERE id=?", (term_id,))
        return cur.fetchone()

    def list_terms(self):
        cur = self.conn.execute("SELECT * FROM terms ORDER BY lower(de)")
        return cur.fetchall()

    # -------- Synonyms --------
    def add_synonym(self, term_id, lang, synonym, allowed=True):
        with self.conn:
            self.conn.execute(
                "INSERT INTO synonyms (term_id, lang, synonym, allowed) VALUES (?, ?, ?, ?)",
                (term_id, lang, synonym, int(allowed))
            )

    def update_synonym_allowed(self, syn_id, allowed):
        with self.conn:
            self.conn.execute(
                "UPDATE synonyms SET allowed=? WHERE id=?",
                (1 if allowed else 0, syn_id)
            )

    def delete_synonyms_for_term(self, term_id):
        with self.conn:
            self.conn.execute("DELETE FROM synonyms WHERE term_id=?", (term_id,))

    def list_synonyms(self, term_id):
        cur = self.conn.execute(
            "SELECT * FROM synonyms WHERE term_id=? ORDER BY lang, synonym",
            (term_id,)
        )
        # sqlite3.Row erlaubt Zugriff per Key
        return [dict(row) for row in cur.fetchall()]

    def synonym_exists(self, term_id, lang, synonym):
        cur = self.conn.execute(
            "SELECT 1 FROM synonyms WHERE term_id=? AND lang=? AND synonym=?",
            (term_id, lang, synonym)
        )
        return cur.fetchone() is not None

    # -------- Anmerkungen --------
    def get_annotation(self, term_id):
        """Liefert alle Anmerkungen als Liste von Dicts."""
        cur = self.conn.execute(
            "SELECT id, lang, note, allowed FROM annotations WHERE term_id=? ORDER BY id DESC",
            (term_id,)
        )
        return [dict(r) for r in cur.fetchall()]

    def save_annotation(self, term_id, note, lang="de", allowed=1):
        """
        Speichert oder aktualisiert eine Anmerkung für einen Begriff.
        Parameter:
            term_id: ID des Begriffs
            note: Text der Anmerkung
            lang: 'de' oder 'en' (Sprache der Anmerkung)
            allowed: 1=zugelassen, 0=nicht zugelassen (optional)
        """
        with self.conn:
            cur = self.conn.execute(
                "SELECT id FROM annotations WHERE term_id=? AND lang=?",
                (term_id, lang)
            )
            if cur.fetchone():
                self.conn.execute(
                    "UPDATE annotations SET note=?, allowed=? WHERE term_id=? AND lang=?",
                    (note, allowed, term_id, lang)
                )
            else:
                self.conn.execute(
                    "INSERT INTO annotations (term_id, lang, note, allowed) VALUES (?, ?, ?, ?)",
                    (term_id, lang, note, allowed)
                )

    def list_annotations(self, term_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM annotations WHERE term_id = ?", (term_id,))
        return cursor.fetchall()


    # -------- Suche --------
    def search(self, query: str):
        q = (query or "").strip()
        if not q:
            return []
        like = f"%{q}%"
        sql = r"""
        SELECT 'term' AS kind, t.id AS id, t.de, t.en, t.de_desc, t.en_desc, t.image,
        t.de AS matched, 1 AS allowed
        FROM terms t
        WHERE lower(t.de)=lower(?) OR lower(t.en)=lower(?)
        UNION
        SELECT 'term_like' AS kind, t.id AS id, t.de, t.en, t.de_desc, t.en_desc, t.image,
        CASE WHEN instr(lower(t.de), lower(?))>0 THEN t.de ELSE t.en END AS matched,
        1 AS allowed
        FROM terms t
        WHERE lower(t.de) LIKE lower(?) OR lower(t.en) LIKE lower(?)
        UNION
        SELECT 'syn' AS kind, t.id AS id, t.de, t.en, t.de_desc, t.en_desc, t.image,
        s.synonym AS matched, s.allowed AS allowed
        FROM synonyms s
        JOIN terms t ON t.id = s.term_id
        WHERE lower(s.synonym)=lower(?)
        UNION
        SELECT 'syn_like' AS kind, t.id AS id, t.de, t.en, t.de_desc, t.en_desc, t.image,
        s.synonym AS matched, s.allowed AS allowed
        FROM synonyms s
        JOIN terms t ON t.id = s.term_id
        WHERE lower(s.synonym) LIKE lower(?)
        ;
        """
        cur = self.conn.execute(sql, (q, q, q, like, like, q, like))
        rows = cur.fetchall()
        seen, res = set(), []
        for r in rows:
            key = (r["id"], (r["matched"] or "").lower())
            if key not in seen:
                seen.add(key)
                res.append(r)

        def rank(row):
            kind_rank = {"term": 0, "syn": 1, "term_like": 2, "syn_like": 3}.get(row["kind"], 9)
            exact = 0 if (row["matched"] or "").lower() == q.lower() else 1
            return (kind_rank, exact, (row["de"] or "").lower())

        res.sort(key=rank)
        return res

    def get_chapter_by_name(self, name: str):
        cur = self.conn.execute("SELECT * FROM chapters WHERE name=?", (name,))
        return cur.fetchone()

    def load_all_terms_grouped(self):
        pass


# ---------------- Image cache ----------------
class ImageCache:
    def __init__(self):
        self.cache = {}

    def load_from_bytes(self, data: bytes | None):
        if not PIL_AVAILABLE or not data:
            return None
        key = (len(data), data[:16])
        if key in self.cache:
            return self.cache[key]
        try:
            img = Image.open(BytesIO(data))
            img.thumbnail((IMG_MAX_W, IMG_MAX_H))
            photo = ImageTk.PhotoImage(img)
            self.cache[key] = photo
            return photo
        except Exception:
            return None


# Firmen-/Akzentfarben
FIRMEN_BLAU     = "#1E3A8A"
FIRMEN_GRAU     = "#2D2F33"  #"#2D2F33" Hintergrund
FIRMEN_SCHWARZ  = "#0F1115"  # Hintergrund Überschrift
AKZENT_NEON     = "#4472C4"  # Überschriften


# ---------------- UI ----------------
class TerminologyApp(ctk.CTkFrame):  # <— früher: ttk.Frame
    edit_note_list: Listbox

    def __init__(self, master, role="admin"):
        super().__init__(master, fg_color=FIRMEN_SCHWARZ)
        self.txt_search_synonyms = None
        self.master = master
        self.pack(fill=tk.BOTH, expand=True)

        self.db = DB(Path(DB_NAME))
        self.img_cache = ImageCache()
        self.role = role
        self.current_term_id = None
        self._term_item_map = {}  # Treeview iid -> term_id
        self._admin_chap_item_map = {}
        self._admin_term_item_map = {}

        self._dummy_img = None

        # --- Shell/UI aufbauen ---
        self._build_ui_shell()  # Sidebar + Content
        self._build_tabs()  # Tabs als CTkTabview (modern)

        # --- initiale Daten / Assets ---
        self.load_logo()
        self.reload_chap_listbox()
        self.root = master

        # --- ttk-Dark-Style für Treeview etc. (falls du weiterhin ttk nutzt) ---
        self._apply_ttk_dark_style()
        # Logo laden und anzeigen

        #Mal sehen ob das geht
        self.search_de_var = None
        self.txt_search_de_desc = None
        self.search_en_var = None
        self.txt_search_en_desc = None
        self.search_img_label = None
        self.edit_syn_list = None

        # Admin-Synonyme anzeigen (editierbar) -- FIX: benutze pack statt grid (kein Mischen erlaubt)
        self.synonym_field = ctk.CTkTextbox(self.edit_tab, width=300, height=150)
        self.synonym_field.pack(fill="both", expand=True, padx=10, pady=10)
        self.synonym_field.configure(font=("Segoe UI Symbol", 12))

        # Eingabe für neue Synonyme
        self.new_synonym_entry = ctk.CTkEntry(self.edit_tab)
        self.new_synonym_entry.pack(fill="x", padx=10, pady=5)


    def _create_dummy_image(self, size=(150, 150), color=(200, 200, 200, 255)):
        """Erzeugt ein Dummy-Bild als Platzhalter (z. B. graues Rechteck)."""
        img = Image.new("RGBA", size, color)
        return ctk.CTkImage(light_image=img, dark_image=img, size=size)

    def _build_admin_tab(self, parent):
        # Logo-Bereich
        logo_frame = ttk.LabelFrame(parent, text="Firmenlogo")
        logo_frame.pack(fill=tk.X, padx=8, pady=8)

        # Aktuelles Logo anzeigen
        self.admin_logo_label = ttk.Label(logo_frame)
        self.admin_logo_label.pack(side=tk.LEFT, padx=8, pady=8)
        self.load_logo()

        # Button zum Ändern
        ttk.Button(logo_frame, text="Logo ändern", command=self.change_logo).pack(side=tk.LEFT, padx=8)

    def load_logo(self):
        """Lädt das Firmenlogo aus der DB und zeigt es überall korrekt an (Such- und Adminseite)."""
        logo_bytes = self.db.get_logo()
        if not logo_bytes:
            return

        import io
        from PIL import Image, ImageTk

        img = Image.open(io.BytesIO(logo_bytes))
        img = img.resize((220, 100))

        # Für CTkLabel
        self._logo_ctk = ctk.CTkImage(light_image=img, dark_image=img, size=(220, 100))
        # Für ttk.Label
        self._logo_tk = ImageTk.PhotoImage(img)

        # --- Haupt-Logo (search_tab) ---
        if hasattr(self, "logo_label") and self.logo_label.winfo_exists():
            if isinstance(self.logo_label, ctk.CTkLabel):
                self.logo_label.configure(image=self._logo_ctk, text="")
            else:
                self.logo_label.configure(image=self._logo_tk, text="")

        # --- Admin-Logo (admin_tab) ---
        if hasattr(self, "admin_logo_label") and self.admin_logo_label.winfo_exists():
            self.admin_logo_label.configure(image=self._logo_tk, text="")

    # ---------- Kapitelverwaltung ----------

    def on_edit_select(self, event):
        sel = self.term_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._term_rows):
            return
        term_id = self._term_rows[idx]["id"]
        self.edit_load_term(term_id)

    # In der App-Klasse
    def add_chapter_gui(self):
        # Name auf Deutsch abfragen
        name_de = simpledialog.askstring("Kapitel hinzufügen", "Name des neuen Kapitels:", parent=self.master)
        if not name_de:
            return  # Abbrechen, wenn nichts eingegeben

        name_en = ""  # Englisch leer, kann später bearbeitet werden

        # Kapitel in DB anlegen
        chap_id = self.db.add_chapter(name_de, name_en)

        if chap_id:
            # GUI sofort aktualisieren
            self.reload_chap_listbox()
            self.reload_terms()  # Treeview aktualisieren
            self.load_all_terms_grouped()
            # GUI mit gespeicherten Werten neu laden
            if self.edit_current_id:
                self.edit_load_term(self.edit_current_id)

            messagebox.showinfo("Kapitel hinzugefügt", f"Kapitel '{name_de}' erstellt.", parent=self.master)
        else:
            messagebox.showwarning("Fehler", f"Kapitel '{name_de}' existiert bereits!", parent=self.master)

    def rename_chapter_tree(self, chapter_id=None):
        if chapter_id is None:
            # Wenn über Button, Kapitel zuerst auswählen
            chapters = self.db.list_chapters()
            if not chapters:
                messagebox.showwarning("Keine Kapitel", "Keine Kapitel zum Umbenennen vorhanden.")
                return
            names = [c['name'] for c in chapters]
            sel = simpledialog.askstring("Kapitel wählen",
                                         f"Vorhandene Kapitel:\n{', '.join(names)}\n\nWelches Kapitel umbenennen?")
            if not sel:
                return
            chapter = next((c for c in chapters if c["name"] == sel), None)
            if not chapter:
                messagebox.showwarning("Nicht gefunden", f"Kapitel '{sel}' nicht gefunden.")
                return
            chapter_id = chapter["id"]
        else:
            chapter = self.db.get_chapter_by_id(chapter_id)

        if not chapter:
            return

        # DE-Name abfragen
        new_de = simpledialog.askstring("Neuer Name", f"Neuer DE-Name für '{chapter['name']}'?",
                                        initialvalue=chapter["name"])
        if not new_de:
            return

        # EN-Name leer lassen
        new_en = ""

        self.db.update_chapter(chapter_id, new_de, new_en)
        self.reload_terms()
        self.load_all_terms_grouped()

    def show_chapter_visibility_dialog(self):
        dlg = tk.Toplevel(self.master)
        dlg.title("Kapitel ein-/ausblenden")
        dlg.transient(self.master)
        dlg.grab_set()

        frm = ttk.Frame(dlg)
        frm.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        vars_by_id = {}
        chapters = self.db.list_chapters()
        ttk.Label(frm, text="Haken = sichtbar in der Suche").pack(anchor="w", pady=(0,8))

        chk_container = ttk.Frame(frm)
        chk_container.pack(fill=tk.BOTH, expand=True)
        for c in chapters:
            v = tk.BooleanVar(value=bool(c["visible"]))
            cb = ttk.Checkbutton(chk_container, text=f"{c['name']} | {c['name_en'] or ''}", variable=v)
            cb.pack(anchor="w")
            vars_by_id[c["id"]] = v

        btnbar = ttk.Frame(frm)
        btnbar.pack(fill=tk.X, pady=(10,0))
        def all_on():
            for v in vars_by_id.values():
                v.set(True)
        def all_off():
            for v in vars_by_id.values():
                v.set(False)
        ttk.Button(btnbar, text="Alle an", command=all_on).pack(side=tk.LEFT)
        ttk.Button(btnbar, text="Alle aus", command=all_off).pack(side=tk.LEFT, padx=6)

        def save():
            for chap_id, var in vars_by_id.items():
                self.db.set_chapter_visibility(chap_id, var.get())
            dlg.destroy()
            self.load_all_terms_grouped()
        ttk.Button(btnbar, text="Speichern", command=save).pack(side=tk.RIGHT)
        ttk.Button(btnbar, text="Abbrechen", command=dlg.destroy).pack(side=tk.RIGHT, padx=6)

       # Fenster mittig
        dlg.update_idletasks()
        w, h = dlg.winfo_width(), dlg.winfo_height()
        ws, hs = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        x, y = (ws//2 - w//2), (hs//2 - h//2)
        dlg.geometry(f"{w}x{h}+{x}+{y}")

    def change_logo(self):
        path = filedialog.askopenfilename(
            title="Firmenlogo auswählen",
            filetypes=[("Bilddateien", "*.png;*.jpg;*.jpeg;*.gif")]
        )
        if not path:
            return

        with open(path, "rb") as f:
            data = f.read()
        self.db.set_logo(data)

        # Logo in allen Tabs aktualisieren
        self.load_logo()

        messagebox.showinfo("Logo", "Firmenlogo wurde aktualisiert.", parent=self.master)


    def _build_ui_shell(self):
        # Fenster-Setup
        self.master.title(APP_TITLE)
        w, h = 1100, 720
        ws, hs = self.master.winfo_screenwidth(), self.master.winfo_screenheight()
        x, y = (ws // 2 - w // 2), (hs // 2 - h // 2)
        self.master.geometry(f"{w}x{h}+{x}+{y}")
        self.master.minsize(900, 600)

        # Grid für Sidebar/Content
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar (links)
        self.sidebar = ctk.CTkFrame(self, fg_color=FIRMEN_GRAU, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="ns")

        ctk.CTkLabel(
            self.sidebar, text="⚡ KriZi App",
            font=("Segoe UI", 18, "bold"),
            text_color=AKZENT_NEON
        ).pack(pady=16, padx=12)

        self.btn_search = ctk.CTkButton(
            self.sidebar, text="🔍 Suche",
            fg_color="transparent", hover_color=FIRMEN_BLAU,
            anchor="w", command=lambda: self._show_tab("search")
        )
        self.btn_search.pack(fill="x", padx=8, pady=4)

        if self.role == "admin":
            self.btn_admin = ctk.CTkButton(
                self.sidebar, text="⚙️ Admin",
                fg_color="transparent", hover_color=FIRMEN_BLAU,
                anchor="w", command=lambda: self._show_tab("admin")
            )
            self.btn_admin.pack(fill="x", padx=8, pady=4)

        # Content (rechts)
        self.content = ctk.CTkFrame(self, fg_color=FIRMEN_SCHWARZ)
        self.content.grid(row=0, column=1, sticky="nsew")

    # ===== Tabs (modern) =====
    def _build_tabs(self):
        # Tab-Container
        self.tab = ctk.CTkTabview(self.content, fg_color=FIRMEN_GRAU, corner_radius=12)
        self.tab.pack(fill="both", expand=True, padx=12, pady=12)

        self.search_tab = self.tab.add("User Suche")
        if self.role == "admin":
            self.edit_tab = self.tab.add("Admin Bearbeitung")
        else:
            self.edit_tab = None

        # --> Wichtig: Hier deine bestehenden Builder verwenden!
        self._build_search_tab(self.search_tab)
        if self.edit_tab is not None:
            self._build_edit_tab(self.edit_tab)

    def _show_tab(self, key: str):
        # CTkTabview zeigt Tabs über Namen an
        if key == "search":
            self.tab.set("User Suche")
        elif key == "admin" and self.edit_tab is not None:
            self.tab.set("Admin Bearbeitung")

    # ===== ttk Dark-Style für Treeview etc. =====
    def _apply_ttk_dark_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Grundfarben
        style.configure(
            ".", background=FIRMEN_SCHWARZ, foreground="#E6E6E6"
        )
        style.configure(
            "TFrame", background=FIRMEN_SCHWARZ
        )
        style.configure(
            "TLabel", background=FIRMEN_SCHWARZ, foreground="#000000"
        )
        style.configure(
            "TEntry", fieldbackground=FIRMEN_GRAU, foreground="#FFFFFF"
        )

        # Treeview dunkel + selektionsfarbe
        style.configure(
            "Treeview",
            background=FIRMEN_GRAU,
            fieldbackground=FIRMEN_GRAU,
            foreground="#000000", #Text Kapitel
            rowheight=26,
            bordercolor="#3A3D44",
            borderwidth=0
        )
        style.map(
            "Treeview",
            background=[("selected", FIRMEN_BLAU)],
            foreground=[("selected", "#FFFFFF")]
        )

#Datenbank Anmerkungen
    def create_tables(self):
        # Terms-Tabelle (Begriffe)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS terms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                de TEXT,
                en TEXT
            );
        """)
        # Annotations-Tabelle
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS annotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                term_id INTEGER NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
                lang TEXT NOT NULL,
                note TEXT NOT NULL,
                allowed INTEGER NOT NULL
            );
        """)
        self.conn.commit()

# NEU
    # ----------- Rechtsklick im Baum -----------
    def on_tree_right_click(self, event):
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return

        tags = self.tree.item(item_id, "tags")
        if "chapter" not in tags:
            return

        chapter_id = self._chapter_item_map.get(item_id)
        if chapter_id is None:
            return

        chapter = self.db.get_chapter_by_id(chapter_id)
        if chapter is None:
            return

        # Menü für den Baum
        menu.add_command(label="Umbenennen", command=lambda: self.rename_chapter_tree(chapter_id))

        menu.post(event.x_root, event.y_root)

    # ----------- Rechtsklick in Kapitelverwaltung -----------
    def on_chapter_right_click(self, event):
        index = self.chap_listbox.nearest(event.y)
        if index < 0:
            return

        chapter_id = self._chap_listbox_map.get(index)
        if not chapter_id:
            return

        chapter = self.db.get_chapter_by_id(chapter_id)
        if not chapter:
            return

        menu = tk.Menu(self.chap_listbox, tearoff=0)

        # Umbenennen
        menu.add_command(
            label="Umbenennen",
            command=lambda cid=chapter_id: self.rename_chapter_gui(cid)
        )

        # Löschen
        menu.add_command(
            label="Löschen",
            command=lambda cid=chapter_id: self.delete_chapter_gui(cid)
        )

        menu.post(event.x_root, event.y_root)

    # ---------- Kapitel umbenennen ----------
    def rename_chapter_gui(self, chapter_id):
        chapter = self.db.get_chapter_by_id(chapter_id)
        if not chapter:
            return

        new_name = simpledialog.askstring(
            "Kapitel umbenennen",
            f"Neuer Name für Kapitel '{chapter['name']}'?",
            initialvalue=chapter["name"],
            parent=self.master
        )
        if not new_name:
            return

        self.db.update_chapter(chapter_id, new_name, chapter["name_en"])

        # GUI sofort aktualisieren
        self.reload_chap_listbox()
        self.reload_terms()  # <- Neu: aktualisiert den Treeview
        self.load_all_terms_grouped()
        # GUI mit gespeicherten Werten neu laden
        if self.edit_current_id:
            self.edit_load_term(self.edit_current_id)

    def show_chapter_context_menu(self, event, iid):
        menu = tk.Menu(self, tearoff=0)
        chap_id = self._admin_chap_item_map.get(iid)
        if not chap_id:
            return
        menu.add_command(label="Kapitel umbenennen", command=lambda: self.rename_chapter_gui(chap_id))
        menu.add_command(label="Kapitel löschen", command=lambda: self.delete_chapter_gui(chap_id))
        menu.post(event.x_root, event.y_root)

    # ---------- Kapitel löschen ----------
    def delete_chapter_gui(self, chap_id=None):
        if chap_id is None:
            # Benutzerwahl
            chapters = self.db.list_chapters()
            if not chapters:
                messagebox.showwarning("Keine Kapitel", "Keine Kapitel zum Löschen vorhanden.", parent=self.master)
                return
            names = [c["name"] for c in chapters]
            sel = simpledialog.askstring(
                "Kapitel löschen",
                f"Vorhandene Kapitel:\n{', '.join(names)}\n\nWelches Kapitel löschen?",
                parent=self.master
            )
            if not sel:
                return
            chapter = next((c for c in chapters if c["name"] == sel), None)
            if not chapter:
                messagebox.showwarning("Nicht gefunden", f"Kapitel '{sel}' nicht gefunden.", parent=self.master)
                return
            chap_id = chapter["id"]

        if messagebox.askyesno("Löschen bestätigen", "Kapitel wirklich löschen?", parent=self.master):
            self.db.delete_chapter(chap_id)  # löscht nur DB

            # GUI sofort aktualisieren
            self.reload_chap_listbox()
            self.reload_terms()
            self.load_all_terms_grouped()
            messagebox.showinfo("Erfolg", "Kapitel gelöscht.", parent=self.master)
            # GUI mit gespeicherten Werten neu laden
            if self.edit_current_id:
                self.edit_load_term(self.edit_current_id)

    # ---------- User-Seite ------------------------------------------------------------------------
    def _build_search_tab(self, parent):
        # Dummy-Bild einmalig vorbereiten
        if self._dummy_img is None:
            self._dummy_img = self._create_dummy_image()

        # Top-Leiste (Logo + Suche)
        top_frame = ctk.CTkFrame(parent, fg_color="#333333", corner_radius=0)
        top_frame.pack(fill="x", padx=8, pady=(6, 8))

         # Sucheingabe
        ctk.CTkLabel(top_frame, text="Begriff suchen:", text_color="#00FFAA").pack(side="left", padx=(0, 8))
        self.q_var = tk.StringVar()
        self.search_entry = ctk.CTkEntry(top_frame, textvariable=self.q_var, width=400,
                                             placeholder_text="Name, ID oder E-Mail eingeben...")
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.bind("<Return>", lambda e: self.on_search())
        self.btn_search_go = ctk.CTkButton(top_frame, text="Suchen", command=self.on_search, fg_color="#1D4ED8")
        self.btn_search_go.pack(side="left", padx=6)
        self.btn_reset = ctk.CTkButton(top_frame, text="Zurücksetzen", command=self.on_reset)
        self.btn_reset.pack(side="left")

        # Body-Pane
        body = ctk.CTkFrame(parent, fg_color="#111111")
        body.pack(fill="both", expand=True, padx=8, pady=6)

        # Left: Treeview / Kapitel
        left_frame = ctk.CTkFrame(body, fg_color="#222222")
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 4))

        cols = ("de", "en")
        self.tree = tk.ttk.Treeview(left_frame, columns=cols, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Kapitel")
        self.tree.heading("de", text="Deutsch")
        self.tree.heading("en", text="Englisch")
        self.tree.pack(fill="both", expand=True, side="left")
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        vs = tk.ttk.Scrollbar(left_frame, orient="vertical", command=self.tree.yview)
        vs.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=vs.set)

        # Right: Detailbereich
        right_frame = ctk.CTkFrame(body, fg_color="#111111")
        right_frame.pack(side="left", fill="both", expand=True)

        # Deutsch
        de_frame = ctk.CTkFrame(right_frame, fg_color="#111111")
        de_frame.pack(fill="x", pady=(4, 8))
        ctk.CTkLabel(de_frame, text="Deutsch", font=("Segoe UI", 14, "bold"), text_color="#00FFAA").pack(anchor="w")
        self.lbl_de = ctk.CTkEntry(de_frame, fg_color="#222222", text_color="white", state="disabled")
        self.lbl_de.pack(fill="x", pady=(4, 8))
        ctk.CTkLabel(de_frame, text="Definition", font=("Segoe UI", 12, "bold"), text_color="#00FFAA").pack(
            anchor="w")
        self.txt_de_desc = ctk.CTkTextbox(de_frame, height=8, wrap="word", fg_color="#222222", text_color="white",
                                            state="disabled")
        self.txt_de_desc.pack(fill="both", expand=True)

        # Englisch
        en_frame = ctk.CTkFrame(right_frame, fg_color="#111111")
        en_frame.pack(fill="x", pady=(4, 8))
        ctk.CTkLabel(en_frame, text="English", font=("Segoe UI", 14, "bold"), text_color="#00FFAA").pack(anchor="w")
        self.lbl_en = ctk.CTkEntry(en_frame, fg_color="#222222", text_color="white", state="disabled")
        self.lbl_en.pack(fill="x", pady=(4, 8))
        ctk.CTkLabel(en_frame, text="Definition", font=("Segoe UI", 12, "bold"), text_color="#00FFAA").pack(
            anchor="w")
        self.txt_en_desc = ctk.CTkTextbox(en_frame, height=8, wrap="word", fg_color="#222222", text_color="white",
                                            state="disabled")
        self.txt_en_desc.pack(fill="both", expand=True)

        # Synonyme + Anmerkungen
        syn_note_frame = ctk.CTkFrame(right_frame, fg_color="#111111")
        syn_note_frame.pack(fill="both", expand=True, pady=(4, 8))

        syn_frame = ctk.CTkFrame(syn_note_frame, fg_color="#222222", corner_radius=10)
        syn_frame.pack(side="left", fill="both", expand=True, padx=(0, 4), pady=4)
        ctk.CTkLabel(syn_frame, text="Synonyme", font=("Segoe UI", 12, "bold"), text_color="#00FFAA").pack(
            anchor="w",
            padx=6,
            pady=4)
        self.edit_syn_list = ctk.CTkTextbox(syn_frame, height=10, wrap="word", fg_color="#333333",
                                            text_color="white",
                                            state="disabled")
        self.edit_syn_list.pack(fill="both", expand=True, padx=6, pady=6)

        note_frame = ctk.CTkFrame(syn_note_frame, fg_color="#222222", corner_radius=10)
        note_frame.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4)
        ctk.CTkLabel(note_frame, text="Anmerkungen", font=("Segoe UI", 12, "bold"), text_color="#00FFAA").pack(
               anchor="w", padx=6, pady=4)
        self.note_text = ctk.CTkTextbox(note_frame, fg_color="#333333", text_color="white", state="disabled")
        self.note_text.pack(fill="both", expand=True, padx=6, pady=6)

        # Bild
        img_frame = ctk.CTkFrame(right_frame, fg_color="#111111")
        img_frame.pack(fill="both", expand=True, pady=(6, 8))
        self.img_label = ctk.CTkLabel(img_frame, text="(kein Bild)", fg_color="#222222", anchor="center",
                                          image=self._dummy_img)
        self.img_label.pack(fill="both", expand=True)
        self.img_label.image_ref = self._dummy_img

         # Kapitel-Anzeige
        self.chapter_frame = ctk.CTkFrame(right_frame, fg_color="#222222", corner_radius=10)
        self.chapter_frame.pack(fill="x", pady=4)
        self.chapter_label = ctk.CTkLabel(self.chapter_frame, text="", text_color="#00FFAA")
        self.chapter_label.pack(anchor="w", padx=4, pady=2)

        # Begriffe initial laden
        self.load_all_terms_grouped()

            # ---------- Methoden für Suche ----------
    # Hilfsfunktion Bildanzeige
    def show_image(self, label: ctk.CTkLabel, image_bytes: bytes | None,
                   max_size: tuple[int, int] = (250, 250)):
        """Zeigt Bild oder Dummy an."""
        try:
            if hasattr(label, "image_ref"):
                label.image_ref = None
            if image_bytes:
                img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
                w, h = img.size
                ratio = min(max_size[0] / w, max_size[1] / h, 1.0)
                img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(int(w * ratio), int(h * ratio)))
                label.configure(text="", image=ctk_img)
                label.image_ref = ctk_img
            else:
                label.configure(text="(kein Bild)", image=self._dummy_img)
                label.image_ref = self._dummy_img
        except Exception as e:
            print("Fehler beim Laden des Bildes:", e)
            label.configure(text="(kein Bild)", image=self._dummy_img)
            label.image_ref = self._dummy_img

    def _clear_tree(self):
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self._term_item_map.clear()

#Admin Laden der Informationen auf der Suchen seite
    def load_all_terms_grouped(self, show_chapters=True):
        """Lädt alle Begriffe für Treeview inkl. Definitionen und Bilder."""
        self._clear_tree()
        self._term_item_map = {}

        chapters = [dict(c) for c in self.db.list_chapters(only_visible=False)]
        all_term_ids_in_chapters = set()

        for c in chapters:
            if not show_chapters and c["visible"]:
                continue
            pid = self.tree.insert("", "end", values=(c["name"], ""), tags=("chapter",))
            for t_row in self.db.list_terms_in_chapter(c["id"]):
                t = dict(t_row)
                iid = self.tree.insert(pid, "end", values=(t["de"], t["en"]), tags=("term",))
                self._term_item_map[iid] = t["id"]
                all_term_ids_in_chapters.add(t["id"])

        # Begriffe ohne Kapitel
        all_terms = [dict(t) for t in self.db.list_terms()]
        for t in all_terms:
            if t["id"] not in all_term_ids_in_chapters:
                kapitel_iid = self.tree.insert("", "end", values=("(ohne Kapitel)", ""), tags=("chapter",))
                iid = self.tree.insert(kapitel_iid, "end", values=(t["de"], t["en"]), tags=("term",))
                self._term_item_map[iid] = t["id"]

        # Treeview-Tags konfigurieren
        self.tree.tag_configure("chapter", font=("Segoe UI", 10, "bold"), background="#d9d9d9")
        self.tree.tag_configure("term", font=("Segoe UI", 10), background="#ffffff")

        self.clear_detail_fields()

    def on_search(self):
        q = self.q_var.get().strip()

        if not q:
            self.load_all_terms_grouped()
            return
        try:
            rows = self.db.search(q)
        except Exception as e:
            messagebox.showerror("Suche Fehler", str(e))
            return
        self._clear_tree()

        # Gruppiere Ergebnis nach sichtbaren Kapiteln
        chapters = self.db.list_chapters(only_visible=True)
        parent_by_chap = {}
        for c in chapters:
            text = f"{c['name']} | {c['name_en'] or ''}"
            parent_by_chap[c["id"]] = self.tree.insert("", "end", text=text, open=True, tags=("chapter",))
        # Extra-Gruppe für ohne/unsichtbare Kapitel
        no_grp = self.tree.insert("", "end", text="(ohne Kapitel)", open=True, tags=("chapter",))

        placed = set()  # (term_id, parent_pid) um Duplikate in der gleichen Gruppe zu verhindern
        for r in rows:
            term_id = r["id"]
            # Kapitel dieses Begriffs
            term_chaps = [c for c in self.db.list_chapters_for_term(term_id) if c["visible"]]
            if not term_chaps:
                if (term_id, no_grp) not in placed:
                    iid = self.tree.insert(no_grp, "end", text="", values=(r["de"], r["en"]), tags=("term",))
                    self._term_item_map[iid] = term_id
                    placed.add((term_id, no_grp))
            else:
                for c in term_chaps:
                    parent = parent_by_chap.get(c["id"], no_grp)
                    if (term_id, parent) in placed:
                        continue
                iid = self.tree.insert(parent, "end", text="", values=(r["de"], r["en"]), tags=("term",))
                self._term_item_map[iid] = term_id
                placed.add((term_id, parent))

        self.clear_detail_fields()

    def on_reset(self):
        self.q_var.set("")
        self.load_all_terms_grouped()

    def on_tree_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        # Nur Kind-Elemente (Begriffe) reagieren
        term_id = self._term_item_map.get(iid)
        if term_id:
            self.show_term_details(term_id)


    # ----- User-Anzeige ----------------------------------------------------------------------------------------
    from typing import Any, Mapping

    def _row_to_dict(self, row: Any) -> dict:
        """Versucht ein sqlite3.Row oder Mapping in ein dict umzuwandeln."""
        try:
            return dict(row)
        except Exception:
            if isinstance(row, dict):
                return row
        return {}

    def show_term_details(self, term_id):
        """Lädt Detaildaten eines Begriffs in die UI (User-Seite)."""
        row = self.db.get_term_by_id(term_id)
        if not row:
            self.clear_detail_fields()
            return

        term = self._row_to_dict(row)
        self.current_term_id = term_id

        # --- Deutsch (einzeiliges Feld) ---
        try:
            if hasattr(self, "lbl_de") and isinstance(self.lbl_de, ctk.CTkEntry):
                self.lbl_de.configure(state="normal")
                self.lbl_de.delete(0, tk.END)
                self.lbl_de.insert(0, term.get("de", "") or "")
                self.lbl_de.configure(state="disabled")
            else:
                # Defensive: falls doch Textbox
                self.lbl_de.configure(state="normal")
                self.lbl_de.delete("1.0", tk.END)
                self.lbl_de.insert("1.0", term.get("de", "") or "")
                self.lbl_de.configure(state="disabled")
        except Exception as e:
            print("Warnung lbl_de:", e)

        # --- Deutsch Beschreibung ---
        try:
            self.txt_de_desc.configure(state="normal")
            self.txt_de_desc.delete("1.0", tk.END)
            if term.get("de_desc"):
                self.txt_de_desc.insert("1.0", term.get("de_desc", ""))
            self.txt_de_desc.configure(state="disabled")
        except Exception as e:
            print("Warnung txt_de_desc:", e)

        # --- Englisch (einzeilig) ---
        try:
            if hasattr(self, "lbl_en") and isinstance(self.lbl_en, ctk.CTkEntry):
                self.lbl_en.configure(state="normal")
                self.lbl_en.delete(0, tk.END)
                self.lbl_en.insert(0, term.get("en", "") or "")
                self.lbl_en.configure(state="disabled")
            else:
                self.lbl_en.configure(state="normal")
                self.lbl_en.delete("1.0", tk.END)
                self.lbl_en.insert("1.0", term.get("en", "") or "")
                self.lbl_en.configure(state="disabled")
        except Exception as e:
            print("Warnung lbl_en:", e)

        # --- Englisch Beschreibung ---
        try:
            self.txt_en_desc.configure(state="normal")
            self.txt_en_desc.delete("1.0", tk.END)
            if term.get("en_desc"):
                self.txt_en_desc.insert("1.0", term.get("en_desc", ""))
            self.txt_en_desc.configure(state="disabled")
        except Exception as e:
            print("Warnung txt_en_desc:", e)

        # --- Kapitel (DB liefert sqlite3.Row; daher vorher in dict umwandeln) ---
        try:
            chapters = self.db.list_chapters_for_term(term_id) or []
            chap_names = []
            for c in chapters:
                cd = self._row_to_dict(c)
                name = cd.get("name", "") or ""
                name_en = cd.get("name_en", "") or ""
                if name_en:
                    chap_names.append(f"{name} | {name_en}")
                else:
                    chap_names.append(name)
            self.chapter_label.configure(text=", ".join(chap_names) if chap_names else "(keine Kapitel)")
        except Exception as e:
            print("Warnung Kapitel:", e)
            try:
                self.chapter_label.configure(text="(Fehler beim Laden der Kapitel)")
            except Exception:
                pass

        # --- Bild anzeigen (sichere Methode, konvertiert image bytes) ---
        try:
            self.show_image(self.img_label, term.get("image"))
        except Exception as e:
            print("Warnung show_image:", e)
            try:
                self.img_label.configure(image=None, text="(kein Bild)")
            except Exception:
                pass

        # --- Synonyme ---
        try:
            # Prüfen, ob das Widget existiert (User-Tab hat es evtl. nicht)
            if getattr(self, "edit_syn_list", None):
                self.edit_syn_list.configure(state="normal")
                self.edit_syn_list.delete("1.0", tk.END)

                synonyms = self.db.list_synonyms(term_id) or []
                if not synonyms:
                    self.edit_syn_list.insert("end", "(keine Synonyme)\n")
                else:
                    for s in synonyms:
                        # s ist bereits ein dict
                        tag = "✓" if int(s.get("allowed", 0)) else "✗"
                        lang = s.get("lang", "") or ""
                        syn = s.get("synonym", "") or ""
                        self.edit_syn_list.insert("end", f"{tag}  [{lang}] {syn}\n")

                self.edit_syn_list.configure(state="disabled")
        except Exception as e:
            print("Warnung Synonyme:", e)

        # --- Anmerkungen ---
        try:
            self.note_text.configure(state="normal")
            self.note_text.delete("1.0", tk.END)
            notes = self.db.get_annotation(term_id) or []
            if not notes:
                self.note_text.insert("end", "(keine Anmerkungen)\n")
            else:
                for n in notes:
                    tag = "✓" if int(n.get("allowed", 0)) else "✗"
                    lang = n.get("lang", "?")
                    text = n.get("note", "")
                    self.note_text.insert("end", f"{tag} [{lang}] {text}\n")
            self.note_text.configure(state="disabled")
        except Exception as e:
            print("Warnung Anmerkungen:", e)
            try:
                self.note_text.configure(state="disabled")
            except Exception:
                pass
#Suchen seite
        self.show_image(self.img_label, term.get("image"))

        # ---Suchen Seite

    from PIL import Image
    import customtkinter as ctk

    def get_dummy_image(size=(100, 100)):
        """Erstellt ein graues Dummy-Bild, das immer angezeigt wird."""
        img = Image.new("RGBA", size, (200, 200, 200, 255))  # hellgrau
        return ctk.CTkImage(light_image=img, dark_image=img, size=size)

    from typing import Optional
    import tkinter as tk
    import customtkinter as ctk

    def show_image(self, label: ctk.CTkLabel, image_bytes: Optional[bytes],
                   max_size: tuple[int, int] = (250, 250)) -> None:
        """Zeigt ein Bild oder Dummy in einem CTkLabel an."""
        import io
        from PIL import Image
        try:
            # Alte Referenz entfernen
            if hasattr(label, "image_ref"):
                label.image_ref = None

            if image_bytes:
                img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
                w, h = img.size
                ratio = min(max_size[0] / w, max_size[1] / h, 1.0)
                img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(int(w * ratio), int(h * ratio)))
                label.configure(text="", image=ctk_img)
                label.image_ref = ctk_img
            else:
                # Kein Bild -> Dummy verwenden
                label.configure(image=self._dummy_img, text="")
                label.image_ref = self._dummy_img
        except Exception as e:
            print("Fehler beim Laden des Bildes:", e)
            try:
                label.configure(image=self._dummy_img, text="")
                label.image_ref = self._dummy_img
            except Exception:
                pass

    def clear_detail_fields(self):
        """Leert alle Felder im Detailbereich (User-Seite)."""

        def clear_widget(widget):
            """Hilfsfunktion zum Leeren eines Widgets, egal ob Entry oder Text."""
            try:
                widget.configure(state="normal")
                if isinstance(widget, ctk.CTkEntry):
                    widget.delete(0, tk.END)
                else:
                    widget.delete("1.0", tk.END)
                widget.configure(state="disabled")
            except Exception:
                pass  # Ignoriere Fehler, falls Widget nicht existiert oder zerstört wurde

        # Nur wenn die Widgets schon existieren
        if hasattr(self, "lbl_de"): clear_widget(self.lbl_de)
        if hasattr(self, "txt_de_desc"): clear_widget(self.txt_de_desc)
        if hasattr(self, "lbl_en"): clear_widget(self.lbl_en)
        if hasattr(self, "txt_en_desc"): clear_widget(self.txt_en_desc)
        if hasattr(self, "syn_list"): clear_widget(self.edit_syn_list)
        if hasattr(self, "note_text"): clear_widget(self.note_text)

        # Bild entfernen
        if hasattr(self, "img_label"):
            try:
                self._current_img = None
                if hasattr(self.img_label, "image_ref"):
                    self.img_label.image_ref = None
                self.img_label.configure(image=None, text="(kein Bild)")
            except tk.TclError as e:
                if "doesn't exist" not in str(e):
                    raise

        # Kapitel entfernen
        if hasattr(self, "chapter_label"):
            try:
                self.chapter_label.configure(text="")
            except tk.TclError:
                pass


    # ---------- Admin Seite ----------
    def _build_edit_tab(self, parent):
        outer = ctk.CTkFrame(parent, fg_color=FIRMEN_SCHWARZ)
        outer.pack(fill="both", expand=True, padx=8, pady=8)

        # --- Links: Treeview + Filter + Buttons ---
        left = ctk.CTkFrame(outer, fg_color=FIRMEN_SCHWARZ)
        left.pack(side="left", fill="y", padx=(0, 6), pady=4)

        # Filter
        ctk.CTkLabel(left, text="Filter:", text_color=AKZENT_NEON).pack(anchor="w", padx=4, pady=(4, 0))
        self.filter_var = tk.StringVar()
        filter_entry = ctk.CTkEntry(left, textvariable=self.filter_var, fg_color=FIRMEN_GRAU, text_color="white")
        filter_entry.pack(fill="x", padx=4, pady=(0, 6))
        filter_entry.bind("<KeyRelease>", lambda e: self.reload_terms())

        # Treeview Begriffsliste
        cols = ("de", "en")
        self.term_tree = ttk.Treeview(left, columns=cols, show="tree headings", selectmode="browse")
        self.term_tree.heading("#0", text=" ")
        self.term_tree.column("#0", width=0, anchor="w")
        self.term_tree.heading("de", text="Deutsch")
        self.term_tree.heading("en", text="Englisch")
        self.term_tree.column("de", width=180, anchor="w")
        self.term_tree.column("en", width=180, anchor="w")
        self.term_tree.pack(fill="both", expand=True, padx=4, pady=6)
        self.term_tree.bind("<<TreeviewSelect>>", self.on_edit_tree_select)
        self.term_tree.bind("<Button-3>", self.on_term_right_click)
        self.term_tree.bind("<Control-Button-1>", self.on_term_right_click)

        vs = ttk.Scrollbar(left, orient="vertical", command=self.term_tree.yview)
        vs.pack(side=tk.RIGHT, fill=tk.Y)
        self.term_tree.configure(yscrollcommand=vs.set)

        # Buttons
        btnbar = ctk.CTkFrame(left, fg_color=FIRMEN_SCHWARZ)
        btnbar.pack(fill="x", pady=(4, 6), padx=4)
        ctk.CTkButton(btnbar, text="Neu", command=self.edit_new).pack(side="left")
        ctk.CTkButton(btnbar, text="Speichern", command=self.edit_save).pack(side="left", padx=6)
        ctk.CTkButton(btnbar, text="Löschen", command=self.edit_delete).pack(side="left")

        # Kapitelverwaltung (Admin)
        if self.role == "admin":
            chap_frame = ctk.CTkFrame(left, fg_color=FIRMEN_SCHWARZ)
            chap_frame.pack(fill="x", padx=4, pady=6)
            ctk.CTkLabel(chap_frame, text="Kapitelverwaltung", text_color=AKZENT_NEON,
                         font=("Segoe UI", 12, "bold")).pack(anchor="w")
            ctk.CTkButton(chap_frame, text="Kapitel hinzufügen", command=self.add_chapter_gui).pack(side="left", pady=4)

            self.chap_listbox = tk.Listbox(left, selectmode=tk.MULTIPLE, bg=FIRMEN_GRAU, fg="white")
            self.chap_listbox.pack(fill="x", pady=4, padx=4)
            self._chap_listbox_map = {}
            self.reload_chap_listbox()
            self.chap_listbox.bind("<Button-3>", self.on_chapter_right_click)
            self.chap_listbox.bind("<Control-Button-1>", self.on_chapter_right_click)

        # --- Rechts: Editor-Felder ---
        right = ctk.CTkFrame(outer, fg_color=FIRMEN_SCHWARZ)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=4)

        # Deutsch
        de_frame = ctk.CTkFrame(right, fg_color=FIRMEN_SCHWARZ)
        de_frame.pack(fill="x", pady=(4, 8))
        ctk.CTkLabel(de_frame, text="Deutsch", font=("Segoe UI", 14, "bold"), text_color=AKZENT_NEON).pack(anchor="w")
        self.edit_de_var = tk.StringVar()
        self.edit_de_entry = ctk.CTkEntry(de_frame, textvariable=self.edit_de_var, fg_color=FIRMEN_GRAU,
                                          text_color="white")
        self.edit_de_entry.pack(fill="x", pady=(4, 8))

        ctk.CTkLabel(de_frame, text="Definition", font=("Segoe UI", 12, "bold"), text_color=AKZENT_NEON).pack(
            anchor="w")
        self.edit_de_desc = ctk.CTkTextbox(de_frame, height=6, wrap="word", fg_color=FIRMEN_GRAU, text_color="white")
        self.edit_de_desc.pack(fill="both", expand=True)

        # Englisch
        en_frame = ctk.CTkFrame(right, fg_color=FIRMEN_SCHWARZ)
        en_frame.pack(fill="x", pady=(4, 8))
        ctk.CTkLabel(en_frame, text="English", font=("Segoe UI", 14, "bold"), text_color=AKZENT_NEON).pack(anchor="w")
        self.edit_en_var = tk.StringVar()
        self.edit_en_entry = ctk.CTkEntry(en_frame, textvariable=self.edit_en_var, fg_color=FIRMEN_GRAU,
                                          text_color="white")
        self.edit_en_entry.pack(fill="x", pady=(4, 8))

        ctk.CTkLabel(en_frame, text="Definition", font=("Segoe UI", 12, "bold"), text_color=AKZENT_NEON).pack(
            anchor="w")
        self.edit_en_desc = ctk.CTkTextbox(en_frame, height=6, wrap="word", fg_color=FIRMEN_GRAU, text_color="white")
        self.edit_en_desc.pack(fill="both", expand=True)

        # Bildauswahl
        img_frame = ctk.CTkFrame(right, fg_color=FIRMEN_SCHWARZ)
        img_frame.pack(fill="x", pady=4)
        ctk.CTkButton(img_frame, text="Bild auswählen...", command=self.edit_pick_image).pack(side="left", padx=(0, 6))
        self.edit_img_path_var = tk.StringVar()
        ctk.CTkLabel(img_frame, textvariable=self.edit_img_path_var, text_color="white").pack(side="left")
        self.edit_preview = ctk.CTkLabel(right, text="(kein Bild)", fg_color=FIRMEN_GRAU, text_color="white")
        self.edit_preview.pack(fill="both", expand=False, pady=8)
        self._current_img_admin = None

        # Synonyme
        syn_frame = ctk.CTkFrame(right, fg_color=FIRMEN_SCHWARZ)
        syn_frame.pack(fill="both", expand=True, pady=(6, 0))
        ctk.CTkLabel(syn_frame, text="Synonyme für diesen Begriff", font=("Segoe UI", 12, "bold"),
                     text_color=AKZENT_NEON).pack(anchor="w", padx=6, pady=4)

        self.edit_syn_list = ctk.CTkTextbox(syn_frame, height=20, wrap="word", fg_color=FIRMEN_GRAU, text_color="white")
        self.edit_syn_list.pack(fill="both", expand=True, padx=6, pady=6)

        # Neue Synonyme oben
        syn_top = ctk.CTkFrame(syn_frame, fg_color=FIRMEN_SCHWARZ)
        syn_top.pack(fill="x", pady=6, padx=4)
        ctk.CTkLabel(syn_top, text="Sprache:", text_color="white").pack(side="left")
        self.edit_syn_lang = tk.StringVar(value="de")
        ctk.CTkComboBox(syn_top, variable=self.edit_syn_lang, values=["de", "en"], width=60).pack(side="left",
                                                                                                  padx=(4, 8))
        self.edit_syn_text = tk.StringVar()
        ctk.CTkEntry(syn_top, textvariable=self.edit_syn_text, fg_color=FIRMEN_GRAU, text_color="white").pack(
            side="left", fill="x", expand=True)
        self.edit_syn_allowed = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(syn_top, text="zugelassen", variable=self.edit_syn_allowed, text_color="white").pack(
            side="left", padx=(8, 6))
        ctk.CTkButton(syn_top, text="Hinzufügen", command=self.edit_add_synonym).pack(side="left")

        # Anmerkungen
        note_frame = ctk.CTkFrame(right, fg_color=FIRMEN_SCHWARZ)
        note_frame.pack(fill="both", expand=True, pady=(6, 0))
        ctk.CTkLabel(note_frame, text="Anmerkungen", font=("Segoe UI", 12, "bold"), text_color=AKZENT_NEON).pack(
            anchor="w", padx=6, pady=4)
        self.edit_note_text = ctk.CTkTextbox(note_frame, height=6, wrap="word", fg_color=FIRMEN_GRAU,
                                             text_color="white")
        self.edit_note_text.pack(fill="both", expand=True, padx=6, pady=6)
        ctk.CTkButton(note_frame, text="Anmerkungen speichern", command=self.save_annotations).pack(pady=6)

        # Interne Variablen
        self.edit_current_id = None
        self.reload_terms()



#Neue Ansicht
    def on_edit_tree_select(self, event=None):
        sel = self.term_tree.selection()
        if not sel:
            return
        iid = sel[0]
        term_id = self._admin_term_item_map.get(iid)
        if not term_id:
            print(f"Kein Begriff für iid={iid}, evtl. Kapitel oder Leerzeile")
            return
        self.edit_load_term(term_id)

    def reload_terms(self):
        """Treeview: alle Kapitel + Begriffe laden"""
        self.term_tree.delete(*self.term_tree.get_children())
        self._admin_term_item_map.clear()
        self._admin_chap_item_map.clear()

        chapters = self.db.list_chapters(only_visible=False)
        for c in chapters:
            pid = self.term_tree.insert("", "end", values=(c["name"], ""), tags=("chapter",))
            self._admin_chap_item_map[pid] = c["id"]
            for t in self.db.list_terms_in_chapter(c["id"]):
                iid = self.term_tree.insert(pid, "end", values=(t["de"], t["en"]), tags=("term",))
                self._admin_term_item_map[iid] = t["id"]

        # Begriffe ohne Kapitel
        all_term_ids = {t["id"] for t in self.db.list_terms()}
        in_any = {t["id"] for c in chapters for t in self.db.list_terms_in_chapter(c["id"])}
        for tid in sorted(all_term_ids - in_any):
            term = self.db.get_term_by_id(tid)
            pid = self.term_tree.insert("", "end", values=("(ohne Kapitel)", ""), tags=("chapter",))
            iid = self.term_tree.insert(pid, "end", values=(term["de"], term["en"]), tags=("term",))
            self._admin_term_item_map[iid] = tid

        self.term_tree.tag_configure("chapter", font=("Segoe UI", 10, "bold"), background="#d9d9d9")
        self.term_tree.tag_configure("term", font=("Segoe UI", 10), background="#ffffff")

    def reload_chap_listbox(self):
        if not hasattr(self, "chap_listbox"):
            return  # User-Seite hat keine Listbox, einfach zurück
        self.chap_listbox.delete(0, tk.END)
        self._chap_listbox_map = {}
        for c in self.db.list_chapters():
            self._chap_listbox_map[c["id"]] = c["name"]
            self.chap_listbox.insert(tk.END, c["name"])

    # Nur für Admin-Seite, alte Listbox-Version
    def reload_terms_admin(self):
        flt = self.filter_var.get().strip().lower()
        self.term_listbox.delete(0, tk.END)
        self._term_rows = self.db.list_terms()
        for r in self._term_rows:
            if not flt or flt in r["de"].lower() or flt in r["en"].lower():
                self.term_listbox.insert(tk.END, f"{r['de']} / {r['en']}")

    # Für User-Seite und ggf. Admin-Treeview
    def reload_terms_tree(self):
        self.load_all_terms_grouped(show_chapters=True)

#Ansicht für suchen udn Adminseite neu 12.09.25
    def search_load_term(self, term_id):
        """Lädt einen Begriff inkl. Definition, Synonyme, Anmerkungen und Bild."""
        term_row = self.db.get_term_by_id(term_id)
        if not term_row:
            # Leeren
            self.search_de_var.set("")
            self.txt_search_de_desc.delete("1.0", "end")
            self.search_en_var.set("")
            self.txt_search_en_desc.delete("1.0", "end")
            if hasattr(self, "txt_search_synonyms"):
                self.txt_search_synonyms.configure(state="normal")
                self.txt_search_synonyms.delete("1.0", "end")
                self.txt_search_synonyms.insert("end", "(Keine Synonyme vorhanden)\n")
                self.txt_search_synonyms.configure(state="disabled")
            if hasattr(self, "txt_search_note"):
                self.txt_search_note.configure(state="normal")
                self.txt_search_note.delete("1.0", "end")
                self.txt_search_note.configure(state="disabled")
            if hasattr(self, "search_img_label"):
                self.search_img_label.configure(image=None, text="(kein Bild)")
                self.search_img_label.image_ref = None
            return

        term = dict(term_row)

        # --- Texte ---
        self.search_de_var.set(term.get("de", ""))
        self.txt_search_de_desc.delete("1.0", "end")
        self.txt_search_de_desc.insert("1.0", term.get("de_desc", ""))
        self.search_en_var.set(term.get("en", ""))
        self.txt_search_en_desc.delete("1.0", "end")
        self.txt_search_en_desc.insert("1.0", term.get("en_desc", ""))

        # --- Synonyme ---
        syn_widget = getattr(self, "txt_search_synonyms", None)
        if syn_widget:
            try:
                syn_widget.configure(state="normal")
                syn_widget.delete("1.0", "end")

                synonyms = self.db.list_synonyms(term_id) or []
                if not synonyms:
                    syn_widget.insert("end", "(Keine Synonyme vorhanden)\n")
                else:
                    for s in synonyms:
                        tag = "✓" if int(s.get("allowed", 0)) else "✗"
                        lang = s.get("lang", "?") or "?"
                        syn_text = s.get("synonym", "") or ""
                        syn_widget.insert("end", f"{tag} [{lang}] {syn_text}\n")

                syn_widget.configure(state="disabled")
            except Exception as e:
                print("Warnung Synonyme:", e)

        # --- Anmerkungen ---
        if hasattr(self, "txt_search_note"):
            note = self.db.get_annotation(term_id)
            self.txt_search_note.configure(state="normal")
            self.txt_search_note.delete("1.0", "end")
            if note:
                self.txt_search_note.insert("1.0", note.strip())
            self.txt_search_note.configure(state="disabled")

        # --- Bild ---
        if hasattr(self, "search_img_label"):
            self._set_ctk_image(self.search_img_label, term.get("image"))

    def _set_ctk_image(self, label_widget, img_bytes):
        """Setzt ein CTkImage auf ein Label. Dummy, falls kein Bild."""
        from PIL import Image
        if img_bytes:
            try:
                import io
                img = Image.open(io.BytesIO(img_bytes))
                MAX_W, MAX_H = IMG_MAX_W, IMG_MAX_H
                w, h = img.size
                ratio = min(MAX_W / w, MAX_H / h, 1.0)
                new_w, new_h = int(w * ratio), int(h * ratio)
                img = img.resize((new_w, new_h), Image.LANCZOS)
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(new_w, new_h))
                label_widget.configure(image=ctk_img, text="")
                label_widget.image_ref = ctk_img
            except Exception as e:
                print("Fehler beim Laden des Bildes:", e)
                empty_img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
                dummy_ctk = ctk.CTkImage(light_image=empty_img, dark_image=empty_img, size=(1, 1))
                label_widget.configure(image=dummy_ctk, text="(kein Bild)")
                label_widget.image_ref = dummy_ctk
        else:
            empty_img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
            dummy_ctk = ctk.CTkImage(light_image=empty_img, dark_image=empty_img, size=(1, 1))
            label_widget.configure(image=dummy_ctk, text="(kein Bild)")
            label_widget.image_ref = dummy_ctk

    def on_search_tree_select(self, event):
        sel = self.tree.selection()
        if sel:
            term_id = self._term_item_map.get(sel[0])
            if term_id:
                self.search_load_term(term_id)

    #Ansicht Admin Adminseite
    def edit_load_term(self, term_id: int):
        """Lädt einen Begriff in die Admin-Bearbeitung."""
        try:
            term = self.db.get_term(term_id)
            if not term:
                print(f"Kein Begriff für iid={term_id}, evtl. Kapitel oder Leerzeile")
                return

            self.edit_current_id = term_id

            # Begriffe
            self.edit_de_var.set(term.get("de", ""))
            self.edit_en_var.set(term.get("en", ""))

            # --- Beschreibung Deutsch ---
            if getattr(self, "edit_de_desc", None):
                try:
                    self.edit_de_desc.configure(state="normal")
                    self.edit_de_desc.delete("1.0", tk.END)
                    self.edit_de_desc.insert("1.0", term.get("de_desc") or "")
                except Exception as e:
                    print("Warnung beim Setzen von edit_de_desc:", e)

            # --- Beschreibung Englisch ---
            if getattr(self, "edit_en_desc", None):
                try:
                    self.edit_en_desc.configure(state="normal")
                    self.edit_en_desc.delete("1.0", tk.END)
                    self.edit_en_desc.insert("1.0", term.get("en_desc") or "")
                except Exception as e:
                    print("Warnung beim Setzen von edit_en_desc:", e)

            # --- Bild ---
            image_bytes = term.get("image")
            if image_bytes:
                self.show_image_from_bytes(image_bytes)
                self._current_img_bytes = image_bytes
            else:
                self.edit_preview.configure(text="(kein Bild)", image=None)
                self._current_img_bytes = None

            # Synonyme laden
            if hasattr(self, "edit_syn_list"):
                self.load_synonyms(term_id)

            # --- Anmerkungen ---
            if getattr(self, "edit_note_text", None):
                self.load_annotations(term_id)

        except Exception as e:
            print(f"Fehler beim Laden des Begriffs {term_id}: {e}")

    # --- Synonyme laden ---
    def init_synonym_widgets(self):
        """Initialisiert die Synonym-Widgets für Admin und User."""
        # Admin-Widget (edit_tab)
        if self.role == "admin":
            self.edit_syn_list = ctk.CTkTextbox(self.edit_tab, width=300, height=150)
            self.edit_syn_list.pack(fill="both", expand=True, padx=10, pady=10)
            self.edit_syn_list.configure(font=("Segoe UI Symbol", 12))

        # User-Widget (search_tab)
        self.txt_search_synonyms = ctk.CTkTextbox(self.search_tab, width=300, height=150)
        self.txt_search_synonyms.pack(fill="both", expand=True, padx=10, pady=10)
        self.txt_search_synonyms.configure(font=("Segoe UI Symbol", 12), state="disabled")

    def load_synonyms(self, term_id):
        """Zeigt Synonyme für Term im passenden Feld (User / Admin) an."""

        # Admin-Feld (bearbeitbar)
        if self.role == "admin" and hasattr(self, "edit_syn_list"):
            box = self.edit_syn_list
            box.configure(state="normal")
        # User-Feld (nur anzeigen)
        elif hasattr(self, "synonym_field"):
            box = self.synonym_field
            box.configure(state="normal")
        else:
            return  # kein Feld vorhanden

        # Inhalt leeren
        box.delete("1.0", "end")

        syns = self.db.list_synonyms(term_id)

        if syns:
            for syn in syns:
                status = "✅" if syn["allowed"] else "🚫"
                box.insert("end", f"{status} {syn['lang']}: {syn['synonym']}\n")
        else:
            box.insert("end", "(Keine Synonyme)")

        # User-Feld wieder sperren
        if box is self.synonym_field or self.role != "admin":
            box.configure(state="disabled")

    # --- Synonym hinzufügen (Button) ---
    def edit_add_synonym(self):
        """Fügt ein neues Synonym hinzu (Admin)."""
        if not self.edit_current_id:
            messagebox.showwarning("Kein Begriff", "Bitte zuerst einen Begriff auswählen.")
            return

        term_id = self.edit_current_id
        lang = self.edit_syn_lang.get().strip()
        synonym = self.edit_syn_text.get().strip()
        allowed = self.edit_syn_allowed.get()

        if not synonym:
            messagebox.showwarning("Leeres Synonym", "Bitte ein Synonym eingeben.")
            return

        # Prüfen, ob Synonym schon existiert
        if self.db.synonym_exists(term_id, lang, synonym):
            messagebox.showwarning("Synonym existiert", f"'{synonym}' existiert bereits für diese Sprache!")
            return

        # Synonym einfügen
        self.db.add_synonym(term_id, lang, synonym, allowed)

        # UI aktualisieren
        self.edit_syn_text.set("")
        self.edit_syn_allowed.set(True)
        self.load_synonyms(term_id)

    # --- Alle Synonyme speichern ---
    def save_synonyms(self):
        """Speichert alle Synonyme aus dem Admin-Widget zurück in die DB."""
        if not hasattr(self, "edit_syn_list") or not self.edit_syn_list:
            return

        term_id = self.edit_current_id
        if not term_id:
            return

        text_content = self.edit_syn_list.get("1.0", tk.END).strip()
        lines = text_content.splitlines()

        # Alte Synonyme löschen
        self.db.delete_synonyms_for_term(term_id)

        # Neue eintragen
        for line in lines:
            if not line.strip() or line.startswith("("):
                continue
            try:
                tag = line[0] == "✓"
                lang = line[line.find("[") + 1:line.find("]")]
                syn = line.split("]", 1)[1].strip()
                self.db.add_synonym(term_id, lang, syn, allowed=tag)
            except Exception as e:
                print("Fehler beim Parsen der Zeile:", line, e)

        messagebox.showinfo("Synonyme gespeichert", "Alle Synonyme wurden erfolgreich gespeichert.")
        self.load_synonyms(term_id)



    # --- Anmerkungen laden ---
    def load_annotations(self, term_id: int):
        """Lädt die Anmerkungen in die CTkTextbox."""
        if not getattr(self, "edit_note_text", None):
            return

        try:
            # Admin darf schreiben -> state normal lassen
            self.edit_note_text.configure(state="normal")
            self.edit_note_text.delete("1.0", tk.END)

            notes = self.db.list_annotations(term_id)
            if not notes:
                self.edit_note_text.insert(tk.END, "(keine Anmerkungen)")
            else:
                for n in notes:
                    self.edit_note_text.insert(tk.END, f"{n['lang']}: {n['note']}\n")

        except Exception as e:
            print(f"Fehler beim Laden der Anmerkungen: {e}")

    def edit_new(self) -> object:
        if hasattr(self, "edit_syn_list") and self.edit_syn_list is not None:
            self.edit_syn_list.configure(state="normal")
            self.edit_syn_list.delete("1.0", "end")
            self.edit_syn_list.configure(state="disabled")


        self.edit_current_id = None
        self.edit_de_entry.delete(0, tk.END)
        self.edit_en_entry.delete(0, tk.END)
        self.edit_de_desc.delete("1.0", tk.END)
        self.edit_en_desc.delete("1.0", tk.END)
        self.edit_note_text.delete("1.0", tk.END)
        self.edit_syn_list.delete("1.0", tk.END)

        # Dummy-Bild setzen
        self._set_ctk_image(self.edit_preview, None)

        self.edit_chapter_label.configure(text="(noch nicht gespeichert)")

        self.edit_de_var.set("")
        self.edit_en_var.set("")
        self.edit_de_var.set("")
        self.edit_en_var.set("")
        self.txt_de_desc.delete("1.0", "end")
        self.txt_en_desc.delete("1.0", "end")
        self.edit_img_path_var.set("")
        self.edit_preview.configure(image=None, text="(kein Bild)")
        self.edit_preview.image = None
        self.edit_syn_list.delete(0, tk.END)
        self.chap_listbox.delete(0, tk.END)
        self.edit_note_text.delete("1.0", tk.END)
        # Kapitel-Liste neu füllen
        for c in self.db.list_chapters():
            self.chap_listbox.insert(tk.END, f"{c['name']} | {c['name_en'] or ''}")

    def edit_pick_image(self):
        from tkinter import filedialog
        try:
            file_path = filedialog.askopenfilename(filetypes=[("Bilder", "*.png;*.jpg;*.jpeg;*.gif")])
            if not file_path:
                return

            import io
            from PIL import Image
            img = Image.open(file_path)
            img = img.resize((220, 220))
            ph = ctk.CTkImage(light_image=img, dark_image=img, size=(220, 220))

            self.edit_preview.configure(image=ph, text="")
            self._current_img_admin = ph

            # Bild-Bytes für das spätere Speichern vorbereiten
            with open(file_path, "rb") as f:
                self._current_img_bytes = f.read()
            self.edit_img_path_var.set(file_path)

        except Exception as e:
            self.edit_preview.configure(image=None, text="(Bild konnte nicht geladen werden)")
            self._current_img_bytes = None
            print(f"Fehler beim Laden des Bildes: {e}")

    # --- Begriff speichern ---
    def edit_save(self):
        if not self.edit_current_id:
            print("Kein Begriff ausgewählt!")
            return

        try:
            image_bytes = getattr(self, "_current_img_bytes", None)
            self.db.update_term(
                term_id=self.edit_current_id,
                de=self.edit_de_var.get().strip(),
                en=self.edit_en_var.get().strip(),
                de_desc=self.edit_de_desc.get("1.0", "end").strip(),
                en_desc=self.edit_en_desc.get("1.0", "end").strip(),
                image_bytes=image_bytes
            )

            # Synonyme speichern (falls du edit_add_synonym implementiert hast)
            self.save_synonyms(self.edit_current_id)

            # Anmerkungen speichern
            self.save_annotations()

            print(f"Begriff {self.edit_current_id} gespeichert: {self.edit_de_var.get()} / {self.edit_en_var.get()}")

            # Treeview aktualisieren
            self.reload_terms()

        except Exception as e:
            print(f"Fehler beim Speichern des Begriffs: {e}")

    def edit_delete(self):
        """Ausgewählten Begriff löschen."""
        if not self.edit_current_id:
            return

        if messagebox.askyesno("Löschen", "Begriff wirklich löschen?"):
            try:
                with self.db.conn:
                    self.db.conn.execute("DELETE FROM terms WHERE id=?", (self.edit_current_id,))
                messagebox.showinfo("Gelöscht", "Begriff erfolgreich gelöscht.")
                self.edit_new()
                self.load_all_terms_grouped()
            except Exception as e:
                messagebox.showerror("Fehler", str(e))

    def edit_refresh_synonyms(self):
        """Lädt die Synonyme eines Begriffs ins Admin-Textfeld."""
        if not getattr(self, "edit_syn_list", None):
            print("⚠️ Kein Synonym-Widget definiert.")
            return
        self.edit_syn_list.configure(state="normal")
        self.edit_syn_list.delete("1.0", tk.END)

        if not self.edit_current_id:
            self.edit_syn_list.insert("1.0", "(Kein Begriff ausgewählt)\n")
            self.edit_syn_list.configure(state="disabled")
            return

        synonyms = self.db.list_synonyms(self.edit_current_id)
        if not synonyms:
            self.edit_syn_list.insert("1.0", "(Keine Synonyme vorhanden)\n")
        else:
            for s in synonyms:
                tag = "✓" if s.get("allowed") else "✗"
                lang = s.get("lang", "?")
                syn = s.get("synonym", "")
                self.edit_syn_list.insert("end", f"{tag} [{lang}] {syn}\n")

        self.edit_syn_list.configure(state="disabled")

    def edit_save_synonyms(self):
        """Speichert die bearbeiteten Synonyme in der DB."""
        if not hasattr(self, "edit_syn_list") or self.edit_syn_list is None:
            return

        text = self.edit_syn_list.get("1.0", "end").strip()
        lines = text.splitlines()

        # Alte Synonyme löschen
        self.db.delete_synonyms_for_term(self.edit_current_id)

        # Neue eintragen
        for line in lines:
            if not line.strip() or line.startswith("("):
                continue
            # Erwartetes Format: "✓  [de] Synonym"
            try:
                tag = line[0] == "✓"
                lang = line[line.find("[") + 1:line.find("]")]
                syn = line.split("]", 1)[1].strip()
                self.db.add_synonym(self.edit_current_id, lang, syn, allowed=tag)
            except Exception as e:
                print("⚠️ Konnte Zeile nicht parsen:", line, e)

        print("✅ Synonyme gespeichert.")

    def _get_selected_edit_syn_id(self):
        sel = self.edit_syn_list.curselection()
        if not sel:
            return None
        idx = sel[0]
        if idx >= len(self._edit_syn_rows):
            return None
        return self._edit_syn_rows[idx]["id"]

    def edit_set_syn_allowed(self, allowed: bool):
        syn_id = self._get_selected_edit_syn_id()
        if not syn_id:
            return
        try:
            self.db.update_synonym_allowed(syn_id, allowed)
            self.edit_refresh_synonyms()
        except Exception as e:
            messagebox.showerror("Fehler", str(e))

    def edit_delete_selected_synonym(self):
        syn_id = self._get_selected_edit_syn_id()
        if not syn_id:
            return
        if not messagebox.askyesno("Synonym löschen", "Ausgewähltes Synonym wirklich löschen?"):
            return
        try:
            self.db.delete_synonym(syn_id)
            self.edit_refresh_synonyms()
        except Exception as e:
            messagebox.showerror("Fehler", str(e))

# --- Anmerkungen bearbeiten ---
    def edit_refresh_annotations(self):
        if self.edit_current_id:
            note_row = self.db.get_annotation(self.edit_current_id)
            self.edit_note_text.delete("1.0", tk.END)
            if note_row:
                note_text = note_row.get("note") if isinstance(note_row, dict) else str(note_row)
                self.edit_note_text.insert("1.0", note_text.strip())
        else:
            self.edit_note_text.delete("1.0", tk.END)

    def save_annotations(self):
        """Speichert die Anmerkung für den aktuellen Begriff (Deutsch und Englisch)."""
        if not self.edit_current_id:
            return

        content = self.edit_note_text.get("1.0", tk.END).strip()

        try:
            # Deutsch
            self.db.save_annotation(self.edit_current_id, content, lang="de", allowed=1)
            # Englisch (falls du separate Felder für en hast, sonst gleiche Inhalte)
            # content_en = self.txt_note_en.get("1.0", tk.END).strip()
            # self.db.save_annotation(self.edit_current_id, content_en, lang="en", allowed=1)

            # GUI sofort aktualisieren
            self.edit_refresh_annotations()
            messagebox.showinfo("Gespeichert", "Anmerkung wurde gespeichert.")
        except Exception as e:
            messagebox.showerror("Fehler", str(e))


        #'--- Popup für Kapitelzuweisung - --

    def show_assign_chapters(self, term_id):
        term = self.db.get_term_by_id(term_id)
        if not term:
            return

        popup = tk.Toplevel(self)
        popup.title(f"Kapitel für '{term['de']}' zuweisen")
        popup.geometry("300x400")

        # Kapitel laden und Checkboxen vorbereiten
        chapters = self.db.list_chapters()
        term_chaps = [c["id"] for c in self.db.list_chapters_for_term(term_id)]
        vars = []

        frame = ttk.Frame(popup)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        canvas = tk.Canvas(frame)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for c in chapters:
            var = tk.BooleanVar(value=c["id"] in term_chaps)
            chk = tk.Checkbutton(scrollable_frame, text=c["name"], variable=var)
            chk.pack(anchor="w", pady=2)
            vars.append((c["id"], var))

        def save():
            # alte Zuordnungen löschen
            for c in chapters:
                self.db.remove_term_from_chapter(term_id, c["id"])
            # neue speichern
            for chap_id, var in vars:
                if var.get():
                    self.db.assign_term_to_chapter(term_id, chap_id)
            popup.destroy()
           
            #Ansicht aktuallisieren
            self.reload_terms()  # Admin-Treeview
            self.load_all_terms_grouped()  # Suchen-Seite

            messagebox.showinfo("Gespeichert", "Kapitelzuordnung aktualisiert.")

        ttk.Button(popup, text="Speichern", command=save).pack(pady=6)

        #NEU
    # --- Kontextmenü für Begriffe ---
    def on_term_right_click(self, event):
        iid = self.term_tree.identify_row(event.y)
        if not iid:
            return

        # Selektion setzen, falls noch nicht markiert
        self.term_tree.selection_set(iid)

        # Prüfen ob Kapitel oder Begriff
        tags = self.term_tree.item(iid, "tags")
        if "chapter" in tags:
            self.show_chapter_context_menu(event, iid)
        elif "term" in tags:
            self.show_term_context_menu(event, iid)

    def show_term_context_menu(self, event, iid):
        term_id = self._admin_term_item_map.get(iid)
        if not term_id:
            return
        menu = tk.Menu(self, tearoff=0)
        # Bearbeiten entfernen, nur Löschen:
        menu.add_command(label="Begriff löschen", command=lambda: self.edit_delete_term_gui(term_id))
        menu.add_command(label="Kapitel zuweisen", command=lambda: self.show_assign_chapters(term_id))
        menu.post(event.x_root, event.y_root)

    def edit_delete_term_gui(self, term_id):
        if not term_id:
            return
        if not messagebox.askyesno("Löschen bestätigen", "Diesen Begriff inkl. Synonyme löschen?"):
            return
        try:
            self.db.delete_term(term_id)  # direkt DB löschen
            # Treeview und GUI neu laden
            self.edit_new()  # Felder leeren
            self.reload_terms()
            self.load_all_terms_grouped()
            messagebox.showinfo("Erfolg", "Begriff gelöscht.")
        except Exception as e:
            messagebox.showerror("Fehler", str(e))

    #Neu 04.09.25
    def delete_chapter(self, iid):
        chap_id = self._admin_chap_item_map.get(iid)
        if not chap_id:
            messagebox.showerror("Fehler", "Kapitel-ID nicht gefunden.")
            return

        chap_name = self.term_tree.item(iid, "values")[0]  # Name aus Treeview
        if messagebox.askyesno("Kapitel löschen", f"Soll Kapitel '{chap_name}' wirklich gelöscht werden?"):
            self.db.delete_chapter(chap_id)
            self.reload_terms()  # Treeview neu laden
            self.reload_chap_listbox()  # Listbox neu laden
            messagebox.showinfo("Erfolg", f"Kapitel '{chap_name}' gelöscht.")

    def show_image_from_bytes(self, image_bytes: bytes | None):
        """Zeigt das Bild im Admin-Tab an (oder Text, wenn None). Robust: Referenzen halten."""
        try:
            if not getattr(self, "edit_preview", None):
                return

            if not image_bytes:
                # Dummy / kein Bild
                try:
                    self.edit_preview.configure(image=None, text="(kein Bild)")
                except Exception:
                    pass
                self._current_img_admin = None
                if hasattr(self.edit_preview, "image_ref"):
                    self.edit_preview.image_ref = None
                return

            import io
            from PIL import Image

            img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
            img = img.resize((220, 220), Image.LANCZOS)

            # CTkImage erzeugen und als Attribut speichern, damit GC es nicht löscht
            self._current_img_admin = ctk.CTkImage(light_image=img, dark_image=img, size=(220, 220))
            self.edit_preview.configure(image=self._current_img_admin, text="")
            # zusätzliche Referenz direkt am Widget
            self.edit_preview.image_ref = self._current_img_admin

        except Exception as e:
            print(f"Fehler beim Anzeigen des Bildes: {e}")
            try:
                self.edit_preview.configure(image=None, text="(kein Bild)")
                self._current_img_admin = None
                if hasattr(self.edit_preview, "image_ref"):
                    self.edit_preview.image_ref = None
            except Exception:
                pass

# ---------------- App Start ----------------
def init_db():
    DB(Path(DB_NAME))


def run_app(role="user"):
    root = tk.Tk()
    app = TerminologyApp(root, role=role)
    root.mainloop()


def login_screen():
    def center(win):
        win.update_idletasks()
        w = win.winfo_width()
        h = win.winfo_height()
        ws = win.winfo_screenwidth()
        hs = win.winfo_screenheight()
        x = (ws // 2) - (w // 2)
        y = (hs // 2) - (h // 2)
        win.geometry(f'{w}x{h}+{x}+{y}')

    def login_as_user():
        login.destroy()
        run_app("user")

    def login_as_admin():
        def check_password():
            if pw_entry.get() == ADMIN_PASSWORD:
                pw_win.destroy()
                login.destroy()
                run_app("admin")
            else:
                messagebox.showerror("Fehler", "Falsches Passwort!")

        pw_win = tk.Toplevel(login)
        pw_win.title("Admin Login")
        ttk.Label(pw_win, text="Passwort:").pack(pady=8, padx=12)
        pw_entry = ttk.Entry(pw_win, show="*")
        pw_entry.pack(pady=6, padx=12)
        ttk.Button(pw_win, text="Login", command=check_password).pack(pady=8)
        pw_win.grab_set()
        center(pw_win)

    login = tk.Tk()
    login.title("Anmeldung")
    login.geometry("360x180")
    login.resizable(False, False)
    ttk.Label(login, text=" ", font=("Segoe UI", 11, "bold")).pack(pady=(18,8))
    ttk.Button(login, text="User (nur Suche)", command=login_as_user, width=20).pack(pady=6)
    ttk.Button(login, text="Admin (Bearbeitung)", command=login_as_admin, width=20).pack(pady=6)
    center(login)
    login.mainloop()


if __name__ == "__main__":
    try:
        init_db()
        login_screen()
    except Exception:
        traceback.print_exc()
        messagebox.showerror("Unerwarteter Fehler", traceback.format_exc())


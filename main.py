"""
main.py
=======

Point d'entrée de Kblo. Interface Tkinter minimaliste avec drag-drop
(via ``tkinterdnd2``), barre de progression non-bloquante, fenêtre de
préférences pour configurer le domaine Jira, et boîte de dialogue de
sauvegarde du fichier ``.excalidraw`` généré.

Exécution ::

    python main.py
"""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except ImportError:  # pragma: no cover - dépend de l'install
    _HAS_DND = False

from config_manager import (
    CONFIG_PATH,
    load_config,
    normalize_domain,
    save_config,
)
from csv_parser import parse_jira_csv
from excalidraw_generator import generate_excalidraw, write_excalidraw
from graph_builder import build_graph
from layout_engine import compute_layout
from validators import (
    KbloValidationError,
    ensure_jira_domain,
    validate_csv_file,
    validate_jira_domain,
)


# ---------------------------------------------------------------------------
# Constantes UI
# ---------------------------------------------------------------------------

WINDOW_W = 540
WINDOW_H = 380
DROP_ZONE_H = 200
MAX_RECOMMENDED_TICKETS = 50

COLOR_BG = "#fafafa"
COLOR_DROP = "#ffffff"
COLOR_DROP_HOVER = "#e8f0ff"
COLOR_DROP_BORDER = "#9aa0a6"
COLOR_TEXT = "#202124"
COLOR_WARN = "#b26a00"
COLOR_OK = "#188038"
COLOR_ERR = "#c5221f"


# ---------------------------------------------------------------------------
# Worker: traitement complet en thread
# ---------------------------------------------------------------------------

class ProcessingWorker(threading.Thread):
    """Enchaine les étapes de traitement dans un thread séparé.

    Communique avec l'UI via une :class:`queue.Queue` — on ne touche
    jamais à Tkinter depuis le thread, c'est le thread UI qui dépile
    les messages via ``root.after``.
    """

    def __init__(
        self,
        csv_path: Path,
        jira_domain: str,
        outbox: queue.Queue,
        confirm_large: Callable[[int], bool],
    ) -> None:
        super().__init__(daemon=True)
        self.csv_path = csv_path
        self.jira_domain = jira_domain
        self.outbox = outbox
        self.confirm_large = confirm_large

    # ----- Helpers de messagerie -----
    def _progress(self, value: int, label: str) -> None:
        self.outbox.put(("progress", value, label))

    def _warn(self, msg: str) -> None:
        self.outbox.put(("warn", msg))

    def _done(self, document: dict, suggested_name: str) -> None:
        self.outbox.put(("done", document, suggested_name))

    def _error(self, msg: str) -> None:
        self.outbox.put(("error", msg))

    # ----- Thread body -----
    def run(self) -> None:
        try:
            self._progress(5, "Validation du CSV…")
            encoding = validate_csv_file(self.csv_path)

            self._progress(15, "Validation du domaine Jira…")
            ensure_jira_domain(self.jira_domain)

            self._progress(25, "Lecture du CSV…")
            report = parse_jira_csv(self.csv_path, encoding=encoding)
            for w in report.warnings:
                self._warn(w)

            if len(report.tickets) > MAX_RECOMMENDED_TICKETS:
                if not self.confirm_large(len(report.tickets)):
                    self.outbox.put(("cancelled",))
                    return

            self._progress(45, "Construction du graphe…")
            graph = build_graph(report.tickets)
            for w in graph.warnings:
                self._warn(w)

            self._progress(65, "Calcul du layout…")
            layout = compute_layout(graph)

            self._progress(85, "Génération du fichier Excalidraw…")
            document = generate_excalidraw(graph, layout, self.jira_domain)

            self._progress(100, "Terminé.")
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._done(document, f"jira_diagram_{stamp}.excalidraw")
        except KbloValidationError as exc:
            self._error(str(exc))
        except Exception as exc:  # noqa: BLE001 — filet de sécurité UI
            self._error(f"Erreur inattendue : {exc}")


# ---------------------------------------------------------------------------
# Fenêtre Préférences
# ---------------------------------------------------------------------------

class PreferencesDialog(tk.Toplevel):
    """Modale pour saisir/valider le domaine Jira."""

    def __init__(self, master: tk.Misc, current_domain: str) -> None:
        super().__init__(master)
        self.title("Préférences — Kblo")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.configure(bg=COLOR_BG)

        self.result: str | None = None

        tk.Label(
            self,
            text="Domaine Jira",
            bg=COLOR_BG,
            fg=COLOR_TEXT,
            font=("Segoe UI", 11, "bold"),
        ).grid(row=0, column=0, columnspan=2, padx=16, pady=(16, 4), sticky="w")

        tk.Label(
            self,
            text="Exemple : https://company.atlassian.net",
            bg=COLOR_BG,
            fg="#5f6368",
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, columnspan=2, padx=16, sticky="w")

        self.var = tk.StringVar(value=current_domain)
        self.entry = tk.Entry(self, textvariable=self.var, width=48)
        self.entry.grid(row=2, column=0, columnspan=2, padx=16, pady=8, sticky="ew")
        self.entry.focus_set()

        self.feedback = tk.Label(
            self,
            text="",
            bg=COLOR_BG,
            font=("Segoe UI", 9),
        )
        self.feedback.grid(row=3, column=0, columnspan=2, padx=16, sticky="w")

        btn_frame = tk.Frame(self, bg=COLOR_BG)
        btn_frame.grid(row=4, column=0, columnspan=2, padx=16, pady=(12, 16), sticky="e")

        tk.Button(
            btn_frame, text="Annuler", width=10, command=self._on_cancel
        ).pack(side=tk.RIGHT, padx=(8, 0))
        tk.Button(
            btn_frame, text="Valider", width=10, command=self._on_ok
        ).pack(side=tk.RIGHT)

        self.var.trace_add("write", lambda *_: self._update_feedback())
        self._update_feedback()

        # Centrage sur la fenêtre parente.
        self.update_idletasks()
        self.geometry(self._center_on_master(master))

        self.bind("<Return>", lambda _e: self._on_ok())
        self.bind("<Escape>", lambda _e: self._on_cancel())

    def _center_on_master(self, master: tk.Misc) -> str:
        try:
            mx = master.winfo_rootx()
            my = master.winfo_rooty()
            mw = master.winfo_width()
            mh = master.winfo_height()
        except tk.TclError:
            return ""
        w = self.winfo_width() or 420
        h = self.winfo_height() or 180
        x = mx + (mw - w) // 2
        y = my + (mh - h) // 2
        return f"{w}x{h}+{x}+{y}"

    def _update_feedback(self) -> None:
        normalized = normalize_domain(self.var.get())
        if not normalized:
            self.feedback.configure(text="", fg=COLOR_TEXT)
            return
        if validate_jira_domain(normalized):
            self.feedback.configure(text=f"✓ {normalized}", fg=COLOR_OK)
        else:
            self.feedback.configure(text="✗ Format invalide", fg=COLOR_ERR)

    def _on_ok(self) -> None:
        normalized = normalize_domain(self.var.get())
        if not validate_jira_domain(normalized):
            messagebox.showerror(
                "Domaine invalide",
                "Le domaine saisi n'est pas valide. Exemple attendu : "
                "https://company.atlassian.net",
                parent=self,
            )
            return
        self.result = normalized
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()


# ---------------------------------------------------------------------------
# Application principale
# ---------------------------------------------------------------------------

class KbloApp:
    """Fenêtre principale Kblo."""

    def __init__(self) -> None:
        self.config = load_config()

        if _HAS_DND:
            self.root: tk.Tk = TkinterDnD.Tk()
        else:
            self.root = tk.Tk()

        self.root.title("Kblo — Jira Blocks → Excalidraw")
        self.root.geometry(f"{WINDOW_W}x{WINDOW_H}")
        self.root.minsize(WINDOW_W, WINDOW_H)
        self.root.configure(bg=COLOR_BG)

        self._queue: queue.Queue = queue.Queue()
        self._worker: ProcessingWorker | None = None
        self._large_response: bool | None = None
        self._large_event = threading.Event()

        self._build_ui()
        self._refresh_domain_banner()

    # ----- Construction UI -----
    def _build_ui(self) -> None:
        top = tk.Frame(self.root, bg=COLOR_BG)
        top.pack(fill=tk.X, padx=16, pady=(14, 4))

        tk.Label(
            top,
            text="Kblo",
            font=("Segoe UI", 18, "bold"),
            bg=COLOR_BG,
            fg=COLOR_TEXT,
        ).pack(side=tk.LEFT)

        tk.Button(
            top,
            text="⚙  Préférences",
            command=self._open_preferences,
            relief=tk.FLAT,
            bg=COLOR_BG,
            fg=COLOR_TEXT,
            activebackground="#ececec",
            cursor="hand2",
        ).pack(side=tk.RIGHT)

        self.banner = tk.Label(
            self.root,
            text="",
            bg=COLOR_BG,
            fg=COLOR_WARN,
            font=("Segoe UI", 9),
        )
        self.banner.pack(fill=tk.X, padx=16)

        # Zone de drop.
        self.drop_frame = tk.Frame(
            self.root,
            bg=COLOR_DROP,
            height=DROP_ZONE_H,
            highlightthickness=2,
            highlightbackground=COLOR_DROP_BORDER,
        )
        self.drop_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
        self.drop_frame.pack_propagate(False)

        self.drop_label = tk.Label(
            self.drop_frame,
            text=(
                "📄\n\nGlissez votre CSV Jira ici\n"
                "ou cliquez pour parcourir"
            ),
            bg=COLOR_DROP,
            fg="#5f6368",
            font=("Segoe UI", 11),
            justify=tk.CENTER,
            cursor="hand2",
        )
        self.drop_label.pack(expand=True)

        self.drop_label.bind("<Button-1>", lambda _e: self._browse())
        self.drop_frame.bind("<Button-1>", lambda _e: self._browse())

        if _HAS_DND:
            self.drop_frame.drop_target_register(DND_FILES)
            self.drop_frame.dnd_bind("<<Drop>>", self._on_drop)
            self.drop_frame.dnd_bind("<<DragEnter>>", self._on_drag_enter)
            self.drop_frame.dnd_bind("<<DragLeave>>", self._on_drag_leave)

        # Barre de progression (cachée au repos).
        self.progress_frame = tk.Frame(self.root, bg=COLOR_BG)

        self.progress_label = tk.Label(
            self.progress_frame,
            text="",
            bg=COLOR_BG,
            fg=COLOR_TEXT,
            font=("Segoe UI", 9),
        )
        self.progress_label.pack(anchor="w", padx=16)

        self.progress = ttk.Progressbar(
            self.progress_frame,
            orient="horizontal",
            mode="determinate",
            maximum=100,
        )
        self.progress.pack(fill=tk.X, padx=16, pady=(4, 10))

    # ----- Drag & drop -----
    def _on_drag_enter(self, _event) -> None:
        self.drop_frame.configure(
            bg=COLOR_DROP_HOVER, highlightbackground="#1a73e8"
        )
        self.drop_label.configure(bg=COLOR_DROP_HOVER)

    def _on_drag_leave(self, _event) -> None:
        self.drop_frame.configure(
            bg=COLOR_DROP, highlightbackground=COLOR_DROP_BORDER
        )
        self.drop_label.configure(bg=COLOR_DROP)

    def _on_drop(self, event) -> None:
        self._on_drag_leave(event)
        paths = self._parse_dnd_paths(event.data)
        if not paths:
            return
        self._start_processing(Path(paths[0]))

    @staticmethod
    def _parse_dnd_paths(data: str) -> list[str]:
        """Parse la chaîne ``event.data`` fournie par TkinterDnD.

        Les chemins avec espaces sont encadrés par des accolades.
        """
        if not data:
            return []
        paths: list[str] = []
        current = ""
        in_braces = False
        for ch in data:
            if ch == "{":
                in_braces = True
                continue
            if ch == "}":
                in_braces = False
                if current:
                    paths.append(current)
                    current = ""
                continue
            if ch == " " and not in_braces:
                if current:
                    paths.append(current)
                    current = ""
                continue
            current += ch
        if current:
            paths.append(current)
        return paths

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Sélectionnez un CSV Jira",
            filetypes=[("Fichiers CSV", "*.csv"), ("Tous les fichiers", "*.*")],
        )
        if path:
            self._start_processing(Path(path))

    # ----- Préférences -----
    def _open_preferences(self) -> tk.StringVar | None:
        dialog = PreferencesDialog(self.root, self.config.get("jira_domain", ""))
        self.root.wait_window(dialog)
        if dialog.result is not None:
            self.config["jira_domain"] = dialog.result
            save_config(self.config)
            messagebox.showinfo(
                "Préférences",
                "Préférences sauvegardées.",
                parent=self.root,
            )
            self._refresh_domain_banner()
        return None

    def _refresh_domain_banner(self) -> None:
        domain = self.config.get("jira_domain", "")
        if domain and validate_jira_domain(domain):
            self.banner.configure(text=f"Domaine Jira : {domain}", fg="#5f6368")
        else:
            self.banner.configure(
                text="⚠  Domaine Jira non configuré (Préférences)",
                fg=COLOR_WARN,
            )

    # ----- Pipeline -----
    def _start_processing(self, csv_path: Path) -> None:
        if self._worker is not None and self._worker.is_alive():
            messagebox.showinfo(
                "Kblo",
                "Un traitement est déjà en cours.",
                parent=self.root,
            )
            return

        domain = self.config.get("jira_domain", "")
        if not domain or not validate_jira_domain(domain):
            messagebox.showwarning(
                "Domaine requis",
                "Veuillez d'abord configurer le domaine Jira dans les préférences.",
                parent=self.root,
            )
            self._open_preferences()
            domain = self.config.get("jira_domain", "")
            if not domain or not validate_jira_domain(domain):
                return

        self._show_progress(True)
        self._current_csv = csv_path

        self._worker = ProcessingWorker(
            csv_path=csv_path,
            jira_domain=domain,
            outbox=self._queue,
            confirm_large=self._confirm_large_blocking,
        )
        self._worker.start()
        self.root.after(80, self._poll_queue)

    def _confirm_large_blocking(self, n: int) -> bool:
        """Appelé depuis le worker — rebascule vers le thread UI."""
        self._large_event.clear()
        self._large_response = None

        def ask() -> None:
            self._large_response = messagebox.askyesno(
                "Beaucoup de tickets",
                f"Plus de {MAX_RECOMMENDED_TICKETS} tickets détectés "
                f"({n}). Le rendu peut être illisible.\n\n"
                "Continuer quand même ?",
                parent=self.root,
            )
            self._large_event.set()

        self.root.after(0, ask)
        self._large_event.wait()
        return bool(self._large_response)

    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self._queue.get_nowait()
                self._dispatch(msg)
        except queue.Empty:
            pass

        if self._worker is not None and self._worker.is_alive():
            self.root.after(80, self._poll_queue)

    def _dispatch(self, msg: tuple) -> None:
        kind = msg[0]
        if kind == "progress":
            _, value, label = msg
            self.progress["value"] = value
            self.progress_label.configure(text=f"{value}% — {label}")
        elif kind == "warn":
            # Les warnings non bloquants s'accumulent dans stderr ; on
            # se contente d'un affichage discret dans la barre de progression.
            sys.stderr.write(f"[Kblo] warning: {msg[1]}\n")
        elif kind == "done":
            _, document, suggested_name = msg
            self._handle_done(document, suggested_name)
        elif kind == "cancelled":
            self._show_progress(False)
        elif kind == "error":
            self._show_progress(False)
            messagebox.showerror("Kblo", msg[1], parent=self.root)

    def _handle_done(self, document: dict, suggested_name: str) -> None:
        initial_dir = self._default_save_dir()
        target = filedialog.asksaveasfilename(
            title="Enregistrer le diagramme Excalidraw",
            defaultextension=".excalidraw",
            filetypes=[("Excalidraw", "*.excalidraw"), ("Tous les fichiers", "*.*")],
            initialdir=initial_dir,
            initialfile=suggested_name,
            parent=self.root,
        )

        if not target:
            self._show_progress(False)
            return

        target_path = Path(target)
        try:
            write_excalidraw(document, target_path)
        except OSError as exc:
            messagebox.showerror(
                "Kblo",
                f"Impossible d'écrire le fichier : {exc}",
                parent=self.root,
            )
            self._show_progress(False)
            return

        self.config["last_export_path"] = str(target_path.parent)
        save_config(self.config)
        self._show_progress(False)

        messagebox.showinfo(
            "Kblo",
            f"Fichier généré avec succès !\n\n{target_path}",
            parent=self.root,
        )

    def _default_save_dir(self) -> str:
        last = self.config.get("last_export_path") or ""
        if last and Path(last).is_dir():
            return last
        if getattr(self, "_current_csv", None):
            return str(self._current_csv.parent)
        return str(Path.home())

    def _show_progress(self, visible: bool) -> None:
        if visible:
            self.progress["value"] = 0
            self.progress_label.configure(text="")
            self.progress_frame.pack(fill=tk.X, pady=(0, 8))
        else:
            self.progress_frame.pack_forget()

    # ----- Main loop -----
    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    """Point d'entrée de l'application."""
    if not _HAS_DND:
        # On n'interrompt pas l'application : le bouton "Parcourir" reste
        # fonctionnel. On informe simplement l'utilisateur via stderr.
        sys.stderr.write(
            "[Kblo] tkinterdnd2 non installé : drag-drop désactivé. "
            "Installez-le avec `pip install tkinterdnd2`.\n"
        )

    # On s'assure que config.json existe dès le premier démarrage.
    load_config()
    _ = CONFIG_PATH  # référencer pour garder l'import explicite utile au debug

    KbloApp().run()


if __name__ == "__main__":
    main()

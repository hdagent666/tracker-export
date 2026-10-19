"""Desktop GUI: `tracker-export-gui`. Tkinter, stdlib only.

Batch export laid out in usage order:
  1. select tracker files/folders  2. destination (remembered)
  3. selections                     4. choice window (the queue)
  5. terminal (log)                 6. export buttons
Themed after FastTracker II: dark slate panels, chunky beveled buttons,
and a pattern-editor style log (black background, green data lines).
Destination and selections persist in ~/.tracker_export.json.
"""

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .export import (ExportCancelled, collect_modules, export_batch,
                     read_module_text)

FILETYPES = [
    ("Tracker modules",
     "*.mod *.s3m *.xm *.it *.stm *.mtm *.669 *.amf *.ult *.dmf *.okt "
     "*.med *.dbm *.mdl *.mptm *.nst *.imf *.far *.ptm *.umx"),
    ("All files", "*.*"),
]

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".tracker_export.json")
SAMPLE_RATES = [22050, 32000, 44100, 48000, 88200, 96000]

# --- FastTracker II palette -------------------------------------------------
BG = "#2A2A44"          # main slate panel
PANEL = "#343452"       # raised panel
DEEP = "#101024"        # sunken wells (list, entry)
BLACK = "#000000"       # pattern editor background
BTN = "#4A4A74"         # button face
BTN_ACTIVE = "#606096"  # button hover
BTN_PRESSED = "#38385C"
FG = "#E6E6F2"          # main text
DIM = "#9D9DC0"         # secondary text
LOGFG = "#CDCDDE"       # pattern data text
ACCENT = "#FFFF55"      # FT2 yellow highlight
GREEN = "#50FF50"       # instrument-number green
RED = "#FF5050"
SELECT = "#3D3DBB"      # selection blue
BAR = "#00E040"         # progress green

FONT = ("Courier New", 11)
FONT_B = ("Courier New", 11, "bold")
FONT_LOG = ("Courier New", 10)
FONT_TITLE = ("Courier New", 25, "bold")
FONT_SUB = ("Courier New", 10, "bold")


def _apply_ft2_theme(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=FG, font=FONT,
                    bordercolor="#1A1A2E")
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=FG, font=FONT)
    style.configure("Head.TLabel", font=FONT_B, foreground=FG)
    style.configure("Dim.TLabel", foreground=DIM, font=("Courier New", 10))
    style.configure("Status.TLabel", foreground=ACCENT, font=FONT_B)
    style.configure("Count.TLabel", foreground=DIM, font=FONT)

    style.configure("TButton", background=BTN, foreground="#FFFFFF",
                    font=FONT_B, borderwidth=2, relief="raised",
                    padding=(9, 4), focusthickness=0)
    style.map("TButton",
              background=[("pressed", BTN_PRESSED),
                          ("active", BTN_ACTIVE),
                          ("disabled", PANEL)],
              foreground=[("disabled", DIM)],
              relief=[("pressed", "sunken")])

    style.configure("TCheckbutton", background=BG, foreground=FG,
                    font=FONT)
    style.map("TCheckbutton",
              background=[("active", BG)],
              foreground=[("disabled", DIM)])

    style.configure("TEntry", fieldbackground=DEEP, foreground=FG,
                    insertcolor="#FFFFFF", borderwidth=2, padding=3)

    style.configure("TScrollbar", background=BTN, troughcolor=PANEL,
                    arrowcolor="#FFFFFF", borderwidth=1)
    style.map("TScrollbar", background=[("active", BTN_ACTIVE)])

    style.configure("FT2.Horizontal.TProgressbar",
                    troughcolor=DEEP, background=BAR,
                    lightcolor=BAR, darkcolor="#00701C",
                    borderwidth=1, thickness=14)
    return style


def _load_settings():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


class ExportApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Tracker Export II — v{__version__}")
        self.geometry("680x730")
        self.minsize(580, 640)
        self.configure(background=BG)
        _apply_ft2_theme(self)

        saved = _load_settings()
        self.outdir_var = tk.StringVar(value=saved.get("outdir", ""))
        self.stems_var = tk.BooleanVar(value=bool(saved.get("stems", True)))
        self.samples_var = tk.BooleanVar(
            value=bool(saved.get("samples", True)))
        sr = saved.get("sr", 44100)
        self.sr_var = tk.IntVar(value=sr if sr in SAMPLE_RATES else 44100)
        self.cancel_event = threading.Event()
        self.events = queue.Queue()
        self.worker = None
        self.last_export_dir = None
        self._msg_cache = {}
        self._msg_meta_cache = {}
        self._msg_path = None
        self._view = "terminal"

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_events)

    # -- settings persistence -------------------------------------------------

    def _save_settings(self):
        data = {"outdir": self.outdir_var.get(),
                "stems": bool(self.stems_var.get()),
                "samples": bool(self.samples_var.get()),
                "sr": int(self.sr_var.get())}
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except Exception:
            pass

    def _on_close(self):
        self._save_settings()
        self.destroy()

    # -- UI ---------------------------------------------------------------

    def _banner(self, parent, row):
        banner = tk.Frame(parent, background=BLACK,
                          highlightbackground="#55557F", highlightthickness=1)
        banner.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        banner.columnconfigure(0, weight=1)
        left = tk.Frame(banner, background=BLACK)
        left.grid(row=0, column=0, sticky="w", padx=12, pady=8)
        title = tk.Frame(left, background=BLACK)
        title.pack(anchor="w")
        tk.Label(title, text="TRACKER EXPORT", font=FONT_TITLE,
                 foreground="#FFFFFF", background=BLACK).pack(side="left")
        tk.Label(title, text=" II", font=FONT_TITLE,
                 foreground=ACCENT, background=BLACK).pack(side="left")
        tk.Label(left, text="S T E M S   +   S A M P L E S   B O U N C E R",
                 font=FONT_SUB, foreground=DIM,
                 background=BLACK).pack(anchor="w", pady=(2, 0))
        # Top-right readout: the selected module's file name and the
        # message hidden in it (its title), like a "now loaded" display.
        readout = tk.Frame(banner, background=BLACK)
        readout.grid(row=0, column=1, sticky="e", padx=12)
        self.bn_file = tk.Label(readout, text="", font=FONT_B,
                                foreground=ACCENT, background=BLACK,
                                justify="right")
        self.bn_file.pack(anchor="e")
        self.bn_title = tk.Label(readout, text="C-4 01 ·· ···",
                                 font=FONT_LOG, foreground=GREEN,
                                 background=BLACK, justify="right")
        self.bn_title.pack(anchor="e")
        self.bn_meta = tk.Label(readout, text="", font=FONT_LOG,
                                foreground=DIM, background=BLACK,
                                justify="right")
        self.bn_meta.pack(anchor="e")
        self._banner_idle()

    def _step(self, parent, row, text):
        ttk.Label(parent, text=text, style="Head.TLabel").grid(
            row=row, column=0, sticky="w", pady=(8, 2))

    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}
        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, **pad)
        main.columnconfigure(0, weight=1)

        self._banner(main, 0)

        # 1 · SELECT TRACKER ------------------------------------------------
        self._step(main, 1, "1 · SELECT TRACKER")
        pick = ttk.Frame(main)
        pick.grid(row=2, column=0, sticky="ew")
        ttk.Button(pick, text="Add files...",
                   command=self._add_files).pack(side="left")
        ttk.Button(pick, text="Add folder...",
                   command=self._add_folder).pack(side="left", padx=(6, 0))
        ttk.Button(pick, text="Remove",
                   command=self._remove_selected).pack(side="left",
                                                        padx=(16, 0))
        ttk.Button(pick, text="Clear",
                   command=self._clear_queue).pack(side="left", padx=(6, 0))
        self.count_label = ttk.Label(pick, text="0 in queue",
                                     style="Count.TLabel")
        self.count_label.pack(side="right")

        # 2 · DESTINATION ---------------------------------------------------
        self._step(main, 3, "2 · DESTINATION")
        out = ttk.Frame(main)
        out.grid(row=4, column=0, sticky="ew")
        out.columnconfigure(0, weight=1)
        ttk.Entry(out, textvariable=self.outdir_var).grid(
            row=0, column=0, sticky="ew")
        ttk.Button(out, text="Browse...", command=self._pick_outdir).grid(
            row=0, column=1, padx=(6, 0))
        ttk.Label(main,
                  text="Remembered between launches. Blank = an "
                       "<title>_export folder next to each module file.",
                  style="Dim.TLabel").grid(row=5, column=0, sticky="w")

        # 3 · SELECTIONS -----------------------------------------------------
        self._step(main, 6, "3 · SELECTIONS")
        opts = ttk.Frame(main)
        opts.grid(row=7, column=0, sticky="w")
        ttk.Checkbutton(opts, text="Stems (one WAV per channel)",
                        variable=self.stems_var).pack(side="left")
        ttk.Checkbutton(opts, text="Samples (labeled WAVs)",
                        variable=self.samples_var).pack(side="left",
                                                    padx=(12, 0))
        rate = ttk.Frame(main)
        rate.grid(row=8, column=0, sticky="w", pady=(4, 0))
        ttk.Label(rate, text="RENDER RATE:").pack(side="left", padx=(0, 6))
        sr_menu = tk.OptionMenu(rate, self.sr_var, *SAMPLE_RATES)
        sr_menu.configure(background=BTN, foreground="#FFFFFF",
                          font=FONT_B, activebackground=BTN_ACTIVE,
                          activeforeground="#FFFFFF", width=7,
                          highlightthickness=0, borderwidth=2,
                          relief="raised")
        sr_menu["menu"].configure(background=DEEP, foreground=FG,
                                  font=FONT, activebackground=SELECT,
                                  activeforeground="#FFFFFF")
        sr_menu.pack(side="left")
        ttk.Label(rate, text="Hz").pack(side="left", padx=(6, 0))

        # 4 · CHOICE WINDOW (queue) ------------------------------------------
        self._step(main, 9, "4 · QUEUED MODULES")
        list_frame = ttk.Frame(main)
        list_frame.grid(row=10, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        main.rowconfigure(10, weight=1)
        self.queue_box = tk.Listbox(
            list_frame, height=6, selectmode="extended",
            background=DEEP, foreground=FG, font=FONT,
            selectbackground=SELECT, selectforeground="#FFFFFF",
            relief="sunken", borderwidth=2, highlightthickness=0,
            activestyle="none")
        self.queue_box.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(list_frame, orient="vertical",
                           command=self.queue_box.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.queue_box.configure(yscrollcommand=sb.set)

        # 5 · TERMINAL / MESSAGES FROM THE PAST --------------------------------
        hdr5 = ttk.Frame(main)
        hdr5.grid(row=11, column=0, sticky="ew", pady=(8, 2))
        ttk.Label(hdr5, text="5 · TERMINAL / MESSAGES",
                  style="Head.TLabel").pack(side="left")
        self.msg_tab_btn = tk.Button(
            hdr5, text="Messages from the past",
            command=lambda: self._switch_view("messages"),
            background=BTN, foreground="#FFFFFF", font=FONT_B,
            activebackground=BTN_ACTIVE, activeforeground="#FFFFFF",
            borderwidth=2, relief="raised", padx=8, pady=1)
        self.msg_tab_btn.pack(side="right")
        self.term_tab_btn = tk.Button(
            hdr5, text="Terminal",
            command=lambda: self._switch_view("terminal"),
            background=BTN, foreground="#FFFFFF", font=FONT_B,
            activebackground=BTN_ACTIVE, activeforeground="#FFFFFF",
            borderwidth=2, relief="sunken", padx=8, pady=1)
        self.term_tab_btn.pack(side="right", padx=(0, 6))

        log_frame = ttk.Frame(main)
        log_frame.grid(row=12, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main.rowconfigure(12, weight=1)

        text_kw = dict(height=9, wrap="word", state="disabled",
                       background=BLACK, foreground=LOGFG, font=FONT_LOG,
                       insertbackground="#FFFFFF", relief="sunken",
                       borderwidth=2, highlightthickness=0)
        self.log = tk.Text(log_frame, **text_kw)
        self.log.grid(row=0, column=0, sticky="nsew")
        self.messages = tk.Text(log_frame, **text_kw)
        self.messages.grid(row=0, column=0, sticky="nsew")
        self.messages.grid_remove()
        for widget in (self.log, self.messages):
            widget.tag_configure("head", foreground=GREEN, font=FONT_B)
            widget.tag_configure("err", foreground=RED)
            widget.tag_configure("ok", foreground=ACCENT, font=FONT_B)
        self.messages.tag_configure("from", foreground=ACCENT,
                                    font=FONT_B)
        lsb = ttk.Scrollbar(log_frame, orient="vertical",
                            command=self._scroll_active)
        lsb.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=lsb.set)
        self.messages.configure(yscrollcommand=lsb.set)
        self.queue_box.bind("<<ListboxSelect>>", self._on_queue_select)
        self._reset_messages()

        # 6 · EXPORT ------------------------------------------------------------
        self.progress = ttk.Progressbar(main, mode="determinate",
                                        maximum=1000,
                                        style="FT2.Horizontal.TProgressbar")
        self.progress.grid(row=13, column=0, sticky="ew", pady=(10, 0))
        self.status = ttk.Label(main, text="Ready.", style="Status.TLabel")
        self.status.grid(row=14, column=0, sticky="w")

        actions = ttk.Frame(main)
        actions.grid(row=15, column=0, sticky="e", pady=(8, 0))
        self.reveal_btn = ttk.Button(
            actions, text="Show last export", state="disabled",
            command=self._reveal)
        self.reveal_btn.pack(side="left", padx=(0, 8))
        self.cancel_btn = ttk.Button(
            actions, text="Cancel", state="disabled",
            command=self._cancel)
        self.cancel_btn.pack(side="left", padx=(0, 8))
        self.export_btn = ttk.Button(
            actions, text="EXPORT", command=self._start_export)
        self.export_btn.pack(side="left")

        self._log("Tracker Export II ready. Add files or a folder, "
                  "then hit EXPORT.")

    # -- queue management ---------------------------------------------------

    def _queued(self):
        return list(self.queue_box.get(0, "end"))

    def _refresh_count(self):
        n = self.queue_box.size()
        self.count_label.configure(text=f"{n} in queue")

    def _add_paths(self, paths):
        existing = set(self._queued())
        added = 0
        for p in paths:
            ap = os.path.abspath(p)
            if ap not in existing:
                self.queue_box.insert("end", ap)
                existing.add(ap)
                added += 1
        self._refresh_count()
        return added

    def _add_files(self):
        paths = filedialog.askopenfilenames(title="Choose tracker modules",
                                            filetypes=FILETYPES)
        if paths:
            self._add_paths(paths)

    def _add_folder(self):
        folder = filedialog.askdirectory(
            title="Crawl this folder (and subfolders) for modules")
        if not folder:
            return
        mods = collect_modules([folder], recursive=True)
        if not mods:
            messagebox.showinfo(
                "No modules found",
                f"No tracker modules found under {folder}")
            return
        added = self._add_paths(mods)
        self._log(f"Folder crawl: found {len(mods)} module(s), "
                  f"{added} new in queue.")

    def _remove_selected(self):
        for idx in reversed(self.queue_box.curselection()):
            self.queue_box.delete(idx)
        self._refresh_count()
        if self._msg_path and self._msg_path not in self._queued():
            self._reset_messages()

    def _clear_queue(self):
        self.queue_box.delete(0, "end")
        self._refresh_count()
        self._reset_messages()

    def _pick_outdir(self):
        path = filedialog.askdirectory(title="Choose output folder")
        if path:
            self.outdir_var.set(path)
            self._save_settings()

    # -- messages from the past --------------------------------------------

    @staticmethod
    def _clip(text, limit=36):
        return text if len(text) <= limit else text[:limit - 1] + "…"

    def _banner_idle(self):
        self.bn_file.configure(text="")
        self.bn_title.configure(text="C-4 01 ·· ···")
        self.bn_meta.configure(text="")

    def _set_banner(self, path, meta):
        self.bn_file.configure(
            text=self._clip(os.path.basename(path)))
        self.bn_title.configure(
            text=self._clip(meta.get("title") or "(untitled)"))
        parts = meta.get("parts") or []
        meta_line = " · ".join(parts) if parts else (meta.get("type") or "")
        self.bn_meta.configure(text=self._clip(meta_line))

    def _scroll_active(self, *args):
        target = self.messages if self._view == "messages" else self.log
        target.yview(*args)

    def _switch_view(self, name):
        self._view = name
        if name == "messages":
            self.log.grid_remove()
            self.messages.grid()
            self.msg_tab_btn.configure(relief="sunken")
            self.term_tab_btn.configure(relief="raised")
        else:
            self.messages.grid_remove()
            self.log.grid()
            self.term_tab_btn.configure(relief="sunken")
            self.msg_tab_btn.configure(relief="raised")

    def _reset_messages(self):
        self._msg_path = None
        self._banner_idle()
        self._show_messages(
            "Messages from the past\n"
            "\n"
            "Select a queued module and the text hidden inside it\n"
            "appears here: its title, its song message, and the\n"
            "instrument & sample names — the classic places demo-scene\n"
            "authors hid their greetings.\n")

    def _show_messages(self, body):
        self.messages.configure(state="normal")
        self.messages.delete("1.0", "end")
        for i, line in enumerate(body.splitlines()):
            tag = None
            if i == 0:
                tag = "from"
            elif line.startswith("---"):
                tag = "head"
            self.messages.insert("end", line + "\n", tag)
        self.messages.configure(state="disabled")
        self.messages.yview_moveto(0)

    def _on_queue_select(self, _event=None):
        sel = self.queue_box.curselection()
        if not sel:
            return
        path = self.queue_box.get(sel[0])
        self._msg_path = path
        self._switch_view("messages")
        self.bn_file.configure(text=self._clip(os.path.basename(path)))
        self.bn_title.configure(text="reading…")
        self.bn_meta.configure(text="")
        if path in self._msg_cache:
            self._show_messages(self._msg_cache[path])
            meta = self._msg_meta_cache.get(path)
            if meta:
                self._set_banner(path, meta)
            return
        self._show_messages(
            f"messages from {os.path.basename(path)}\n\nReading...")
        threading.Thread(target=self._read_messages_worker,
                         args=(path,), daemon=True).start()

    def _read_messages_worker(self, path):
        meta = None
        try:
            meta, text = read_module_text(path)
            body = text
        except SystemExit as e:
            body = (f"messages from {os.path.basename(path)}\n\n"
                    f"No readable text in this one ({e}).")
        except Exception as e:  # noqa: BLE001
            body = (f"messages from {os.path.basename(path)}\n\n"
                    f"Couldn't read this file: {type(e).__name__}: {e}")
        self.events.put(("messages", (path, body, meta)))

    # -- export -------------------------------------------------------------

    def _start_export(self):
        files = self._queued()
        if not files:
            messagebox.showerror("Nothing queued",
                                 "Add at least one module first.")
            return
        if not self.stems_var.get() and not self.samples_var.get():
            messagebox.showerror(
                "Nothing to export",
                "Enable stems and/or samples.")
            return
        self.cancel_event.clear()
        self.export_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.reveal_btn.configure(state="disabled")
        self.progress.configure(value=0)
        n = len(files)
        self.status.configure(
            text=f"Exporting {n} module{'s' if n != 1 else ''}...")
        # Snapshot widget values HERE, on the main thread: Tk variables
        # must not be read from the worker thread ("main thread is not
        # in main loop" RuntimeError).
        opts = dict(outdir=self.outdir_var.get() or None,
                    sample_rate=int(self.sr_var.get()),
                    do_stems=self.stems_var.get(),
                    do_samples=self.samples_var.get())
        self._save_settings()
        self.worker = threading.Thread(target=self._run, args=(files, opts),
                                       daemon=True)
        self.worker.start()

    def _run(self, files, opts):
        try:
            exported, failures = export_batch(
                files,
                **opts,
                on_log=lambda m: self.events.put(("log", m)),
                on_progress=lambda f, lbl: self.events.put(
                    ("progress", (f, lbl))),
                cancel=self.cancel_event.is_set,
            )
            self.events.put(("done", (exported, failures)))
        except ExportCancelled:
            self.events.put(("cancelled", None))
        except SystemExit as e:
            self.events.put(("error", str(e)))
        except Exception as e:  # noqa: BLE001
            self.events.put(("error", f"{type(e).__name__}: {e}"))

    def _cancel(self):
        self.cancel_event.set()
        self.status.configure(text="Cancelling...")

    def _drain_events(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "log":
                    self._log(data)
                elif kind == "messages":
                    path, body, meta = data
                    self._msg_cache[path] = body
                    if meta:
                        self._msg_meta_cache[path] = meta
                    if self._msg_path == path:
                        self._show_messages(body)
                        if meta:
                            self._set_banner(path, meta)
                elif kind == "progress":
                    frac, label = data
                    self.progress.configure(value=int(frac * 1000))
                    self.status.configure(text=label)
                elif kind == "done":
                    exported, failures = data
                    if exported:
                        self.last_export_dir = exported[0]
                        self.reveal_btn.configure(state="normal")
                    self.status.configure(
                        text=f"Done: {len(exported)} exported, "
                             f"{len(failures)} skipped/failed.")
                    self._finish()
                elif kind == "cancelled":
                    self.status.configure(text="Cancelled.")
                    self._finish()
                elif kind == "error":
                    messagebox.showerror("Export failed", data)
                    self.status.configure(text="Failed.")
                    self._finish()
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _finish(self):
        self.export_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")

    def _log(self, msg):
        tag = None
        if msg.startswith("---") or msg.startswith("Batch complete"):
            tag = "ok" if msg.startswith("Batch complete") else "head"
        elif "SKIPPED" in msg or "FAILED" in msg or msg.startswith("error"):
            tag = "err"
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _reveal(self):
        target = self.outdir_var.get() or self.last_export_dir
        if not target:
            return
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", target], check=False)
            elif sys.platform.startswith("win"):
                os.startfile(target)  # noqa: S606
            else:
                subprocess.run(["xdg-open", target], check=False)
        except Exception:
            pass


def main():
    app = ExportApp()
    app.mainloop()


if __name__ == "__main__":
    main()

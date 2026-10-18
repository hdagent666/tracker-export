"""Desktop GUI: `tracker-export-gui`. Tkinter, stdlib only.

Supports batch export: queue individual files or crawl whole folders.
"""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .export import ExportCancelled, collect_modules, export_batch

FILETYPES = [
    ("Tracker modules",
     "*.mod *.s3m *.xm *.it *.stm *.mtm *.669 *.amf *.ult *.dmf *.okt "
     "*.med *.dbm *.mdl *.mptm *.nst *.imf *.far *.ptm *.umx"),
    ("All files", "*.*"),
]


class ExportApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Tracker Export {__version__}")
        self.geometry("640x600")
        self.minsize(560, 520)

        self.outdir_var = tk.StringVar()
        self.stems_var = tk.BooleanVar(value=True)
        self.samples_var = tk.BooleanVar(value=True)
        self.sr_var = tk.IntVar(value=44100)
        self.cancel_event = threading.Event()
        self.events = queue.Queue()
        self.worker = None
        self.last_export_dir = None

        self._build_ui()
        self.after(100, self._drain_events)

    # -- UI ---------------------------------------------------------------

    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}
        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, **pad)
        main.columnconfigure(0, weight=1)

        ttk.Label(main, text="Modules to export:").grid(
            row=0, column=0, sticky="w")

        list_frame = ttk.Frame(main)
        list_frame.grid(row=1, column=0, sticky="nsew", pady=(2, 2))
        list_frame.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)
        self.queue_box = tk.Listbox(list_frame, height=7, selectmode="extended")
        self.queue_box.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(list_frame, orient="vertical",
                           command=self.queue_box.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.queue_box.configure(yscrollcommand=sb.set)

        btns = ttk.Frame(main)
        btns.grid(row=2, column=0, sticky="w", pady=(0, 2))
        ttk.Button(btns, text="Add files...",
                   command=self._add_files).pack(side="left")
        ttk.Button(btns, text="Add folder...",
                   command=self._add_folder).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Remove",
                   command=self._remove_selected).pack(side="left",
                                                        padx=(16, 0))
        ttk.Button(btns, text="Clear",
                   command=self._clear_queue).pack(side="left", padx=(6, 0))
        self.count_label = ttk.Label(btns, text="0 modules queued")
        self.count_label.pack(side="left", padx=(16, 0))

        out = ttk.Frame(main)
        out.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        out.columnconfigure(1, weight=1)
        ttk.Label(out, text="Output folder:").grid(row=0, column=0, sticky="w")
        ttk.Entry(out, textvariable=self.outdir_var).grid(
            row=0, column=1, sticky="ew", padx=6)
        ttk.Button(out, text="Browse...", command=self._pick_outdir).grid(
            row=0, column=2)
        ttk.Label(main,
                  text="Blank = an <title>_export folder next to each "
                       "module file.").grid(row=4, column=0, sticky="w")

        opts = ttk.Frame(main)
        opts.grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Checkbutton(opts, text="Stems (one WAV per channel)",
                        variable=self.stems_var).pack(side="left")
        ttk.Checkbutton(opts, text="Samples (labeled WAVs)",
                        variable=self.samples_var).pack(side="left",
                                                    padx=(12, 0))
        ttk.Label(opts, text="Render rate:").pack(side="left", padx=(16, 4))
        ttk.Combobox(opts, textvariable=self.sr_var, width=8,
                     values=[22050, 32000, 44100, 48000, 88200, 96000],
                     state="readonly").pack(side="left")

        self.progress = ttk.Progressbar(main, mode="determinate",
                                        maximum=1000)
        self.progress.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        self.status = ttk.Label(main, text="Ready.")
        self.status.grid(row=7, column=0, sticky="w")

        self.log = tk.Text(main, height=10, wrap="word",
                           state="disabled")
        self.log.grid(row=8, column=0, sticky="nsew", pady=(4, 0))
        main.rowconfigure(8, weight=1)

        actions = ttk.Frame(main)
        actions.grid(row=9, column=0, sticky="e", pady=(8, 0))
        self.reveal_btn = ttk.Button(
            actions, text="Show last export", state="disabled",
            command=self._reveal)
        self.reveal_btn.pack(side="left", padx=(0, 8))
        self.cancel_btn = ttk.Button(
            actions, text="Cancel", state="disabled",
            command=self._cancel)
        self.cancel_btn.pack(side="left", padx=(0, 8))
        self.export_btn = ttk.Button(
            actions, text="Export", command=self._start_export)
        self.export_btn.pack(side="left")

    # -- queue management ---------------------------------------------------

    def _queued(self):
        return list(self.queue_box.get(0, "end"))

    def _refresh_count(self):
        n = self.queue_box.size()
        self.count_label.configure(
            text=f"{n} module{'s' if n != 1 else ''} queued")

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

    def _clear_queue(self):
        self.queue_box.delete(0, "end")
        self._refresh_count()

    def _pick_outdir(self):
        path = filedialog.askdirectory(title="Choose output folder")
        if path:
            self.outdir_var.set(path)

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
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
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

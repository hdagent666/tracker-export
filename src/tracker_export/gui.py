"""Desktop GUI: `tracker-export-gui`. Tkinter, stdlib only."""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .engine import find_libxmp, libxmp_install_hint
from .export import ExportCancelled, export_module

MODULE_TYPES = [
    ("Tracker modules",
     "*.mod *.s3m *.xm *.it *.stm *.mtm *.669 *.amf *.ult *.dmf *.okt "
     "*.med *.dbm *.mdl *.mptm"),
    ("All files", "*.*"),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Tracker Export {__version__}")
        self.geometry("620x520")
        self.minsize(560, 460)
        self._worker = None
        self._cancel_event = threading.Event()
        self._ui_queue = queue.Queue()
        self._export_dir = None
        self._build_widgets()
        self._check_libxmp()
        self.after(100, self._pump_queue)

    # -- layout ------------------------------------------------------
    def _build_widgets(self):
        pad = {"padx": 10, "pady": 4}
        frm = ttk.Frame(self)
        frm.pack(fill=tk.BOTH, expand=True)

        # module file
        ttk.Label(frm, text="Module file:").grid(row=0, column=0, sticky="w",
                                                 **pad)
        self.input_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.input_var).grid(
            row=1, column=0, sticky="ew", **pad)
        ttk.Button(frm, text="Browse…",
                   command=self._browse_input).grid(row=1, column=1, **pad)

        # output dir
        ttk.Label(frm, text="Output folder (blank = next to the module):").grid(
            row=2, column=0, sticky="w", **pad)
        self.outdir_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.outdir_var).grid(
            row=3, column=0, sticky="ew", **pad)
        ttk.Button(frm, text="Browse…",
                   command=self._browse_outdir).grid(row=3, column=1, **pad)

        # options
        opts = ttk.LabelFrame(frm, text="Options")
        opts.grid(row=4, column=0, columnspan=2, sticky="ew", **pad)
        self.stems_var = tk.BooleanVar(value=True)
        self.samples_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Per-channel stems",
                        variable=self.stems_var).pack(side=tk.LEFT, padx=10,
                                                      pady=6)
        ttk.Checkbutton(opts, text="Bounce samples",
                        variable=self.samples_var).pack(side=tk.LEFT, padx=10,
                                                        pady=6)
        ttk.Label(opts, text="Rate:").pack(side=tk.LEFT, padx=(10, 2), pady=6)
        self.sr_var = tk.StringVar(value="44100")
        ttk.Combobox(opts, textvariable=self.sr_var, width=7,
                     values=("44100", "48000", "96000"),
                     state="readonly").pack(side=tk.LEFT, pady=6)

        # buttons
        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=2, sticky="ew", **pad)
        self.export_btn = ttk.Button(btns, text="Export",
                                     command=self._start_export)
        self.export_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.cancel_btn = ttk.Button(btns, text="Cancel",
                                     command=self._cancel, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.reveal_btn = ttk.Button(btns, text="Show export folder",
                                     command=self._reveal, state=tk.DISABLED)
        self.reveal_btn.pack(side=tk.LEFT)

        # progress
        self.prog_var = tk.DoubleVar(value=0)
        self.prog_label = tk.StringVar(value="Idle.")
        ttk.Label(frm, textvariable=self.prog_label).grid(
            row=6, column=0, columnspan=2, sticky="w", **pad)
        ttk.Progressbar(frm, variable=self.prog_var, maximum=100).grid(
            row=7, column=0, columnspan=2, sticky="ew", **pad)

        # log
        ttk.Label(frm, text="Log:").grid(row=8, column=0, sticky="w", **pad)
        self.log_text = tk.Text(frm, height=10, state=tk.DISABLED,
                                wrap=tk.WORD)
        self.log_text.grid(row=9, column=0, columnspan=2, sticky="nsew",
                           **pad)
        scroll = ttk.Scrollbar(frm, command=self.log_text.yview)
        scroll.grid(row=9, column=2, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(9, weight=1)

    # -- libxmp check -------------------------------------------------
    def _check_libxmp(self):
        try:
            find_libxmp()
        except SystemExit:
            messagebox.showwarning(
                "libxmp not found",
                "Tracker Export needs the libxmp library, which wasn't found "
                "on this system.\n\n" + libxmp_install_hint() +
                "\n\nExports will fail until it is installed.")

    # -- file picking --------------------------------------------------
    def _browse_input(self):
        path = filedialog.askopenfilename(title="Choose a tracker module",
                                          filetypes=MODULE_TYPES)
        if path:
            self.input_var.set(path)

    def _browse_outdir(self):
        path = filedialog.askdirectory(title="Choose output folder")
        if path:
            self.outdir_var.set(path)

    # -- export ---------------------------------------------------------
    def _log(self, msg):
        self._ui_queue.put(("log", msg))

    def _progress(self, frac, label):
        self._ui_queue.put(("progress", frac, label))

    def _start_export(self):
        src = self.input_var.get().strip()
        if not src or not os.path.isfile(src):
            messagebox.showerror("No module",
                                 "Pick a tracker module file first.")
            return
        try:
            sr = int(self.sr_var.get())
        except ValueError:
            sr = 44100
        outdir = self.outdir_var.get().strip() or None
        if outdir and not os.path.isdir(outdir):
            messagebox.showerror("Bad output folder",
                                 "That output folder doesn't exist.")
            return
        self.export_btn.configure(state=tk.DISABLED)
        self.cancel_btn.configure(state=tk.NORMAL)
        self.reveal_btn.configure(state=tk.DISABLED)
        self._export_dir = None
        self._cancel_event.clear()
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)
        args = dict(
            input_path=src, outdir=outdir, sample_rate=sr,
            do_stems=self.stems_var.get(), do_samples=self.samples_var.get(),
            on_log=self._log, on_progress=self._progress,
            cancel=self._cancel_event.is_set,
        )
        self._worker = threading.Thread(target=self._run_export,
                                        args=(args,), daemon=True)
        self._worker.start()

    def _run_export(self, args):
        try:
            export_dir = export_module(**args)
            self._ui_queue.put(("done", export_dir))
        except ExportCancelled:
            self._ui_queue.put(("cancelled",))
        except SystemExit as e:
            self._ui_queue.put(("error", str(e)))
        except Exception as e:  # noqa: BLE001 - show it in the GUI
            self._ui_queue.put(("error", f"{type(e).__name__}: {e}"))

    def _cancel(self):
        self._cancel_event.set()
        self._log("Cancelling…")

    def _reveal(self):
        if not self._export_dir or not os.path.isdir(self._export_dir):
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", self._export_dir])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer", self._export_dir])
        else:
            subprocess.Popen(["xdg-open", self._export_dir])

    # -- UI thread pump ---------------------------------------------------
    def _pump_queue(self):
        try:
            while True:
                item = self._ui_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    self.log_text.configure(state=tk.NORMAL)
                    self.log_text.insert(tk.END, item[1] + "\n")
                    self.log_text.see(tk.END)
                    self.log_text.configure(state=tk.DISABLED)
                elif kind == "progress":
                    _, frac, label = item
                    self.prog_var.set(frac * 100)
                    self.prog_label.set(label or "Working…")
                elif kind == "done":
                    self._export_dir = item[1]
                    self.prog_var.set(100)
                    self.prog_label.set("Done.")
                    self.export_btn.configure(state=tk.NORMAL)
                    self.cancel_btn.configure(state=tk.DISABLED)
                    self.reveal_btn.configure(state=tk.NORMAL)
                    messagebox.showinfo("Done",
                                        "Export finished.\n\n" + item[1])
                elif kind == "cancelled":
                    self.prog_label.set("Cancelled.")
                    self.export_btn.configure(state=tk.NORMAL)
                    self.cancel_btn.configure(state=tk.DISABLED)
                elif kind == "error":
                    self.prog_label.set("Error.")
                    self.export_btn.configure(state=tk.NORMAL)
                    self.cancel_btn.configure(state=tk.DISABLED)
                    messagebox.showerror("Export failed", item[1])
        except queue.Empty:
            pass
        self.after(100, self._pump_queue)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

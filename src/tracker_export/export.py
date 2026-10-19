"""High-level export: folder layout, naming, manifest, sample-rate conventions."""

import os
import re
import shutil

from .audio import describe_loop, sample_to_pcm16, write_wav
from .engine import XMP_SAMPLE_16BIT, XMP_SAMPLE_STEREO, XmpEngine, find_libxmp


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------

def sanitize(name, default="untitled", maxlen=60):
    name = (name or "").strip()
    name = re.sub(r"[^\w\-. ]", "_", name, flags=re.UNICODE)
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"_+", "_", name).strip("._")
    if not name:
        name = default
    return name[:maxlen]


def unique_path(directory, filename):
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    n = 2
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base}_{n}{ext}")
        n += 1
    return candidate


# ---------------------------------------------------------------------------
# Sample pitch conventions per format
# ---------------------------------------------------------------------------

def sample_rate_convention(filename, mod_type):
    """Return (rate_hz, unity_midi_note, note_name, description)."""
    ext = os.path.splitext(filename)[1].lower()
    t = (mod_type or "").lower()
    if ext in (".mod", ".nst", ".m15") or "m.k." in t:
        return (8287, 36, "C-2",
                "Amiga PAL rate; sample plays at recorded pitch on C-2")
    if ext == ".xm" or "fasttracker" in t:
        return (8363, 60, "C-4", "FastTracker II convention")
    if ext == ".s3m" or "scream tracker" in t:
        return (8363, 60, "C-4", "ScreamTracker III convention")
    if ext == ".it" or "impulse tracker" in t:
        return (8363, 60, "C-4", "Impulse Tracker convention")
    return (8363, 60, "C-4",
            "fallback convention (format not in rate table)")


def sample_label(s, info):
    """Best human label for a sample: sample name -> instrument name -> fallback."""
    idx = s["index"]
    label = s["name"]
    via = "sample name"
    if not label:
        insts = [i for i in dict.fromkeys(info["sample_to_inst"].get(idx, []))
                 if i]
        if insts:
            label = insts[0]
            via = "instrument name"
    if not label:
        label = f"sample_{idx + 1:02d}"
        via = "fallback"
    return label, via


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class ExportCancelled(Exception):
    pass


def export_module(input_path, outdir=None, sample_rate=44100,
                  do_stems=True, do_samples=True, lib_path=None,
                  max_seconds=1200, on_log=None, on_progress=None,
                  cancel=None):
    """Export a tracker module. Returns the export directory path.

    on_log(msg) receives status lines, on_progress(frac, label) receives
    0..1 progress updates, cancel() is polled and aborts the export.
    """
    log = on_log or (lambda m: None)

    def prog(frac, label=""):
        if on_progress is not None:
            on_progress(max(0.0, min(1.0, frac)), label)

    if not os.path.isfile(input_path):
        raise SystemExit(f"error: file not found: {input_path}")
    with open(input_path, "rb") as f:
        blob = f.read()
    if len(blob) < 64:
        raise SystemExit("error: file too small to be a tracker module")

    engine = XmpEngine(find_libxmp(lib_path))
    try:
        info = engine.load(blob)
    except RuntimeError as e:
        raise SystemExit(
            f"error: {e}\n"
            f"({os.path.basename(input_path)} is not a format libxmp can play)")

    base = os.path.splitext(os.path.basename(input_path))[0]
    folder_name = sanitize(info["title"] or base,
                           default=sanitize(base)) + "_export"
    root = outdir or os.path.dirname(os.path.abspath(input_path))
    export_dir = unique_path(root, folder_name)
    os.makedirs(export_dir)
    stems_dir = os.path.join(export_dir, "stems")
    samples_dir = os.path.join(export_dir, "samples")
    os.makedirs(stems_dir, exist_ok=True)
    os.makedirs(samples_dir, exist_ok=True)

    log(f"Module : {info['title'] or '(untitled)'} [{info['type']}]")
    log(f"Stats  : {info['channels']} channels, "
        f"{info['instruments']} instruments, "
        f"{info['samples']} sample slots, "
        f"{info['patterns']} patterns")
    log(f"Export : {export_dir}")

    shutil.copy2(input_path,
                 os.path.join(export_dir, os.path.basename(input_path)))
    log("Copied original module.")

    # Preserve any text hidden in the module (title, song message,
    # instrument/sample names) as messages.txt alongside the audio.
    msg_parts = module_text_parts(info)
    wrote_messages = False
    if msg_parts:
        with open(os.path.join(export_dir, "messages.txt"), "w") as f:
            f.write(format_module_text(info,
                                       os.path.basename(input_path)))
        wrote_messages = True
        log(f"Messages preserved ({', '.join(msg_parts)}) "
            f"-> messages.txt")

    # progress accounting: 1 unit per render + 1 per sample file
    nonempty = [s for s in info["sample_list"] if s["len"] > 0 and s["raw"]]
    units = []
    units.append(("mix", None))
    if do_stems:
        units += [(f"stem ch{ch + 1}", ch) for ch in range(info["channels"])]
    total_units = len(units) + (len(nonempty) if do_samples else 0)
    done_units = 0

    def render_one(label, solo_channel):
        nonlocal done_units
        log(f"Rendering {label} ({sample_rate} Hz stereo)...")

        def pcb(frac):
            prog((done_units + frac) / total_units, label)

        pcm, truncated, ended_by, was_cancelled = engine.render(
            info, sample_rate, solo_channel=solo_channel,
            max_seconds=max_seconds, progress_cb=pcb, cancel=cancel)
        if was_cancelled:
            raise ExportCancelled()
        secs = len(pcm) / 4 / sample_rate if sample_rate else 0
        log(f"  {label}: {secs:.1f}s (stopped: {ended_by}"
            f"{', truncated' if truncated else ''})")
        done_units += 1
        prog(done_units / total_units, label)
        return pcm

    try:
        pcm = render_one("mix", None)
        write_wav(os.path.join(export_dir, "mix.wav"), pcm, 2, sample_rate)

        stem_files = []
        if do_stems:
            for ch in range(info["channels"]):
                pcm = render_one(f"stem ch{ch + 1:02d}", ch)
                name = f"ch{ch + 1:02d}.wav"
                write_wav(os.path.join(stems_dir, name), pcm, 2, sample_rate)
                stem_files.append(name)
            log(f"{len(stem_files)} stems written.")

        rate, unity_note, note_name, rate_note = sample_rate_convention(
            input_path, info["type"])
        sample_files = []
        sample_rows = []
        skipped_empty = info["samples"] - len(nonempty)
        if do_samples:
            for s in info["sample_list"]:
                if cancel is not None and cancel():
                    raise ExportCancelled()
                idx = s["index"]
                if s["len"] <= 0 or not s["raw"]:
                    sample_rows.append((idx, "-", "empty slot", 0, "none"))
                    continue
                label, via = sample_label(s, info)
                pcm16, nch = sample_to_pcm16(s["raw"], s["flg"])
                loop_desc, loop = describe_loop(s["flg"], s["lps"], s["lpe"])
                fname = (f"{idx + 1:02d}_"
                         f"{sanitize(label, default=f'sample_{idx + 1:02d}')}.wav")
                fpath = unique_path(samples_dir, fname)
                write_wav(fpath, pcm16, nch, rate, loop=loop,
                          unity_note=unity_note)
                sample_files.append(os.path.basename(fpath))
                sample_rows.append(
                    (idx, os.path.basename(fpath), label, s["len"], loop_desc,
                     via, "16-bit" if s["flg"] & XMP_SAMPLE_16BIT else "8-bit",
                     "stereo" if nch == 2 else "mono"))
                done_units += 1
                prog(done_units / total_units,
                     f"sample {idx + 1}/{info['samples']}")
            log(f"{len(sample_files)} samples bounced "
                f"({skipped_empty} empty slots skipped).")
    finally:
        engine.unload(info)

    manifest = [
        "tracker_export manifest",
        "========================",
        f"source file : {os.path.basename(input_path)}",
        f"title       : {info['title'] or '(untitled)'}",
        f"format      : {info['type']}",
        f"channels    : {info['channels']}",
        f"instruments : {info['instruments']}",
        f"samples     : {info['samples']} slots "
        f"({len(sample_files)} bounced, {skipped_empty} empty)",
        f"patterns    : {info['patterns']}",
        f"render      : {sample_rate} Hz, 16-bit stereo WAV",
        *(["messages    : messages.txt (title, song message, "
           "instrument/sample names)"] if wrote_messages else []),
        "",
        f"sample pitch convention: {rate} Hz, unity note {note_name} "
        f"(MIDI {unity_note})",
        f"  ({rate_note}.)",
        "  Loop points are embedded in each WAV's smpl chunk.",
        "",
        "mix.wav = full mix",
    ]
    if stem_files:
        manifest.append("stems/  = one file per tracker channel "
                        f"({', '.join(stem_files)})")
    if sample_rows:
        manifest.append("")
        manifest.append("samples/  idx | file | label | frames | bitdepth | "
                        "ch | loop | label source")
        for row in sample_rows:
            manifest.append("  " + " | ".join(str(c) for c in row))
    manifest.append("")
    with open(os.path.join(export_dir, "manifest.txt"), "w") as f:
        f.write("\n".join(manifest) + "\n")
    log("Wrote manifest.txt.")
    prog(1.0, "done")
    log(f"Done. Everything is in:\n  {export_dir}")
    return export_dir


# ---------------------------------------------------------------------------
# Hidden text: titles, song messages, instrument/sample names
# ---------------------------------------------------------------------------

def module_text_parts(info):
    """Short descriptions of the text found in a loaded module, e.g.
    ['title', 'song message', '12 instrument names', '31 sample names'].
    Empty list when the module carries no text at all."""
    parts = []
    if info.get("title"):
        parts.append("title")
    if info.get("comment"):
        parts.append("song message")
    n_inst = sum(1 for n in info.get("instrument_names", []) if n)
    if n_inst:
        parts.append(f"{n_inst} instrument name{'s' if n_inst != 1 else ''}")
    n_smp = sum(1 for s in info.get("sample_list", []) if s.get("name"))
    if n_smp:
        parts.append(f"{n_smp} sample name{'s' if n_smp != 1 else ''}")
    return parts


def format_module_text(info, source_name):
    """Render a module's hidden text as a readable document: the song
    message verbatim, then instrument and sample names in slot order
    (the classic place demo-scene authors hid greetings — read down
    the list)."""
    out = [f"messages from {source_name}",
           "=" * 60,
           f"title   : {info.get('title') or '(untitled)'}",
           f"format  : {info.get('type') or ''}"]
    if info.get("comment"):
        out += ["", "--- song message " + "-" * 42, info["comment"]]
    inst = info.get("instrument_names", [])
    smp = [s.get("name", "") for s in info.get("sample_list", [])]
    if any(inst) and any(smp):
        out += ["", "--- instrument names " + "-" * 38]
        out += [f"{i + 1:3d}  {n}" for i, n in enumerate(inst)]
        out += ["", "--- sample names " + "-" * 42]
        out += [f"{i + 1:3d}  {n}" for i, n in enumerate(smp)]
    elif any(inst) or any(smp):
        # Sample-based formats (MOD/S3M...) keep their text in one list.
        names = inst if any(inst) else smp
        out += ["", "--- instrument & sample names " + "-" * 29]
        out += [f"{i + 1:3d}  {n}" for i, n in enumerate(names)]
    return "\n".join(out) + "\n"


def read_module_text(input_path, lib_path=None):
    """Load a module just to read its hidden text. Returns
    (info_dict, formatted_text). Raises RuntimeError/SystemExit like
    the other loaders when the file cannot be read."""
    if not os.path.isfile(input_path):
        raise SystemExit(f"error: file not found: {input_path}")
    with open(input_path, "rb") as f:
        blob = f.read()
    if len(blob) < 64:
        raise SystemExit("error: file too small to be a tracker module")
    engine = XmpEngine(find_libxmp(lib_path))
    try:
        info = engine.load(blob)
        text = format_module_text(info, os.path.basename(input_path))
        parts = module_text_parts(info)
    finally:
        engine.unload(info)
    return {"title": info["title"], "type": info["type"],
            "comment": info["comment"], "parts": parts}, text


# ---------------------------------------------------------------------------
# Batch export + directory crawling
# ---------------------------------------------------------------------------

#: Extensions recognised as tracker modules when crawling directories.
#: Files that turn out not to load are skipped by the batch runner,
#: so an over-inclusive list is harmless.
MODULE_EXTENSIONS = {
    ".mod", ".s3m", ".xm", ".it", ".stm", ".mtm", ".669", ".amf", ".ult",
    ".dmf", ".okt", ".med", ".dbm", ".mdl", ".mptm", ".nst", ".m15",
    ".imf", ".far", ".ptm", ".umx", ".sfx", ".gdm", ".dsm", ".j2b",
    ".psm", ".digi", ".dtm", ".emod", ".fls", ".fnk", ".gtk", ".gt2",
    ".liq", ".m15", ".mgt", ".mmdc", ".np", ".om", ".plm", ".rtm",
    ".smod", ".st26", ".xann", ".xm15",
}


def is_module_filename(name):
    return os.path.splitext(name)[1].lower() in MODULE_EXTENSIONS


def collect_modules(inputs, recursive=True):
    """Expand a mix of files and directories into module file paths.

    Directories are crawled (recursively unless recursive=False);
    hidden files/folders are skipped. Plain files pass through as-is.
    Returns a de-duplicated, order-preserving list.
    """
    found = []

    def add(path):
        ap = os.path.abspath(path)
        if ap not in found:
            found.append(ap)

    for inp in inputs:
        if os.path.isdir(inp):
            if recursive:
                for root, dirs, files in os.walk(inp):
                    dirs[:] = sorted(d for d in dirs
                                     if not d.startswith("."))
                    for f in sorted(files):
                        if not f.startswith(".") and is_module_filename(f):
                            add(os.path.join(root, f))
            else:
                for f in sorted(os.listdir(inp)):
                    p = os.path.join(inp, f)
                    if (os.path.isfile(p) and not f.startswith(".")
                            and is_module_filename(f)):
                        add(p)
        elif os.path.isfile(inp):
            add(inp)
    return found


def export_batch(files, outdir=None, sample_rate=44100,
                 do_stems=True, do_samples=True, lib_path=None,
                 max_seconds=1200, on_log=None, on_progress=None,
                 cancel=None):
    """Export every file in `files`; one bad file never stops the batch.

    Returns (exported_dirs, failures) where failures is a list of
    (path, reason) tuples. on_progress receives overall 0..1 progress
    with a human label.
    """
    log = on_log or (lambda m: None)
    n = len(files)
    exported = []
    failures = []
    for i, path in enumerate(files):
        if cancel is not None and cancel():
            log("Batch cancelled.")
            raise ExportCancelled()
        name = os.path.basename(path)
        log(f"--- [{i + 1}/{n}] {name} ---")

        def wrap(frac, label, i=i, name=name):
            if on_progress is not None:
                on_progress((i + frac) / n, f"{i + 1}/{n} {name}: {label}")

        try:
            d = export_module(path, outdir=outdir, sample_rate=sample_rate,
                              do_stems=do_stems, do_samples=do_samples,
                              lib_path=lib_path, max_seconds=max_seconds,
                              on_log=log, on_progress=wrap, cancel=cancel)
            exported.append(d)
        except ExportCancelled:
            raise
        except SystemExit as e:
            reason = str(e).strip().splitlines()[0] if str(e).strip() \
                else "unloadable"
            failures.append((path, reason))
            log(f"  SKIPPED {name}: {reason}")
        except Exception as e:  # noqa: BLE001 - keep batch alive
            failures.append((path, f"{type(e).__name__}: {e}"))
            log(f"  FAILED {name}: {type(e).__name__}: {e}")
    log(f"Batch complete: {len(exported)} exported, "
        f"{len(failures)} skipped/failed, {n} total.")
    if on_progress is not None:
        on_progress(1.0, "batch done")
    return exported, failures


def print_info(input_path, lib_path=None):
    with open(input_path, "rb") as f:
        blob = f.read()
    engine = XmpEngine(find_libxmp(lib_path))
    try:
        info = engine.load(blob)
    except RuntimeError as e:
        raise SystemExit(f"error: {e}")
    lines = [
        f"Title      : {info['title'] or '(untitled)'}",
        f"Format     : {info['type']}",
        f"Channels   : {info['channels']}",
        f"Instruments: {info['instruments']}",
        f"Samples    : {info['samples']}",
        f"Patterns   : {info['patterns']}",
        "Sample slots:",
    ]
    for s in info["sample_list"]:
        label, _ = sample_label(s, info)
        loop_desc, _ = describe_loop(s["flg"], s["lps"], s["lpe"])
        lines.append(
            f"  [{s['index'] + 1:2d}] {label or '(no name)':30.30s} "
            f"len={s['len']:6d} loop={loop_desc} "
            f"{'16bit' if s['flg'] & XMP_SAMPLE_16BIT else '8bit'}"
            f"{' stereo' if s['flg'] & XMP_SAMPLE_STEREO else ''}")
    engine.unload(info)
    parts = module_text_parts(info)
    if parts:
        lines.append("")
        lines.append(format_module_text(info, os.path.basename(input_path)))
    return "\n".join(lines)

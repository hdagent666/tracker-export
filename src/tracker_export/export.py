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
    return "\n".join(lines)

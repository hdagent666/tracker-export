"""libxmp access via ctypes. Stdlib only — no compiled extensions needed."""

import ctypes
import ctypes.util
import os
import sys

# ---------------------------------------------------------------------------
# Finding the libxmp shared library
# ---------------------------------------------------------------------------

_LIBXMP_CANDIDATES = [
    "libxmp.so.4",
    "libxmp.so",
    "libxmp.4.dylib",
    "libxmp.dylib",
    "xmp",
]

_INSTALL_HINT = (
    "Install it first:\n"
    "  macOS:          brew install libxmp\n"
    "  Ubuntu/Debian:  sudo apt install libxmp4\n"
    "  Fedora:         sudo dnf install libxmp\n"
    "  Arch:           sudo pacman -S libxmp"
)


def _bundle_dirs():
    """Extra places to look (frozen apps, .app bundles)."""
    dirs = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(meipass)
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    # macOS .app layout: Contents/MacOS/<exe>, dylib in Contents/Frameworks
    for cand in (
        exe_dir,
        os.path.join(exe_dir, "..", "Frameworks"),
        os.path.join(exe_dir, "..", "Resources"),
    ):
        cand = os.path.normpath(cand)
        if os.path.isdir(cand):
            dirs.append(cand)
    return dirs


def find_libxmp(user_path=None):
    """Locate the libxmp shared library; raise SystemExit with help if absent."""
    if user_path:
        if os.path.isfile(user_path):
            return user_path
        raise SystemExit(f"error: libxmp not found at {user_path}")
    env = os.environ.get("LIBXMP_PATH")
    if env and os.path.isfile(env):
        return env
    for d in _bundle_dirs():
        for name in ("libxmp.so.4", "libxmp.so", "libxmp.4.dylib",
                     "libxmp.dylib"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    found = ctypes.util.find_library("xmp")
    if found:
        return found
    for name in _LIBXMP_CANDIDATES:
        try:
            ctypes.CDLL(name)
            return name
        except OSError:
            continue
    raise SystemExit(
        "error: could not find the libxmp shared library.\n" + _INSTALL_HINT
    )


def libxmp_install_hint():
    return _INSTALL_HINT


# ---------------------------------------------------------------------------
# ctypes bindings (struct layouts verified against libxmp 4.6.x xmp.h)
# ---------------------------------------------------------------------------

XMP_MAX_CHANNELS = 64
XMP_MAX_MOD_LENGTH = 256
XMP_NAME_SIZE = 64
XMP_MAX_KEYS = 121

XMP_SAMPLE_16BIT = 1 << 0
XMP_SAMPLE_LOOP = 1 << 1
XMP_SAMPLE_LOOP_BIDIR = 1 << 2
XMP_SAMPLE_LOOP_REVERSE = 1 << 3
XMP_SAMPLE_LOOP_FULL = 1 << 4
XMP_SAMPLE_SLOOP = 1 << 5
XMP_SAMPLE_SLOOP_BIDIR = 1 << 6
XMP_SAMPLE_STEREO = 1 << 7

XMP_END = 1


class _XmpSample(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char * 32),
                ("len", ctypes.c_int),
                ("lps", ctypes.c_int),
                ("lpe", ctypes.c_int),
                ("flg", ctypes.c_int),
                ("data", ctypes.POINTER(ctypes.c_ubyte))]


class _XmpChannel(ctypes.Structure):
    _fields_ = [("pan", ctypes.c_int),
                ("vol", ctypes.c_int),
                ("flg", ctypes.c_int)]


class _XmpModule(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char * XMP_NAME_SIZE),
                ("type", ctypes.c_char * XMP_NAME_SIZE),
                ("pat", ctypes.c_int), ("trk", ctypes.c_int),
                ("chn", ctypes.c_int), ("ins", ctypes.c_int),
                ("smp", ctypes.c_int), ("spd", ctypes.c_int),
                ("bpm", ctypes.c_int), ("len", ctypes.c_int),
                ("rst", ctypes.c_int), ("gvl", ctypes.c_int),
                ("xxp", ctypes.c_void_p), ("xxt", ctypes.c_void_p),
                ("xxi", ctypes.c_void_p), ("xxs", ctypes.POINTER(_XmpSample)),
                ("xxc", _XmpChannel * XMP_MAX_CHANNELS),
                ("xxo", ctypes.c_ubyte * XMP_MAX_MOD_LENGTH)]


class _XmpModuleInfo(ctypes.Structure):
    _fields_ = [("md5", ctypes.c_ubyte * 16),
                ("vol_base", ctypes.c_int),
                ("mod", ctypes.POINTER(_XmpModule)),
                ("comment", ctypes.c_char_p),
                ("num_sequences", ctypes.c_int),
                ("seq_data", ctypes.c_void_p)]


class _XmpChannelInfo(ctypes.Structure):
    _fields_ = [("period", ctypes.c_uint),
                ("position", ctypes.c_uint),
                ("pitchbend", ctypes.c_short),
                ("note", ctypes.c_ubyte),
                ("instrument", ctypes.c_ubyte),
                ("sample", ctypes.c_ubyte),
                ("volume", ctypes.c_ubyte),
                ("pan", ctypes.c_ubyte),
                ("reserved", ctypes.c_ubyte),
                ("event", ctypes.c_ubyte * 8)]


class _XmpFrameInfo(ctypes.Structure):
    _fields_ = [("pos", ctypes.c_int), ("pattern", ctypes.c_int),
                ("row", ctypes.c_int), ("num_rows", ctypes.c_int),
                ("frame", ctypes.c_int), ("speed", ctypes.c_int),
                ("bpm", ctypes.c_int), ("time", ctypes.c_int),
                ("total_time", ctypes.c_int), ("frame_time", ctypes.c_int),
                ("buffer", ctypes.c_void_p), ("buffer_size", ctypes.c_int),
                ("total_size", ctypes.c_int), ("volume", ctypes.c_int),
                ("loop_count", ctypes.c_int), ("virt_channels", ctypes.c_int),
                ("virt_used", ctypes.c_int), ("sequence", ctypes.c_int),
                ("channel_info", _XmpChannelInfo * XMP_MAX_CHANNELS)]


class _XmpSubInstrument(ctypes.Structure):
    _fields_ = [("vol", ctypes.c_int), ("gvl", ctypes.c_int),
                ("pan", ctypes.c_int), ("xpo", ctypes.c_int),
                ("fin", ctypes.c_int), ("vwf", ctypes.c_int),
                ("vde", ctypes.c_int), ("vra", ctypes.c_int),
                ("vsw", ctypes.c_int), ("rvv", ctypes.c_int),
                ("sid", ctypes.c_int), ("nna", ctypes.c_int),
                ("dct", ctypes.c_int), ("dca", ctypes.c_int),
                ("ifc", ctypes.c_int), ("ifr", ctypes.c_int)]


class _XmpInstrumentMapEntry(ctypes.Structure):
    _fields_ = [("ins", ctypes.c_ubyte), ("xpo", ctypes.c_byte)]


class _XmpEnvelope(ctypes.Structure):
    _fields_ = [("flg", ctypes.c_int), ("npt", ctypes.c_int),
                ("scl", ctypes.c_int), ("sus", ctypes.c_int),
                ("sue", ctypes.c_int), ("lps", ctypes.c_int),
                ("lpe", ctypes.c_int),
                ("data", ctypes.c_short * (32 * 2))]


class _XmpInstrument(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char * 32),
                ("vol", ctypes.c_int), ("nsm", ctypes.c_int),
                ("rls", ctypes.c_int),
                ("aei", _XmpEnvelope), ("pei", _XmpEnvelope),
                ("fei", _XmpEnvelope),
                ("map", _XmpInstrumentMapEntry * XMP_MAX_KEYS),
                ("sub", ctypes.POINTER(_XmpSubInstrument)),
                ("extra", ctypes.c_void_p)]


def _clean_text(raw):
    if not raw:
        return ""
    if isinstance(raw, bytes):
        text = raw.split(b"\x00")[0].decode("latin-1", "replace")
    else:
        text = str(raw)
    return "".join(c for c in text if c.isprintable()).strip()


def _clean_slot_name(raw):
    """Clean a name slot the way FT2 displays it in its top-right
    square: the author's own layout spaces are kept, only trailing
    padding is dropped."""
    if not raw:
        return ""
    if isinstance(raw, bytes):
        text = raw.split(b"\x00")[0].decode("latin-1", "replace")
    else:
        text = str(raw)
    return "".join(c for c in text if c.isprintable()).rstrip()


def _clean_comment(raw):
    """Clean a module comment/song message, preserving line breaks."""
    if not raw:
        return ""
    if isinstance(raw, bytes):
        text = raw.split(b"\x00")[0].decode("latin-1", "replace")
    else:
        text = str(raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in text.split("\n"):
        line = "".join(c for c in line if c.isprintable() or c == "\t")
        lines.append(line.rstrip())
    return "\n".join(lines).strip("\n").strip()


class XmpEngine:
    """Thin wrapper around libxmp."""

    def __init__(self, lib_path):
        self.lib = ctypes.CDLL(lib_path)
        L = self.lib
        L.xmp_create_context.restype = ctypes.c_void_p
        L.xmp_free_context.argtypes = [ctypes.c_void_p]
        L.xmp_load_module_from_memory.argtypes = [ctypes.c_void_p,
                                                 ctypes.c_void_p, ctypes.c_long]
        L.xmp_load_module_from_memory.restype = ctypes.c_int
        L.xmp_release_module.argtypes = [ctypes.c_void_p]
        L.xmp_get_module_info.argtypes = [ctypes.c_void_p,
                                         ctypes.POINTER(_XmpModuleInfo)]
        L.xmp_start_player.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                       ctypes.c_int]
        L.xmp_start_player.restype = ctypes.c_int
        L.xmp_play_frame.argtypes = [ctypes.c_void_p]
        L.xmp_play_frame.restype = ctypes.c_int
        L.xmp_get_frame_info.argtypes = [ctypes.c_void_p,
                                        ctypes.POINTER(_XmpFrameInfo)]
        L.xmp_end_player.argtypes = [ctypes.c_void_p]
        L.xmp_channel_mute.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                      ctypes.c_int]
        L.xmp_channel_mute.restype = ctypes.c_int

    # -- loading ------------------------------------------------------
    def load(self, blob):
        """Load a module from bytes; returns an info dict (context freed
        separately via unload())."""
        ctx = self.lib.xmp_create_context()
        if not ctx:
            raise RuntimeError("xmp_create_context failed")
        rc = self.lib.xmp_load_module_from_memory(ctx, blob, len(blob))
        if rc != 0:
            self.lib.xmp_free_context(ctx)
            raise RuntimeError(
                f"not a loadable tracker module (libxmp error {rc})")
        mi = _XmpModuleInfo()
        self.lib.xmp_get_module_info(ctx, ctypes.byref(mi))
        mod = mi.mod.contents
        info = {
            "ctx": ctx,
            "blob": blob,  # keep alive while context exists
            "title": _clean_text(mod.name),
            "comment": _clean_comment(mi.comment),
            "type": _clean_text(mod.type),
            "channels": mod.chn,
            "instruments": mod.ins,
            "samples": mod.smp,
            "patterns": mod.pat,
            "length_orders": mod.len,
        }
        samples = []
        for i in range(mod.smp):
            s = mod.xxs[i]
            nbytes = s.len * (2 if s.flg & XMP_SAMPLE_16BIT else 1) \
                * (2 if s.flg & XMP_SAMPLE_STEREO else 1)
            raw = bytes(ctypes.string_at(s.data, nbytes)) \
                if s.len > 0 and s.data else b""
            samples.append({
                "index": i,
                "name": _clean_text(s.name),
                "len": s.len,
                "lps": s.lps,
                "lpe": s.lpe,
                "flg": s.flg,
                "raw": raw,
            })
        inst_names = []
        inst_slots = []
        sample_to_inst = {}
        if mod.xxi:
            insts = ctypes.cast(mod.xxi, ctypes.POINTER(_XmpInstrument))
            for i in range(mod.ins):
                xi = insts[i]
                nm = _clean_text(xi.name)
                inst_names.append(nm)
                inst_slots.append(_clean_slot_name(xi.name))
                if xi.sub and xi.nsm > 0:
                    for j in range(xi.nsm):
                        sid = xi.sub[j].sid
                        sample_to_inst.setdefault(sid, []).append(
                            nm or f"instrument {i + 1}")
        info["sample_list"] = samples
        info["instrument_names"] = inst_names
        info["instrument_slots"] = inst_slots
        info["sample_slots"] = [_clean_slot_name(mod.xxs[i].name)
                                for i in range(mod.smp)]
        info["sample_to_inst"] = sample_to_inst
        return info

    def unload(self, info):
        self.lib.xmp_release_module(info["ctx"])
        self.lib.xmp_free_context(info["ctx"])

    # -- rendering ----------------------------------------------------
    def render(self, info, sample_rate=44100, solo_channel=None,
               max_seconds=1200, progress_cb=None, cancel=None):
        """Render mix (or one soloed channel) to raw stereo int16 bytes.

        progress_cb(frac) is called with 0..1 as rendering proceeds;
        cancel() is polled and aborts cleanly when it returns True.
        Returns (pcm_bytes, truncated, ended_by).
        """
        L = self.lib
        ctx = L.xmp_create_context()
        rc = L.xmp_load_module_from_memory(ctx, info["blob"], len(info["blob"]))
        if rc != 0:
            L.xmp_free_context(ctx)
            raise RuntimeError("reload failed during render")
        try:
            if L.xmp_start_player(ctx, sample_rate, 0) != 0:
                raise RuntimeError("xmp_start_player failed")
            if solo_channel is not None:
                # NOTE: mute only takes effect after start_player
                for ch in range(info["channels"]):
                    rc = L.xmp_channel_mute(
                        ctx, ch, 0 if ch == solo_channel else 1)
                    if rc < 0:
                        raise RuntimeError(f"xmp_channel_mute failed (rc={rc})")
            out = bytearray()
            fi = _XmpFrameInfo()
            truncated = False
            cancelled = False
            ended_by = "end"
            frames = 0
            while True:
                if cancel is not None and cancel():
                    cancelled = True
                    ended_by = "cancelled"
                    break
                rc = L.xmp_play_frame(ctx)
                L.xmp_get_frame_info(ctx, ctypes.byref(fi))
                if fi.buffer_size > 0:
                    out += ctypes.string_at(fi.buffer, fi.buffer_size)
                frames += 1
                if progress_cb is not None and frames % 16 == 0:
                    total = fi.total_time if fi.total_time > 0 else 1
                    progress_cb(min(0.99, fi.time / total))
                if rc != 0:
                    ended_by = "end" if rc == XMP_END else f"player error {rc}"
                    break
                if fi.loop_count > 0:
                    ended_by = "loop"
                    break
                if fi.time > max_seconds * 1000:
                    truncated = True
                    ended_by = "time-cap"
                    break
            if progress_cb is not None:
                progress_cb(1.0)
            return bytes(out), truncated, ended_by, cancelled
        finally:
            L.xmp_end_player(ctx)
            L.xmp_release_module(ctx)
            L.xmp_free_context(ctx)

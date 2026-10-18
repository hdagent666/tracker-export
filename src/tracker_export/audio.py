"""WAV writing (16-bit PCM + smpl chunk for loop points) and sample conversion."""

import array
import struct
import sys

from .engine import (XMP_SAMPLE_16BIT, XMP_SAMPLE_LOOP, XMP_SAMPLE_LOOP_BIDIR,
                     XMP_SAMPLE_LOOP_REVERSE, XMP_SAMPLE_SLOOP,
                     XMP_SAMPLE_SLOOP_BIDIR, XMP_SAMPLE_STEREO)


def write_wav(path, pcm16_bytes, nchannels, sample_rate,
              loop=None, unity_note=60):
    """Write 16-bit PCM WAV. loop = (start, end, pingpong_bool) or None."""
    data = pcm16_bytes
    chunks = []
    byte_rate = sample_rate * nchannels * 2
    chunks.append(b"fmt " + struct.pack("<I", 16) +
                  struct.pack("<HHIIHH", 1, nchannels, sample_rate,
                              byte_rate, nchannels * 2, 16))
    if loop is not None:
        start, end, pingpong = loop
        period_ns = int(round(1e9 / sample_rate))
        body = struct.pack("<9I", 0, 0, period_ns, unity_note, 0, 0, 0, 1, 0)
        body += struct.pack("<6I", 0, 1 if pingpong else 0,
                            start, end, 0, 0)
        chunks.append(b"smpl" + struct.pack("<I", len(body)) + body)
    chunks.append(b"data" + struct.pack("<I", len(data)) + data)
    riff_body = b"WAVE" + b"".join(chunks)
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(riff_body)) + riff_body)


def sample_to_pcm16(raw, flg):
    """Convert libxmp sample data (signed 8-bit / signed 16-bit LE,
    interleaved if stereo) to (pcm16_bytes, nchannels)."""
    is16 = bool(flg & XMP_SAMPLE_16BIT)
    stereo = bool(flg & XMP_SAMPLE_STEREO)
    nchannels = 2 if stereo else 1
    if not raw:
        return b"", nchannels
    if is16:
        a = array.array("h")
        a.frombytes(raw)
        if sys.byteorder != "little":
            a.byteswap()
        return a.tobytes(), nchannels
    b = array.array("b", raw)  # signed 8-bit
    a = array.array("h", (v << 8 for v in b))
    return a.tobytes(), nchannels


def describe_loop(flg, lps, lpe):
    """Return (human-readable description, wav-loop-tuple-or-None)."""
    if flg & XMP_SAMPLE_LOOP:
        kind = "ping-pong" if (flg & XMP_SAMPLE_LOOP_BIDIR) else "forward"
        if flg & XMP_SAMPLE_LOOP_REVERSE:
            kind = "reverse"
        return (f"{kind} {lps}-{lpe}",
                (lps, lpe, bool(flg & XMP_SAMPLE_LOOP_BIDIR)))
    if flg & XMP_SAMPLE_SLOOP:
        kind = ("sustain ping-pong"
                if (flg & XMP_SAMPLE_SLOOP_BIDIR) else "sustain")
        return (f"{kind} {lps}-{lpe}",
                (lps, lpe, bool(flg & XMP_SAMPLE_SLOOP_BIDIR)))
    return "none", None

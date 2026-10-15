"""PCM / WAV helpers and the chunker. Everything stays in memory."""
from __future__ import annotations

import io
import wave

import numpy as np

from config import CHUNK_BYTES, MIN_FLUSH_BYTES, SAMPLE_RATE


def pcm_to_wav(pcm: bytes, channels: int = 1) -> bytes:
    """Raw 16 kHz int16 PCM -> WAV file bytes, entirely in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def rms(pcm: bytes) -> float:
    if not pcm:
        return 0.0
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    return float(np.sqrt(np.mean(a * a)))


def load_wav_channels(path: str) -> list[bytes]:
    """Read any PCM WAV; return one 16 kHz int16 mono byte string per channel (linear resample)."""
    with wave.open(path, "rb") as w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        raise ValueError(f"unsupported WAV sample width: {width} bytes")
    a = np.frombuffer(raw, dtype=dtype).astype(np.float64)
    if width == 1:
        a = (a - 128) * 256
    elif width == 4:
        a /= 65536
    a = a[: len(a) // ch * ch].reshape(-1, ch)
    out = []
    for c in range(ch):
        x = a[:, c]
        if rate != SAMPLE_RATE and len(x):
            t_new = np.arange(int(len(x) * SAMPLE_RATE / rate)) * rate / SAMPLE_RATE
            x = np.interp(t_new, np.arange(len(x)), x)
        out.append(np.clip(x, -32768, 32767).astype(np.int16).tobytes())
    return out


def load_wav_16k_mono(path: str) -> bytes:
    """Any PCM WAV -> 16 kHz mono int16 bytes (channels averaged)."""
    chans = [np.frombuffer(c, dtype=np.int16).astype(np.float64) for c in load_wav_channels(path)]
    return np.mean(chans, axis=0).astype(np.int16).tobytes() if len(chans) > 1 else chans[0].astype(np.int16).tobytes()


class Chunker:
    """Accumulates PCM and yields exact 4-second chunks."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def push(self, pcm: bytes) -> list[bytes]:
        self.buf += pcm
        out = []
        while len(self.buf) >= CHUNK_BYTES:
            out.append(bytes(self.buf[:CHUNK_BYTES]))
            del self.buf[:CHUNK_BYTES]
        return out

    def tail(self) -> bytes | None:
        t = bytes(self.buf) if len(self.buf) >= MIN_FLUSH_BYTES else None
        self.buf.clear()
        return t

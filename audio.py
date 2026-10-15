"""PCM / WAV helpers and the chunker. Everything stays in memory."""
from __future__ import annotations

import io
import wave
from collections import deque
from dataclasses import dataclass

import numpy as np

from config import SAMPLE_RATE


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


@dataclass
class Chunk:
    pcm: bytes
    start: int          # sample index (since the stream began) of the first sample
    end: int            # sample index just past the last sample
    speech_end: int     # sample index just past the last voiced frame (latency reference)

    @property
    def seconds(self) -> float:
        return (self.end - self.start) / SAMPLE_RATE


class PauseChunker:
    """Cuts a 16 kHz int16 stream at natural pauses: once at least `min_s` is buffered, the first
    `pause_ms` of quiet ends the chunk; nothing grows past `max_s` (then it cuts at the quietest
    moment in the window, so words are rarely split). Leading silence is trimmed to a short pre-roll,
    so silence costs no STT calls and chunks start right before speech."""

    FRAME_MS = 20

    def __init__(self, min_s: float = 1.5, max_s: float = 4.0, pause_ms: int = 300, preroll_ms: int = 200,
                 silence_rms: float = 120.0, min_tail_s: float = 0.5) -> None:
        self.fb = SAMPLE_RATE * self.FRAME_MS // 1000 * 2           # bytes per frame
        self.min_f = int(min_s * 1000 / self.FRAME_MS)
        self.max_f = int(max_s * 1000 / self.FRAME_MS)
        self.pause_f = max(1, pause_ms // self.FRAME_MS)
        self.preroll_f = max(0, preroll_ms // self.FRAME_MS)
        self.min_tail_f = int(min_tail_s * 1000 / self.FRAME_MS)
        self.silence_rms = silence_rms
        self.recent: deque[float] = deque(maxlen=3000 // self.FRAME_MS)   # frame RMS, last 3 s
        self.pending = bytearray()                                   # < 1 frame
        self.frames: list[bytes] = []
        self.rmsv: list[float] = []                                  # RMS of each buffered frame
        self.start = 0                                               # sample index of frames[0]
        self.total = 0                                               # samples pushed so far

    @property
    def threshold(self) -> float:
        """SILENCE_RMS, raised in a noisy room to 2x the noise floor (the quietest frame in the
        last 3 s: speech always has gaps, steady noise does not)."""
        floor = min(self.recent) if len(self.recent) >= 25 else 0.0
        return max(self.silence_rms, 2.0 * floor)

    def _flags(self) -> list[bool]:
        th = self.threshold
        return [r >= th for r in self.rmsv]

    def push(self, pcm: bytes) -> list[Chunk]:
        self.pending += pcm
        self.total += len(pcm) // 2
        out = []
        while len(self.pending) >= self.fb:
            frame = bytes(self.pending[: self.fb])
            del self.pending[: self.fb]
            c = self._add(frame)
            if c:
                out.append(c)
        return out

    def _add(self, frame: bytes) -> Chunk | None:
        r = rms(frame)
        self.recent.append(r)
        self.frames.append(frame)
        self.rmsv.append(r)
        loud = self._flags()                                         # judged against the current floor
        if not any(loud):                                            # no speech yet: keep only the pre-roll
            drop = len(self.frames) - self.preroll_f
            if drop > 0:
                del self.frames[:drop], self.rmsv[:drop]
                self.start += drop * self.fb // 2
            return None
        n = len(self.frames)
        if n >= self.max_f:
            quiet = [i for i in range(self.min_f, n) if not loud[i]]
            cut = (quiet[-1] + 1) if quiet else n                    # latest quiet frame, else hard cut
            return self._emit(cut, loud)
        if n >= self.min_f and n >= self.pause_f and not any(loud[-self.pause_f:]):
            return self._emit(n, loud)
        return None

    def _emit(self, cut: int, loud: list[bool]) -> Chunk:
        fs = self.fb // 2
        voiced = [i for i in range(cut) if loud[i]]
        last_loud = voiced[-1] if voiced else 0
        c = Chunk(b"".join(self.frames[:cut]), self.start, self.start + cut * fs, self.start + (last_loud + 1) * fs)
        del self.frames[:cut], self.rmsv[:cut]
        self.start += cut * fs
        return c

    def tail(self) -> Chunk | None:
        """Whatever is buffered, if it holds enough speech to be worth transcribing (track end, idle)."""
        loud = self._flags()
        c = None
        if self.frames and any(loud) and len(self.frames) >= self.min_tail_f:
            c = self._emit(len(self.frames), loud)
        else:
            self.start += len(self.frames) * self.fb // 2
            self.frames.clear()
            self.rmsv.clear()
        return c

    def lag_seconds(self, sample: int) -> float:
        """How long ago (in stream time) `sample` was, given everything pushed so far."""
        return max(0.0, (self.total - sample) / SAMPLE_RATE)


def chunk_stream(pcm: bytes, **kw) -> list[Chunk]:
    """Offline: chunk a whole recording exactly as the live path would."""
    ch = PauseChunker(**kw)
    out = ch.push(pcm)
    t = ch.tail()
    return out + ([t] if t else [])

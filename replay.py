"""Replay inputs: turn a WAV into timed segments, and cache their transcripts next to the WAV.

Stereo WAVs are two speakers (left = caller, right = victim; that is what --record-dir writes);
mono WAVs are one speaker. `call.wav` gets `call.transcripts.json` after the first replay with a
real STT (or straight from a recording), and later replays use it instead of any STT, which
is what makes the fallback work with no internet at all.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from audio import chunk_stream, load_wav_channels
from config import SAMPLE_RATE, Config

log = logging.getLogger("chaukanna.replay")
CACHE_FORMAT = 1
CHANNEL_SPEAKERS = ("caller", "victim")


@dataclass
class Segment:
    speaker: str
    start: float          # seconds into the file
    end: float
    speech_end: float
    pcm: bytes
    text: str | None = None
    language: str | None = None
    source: str | None = None


def cache_path(wav: str | Path) -> Path:
    p = Path(wav)
    return p.with_name(p.stem + ".transcripts.json")


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_cache(wav: str | Path) -> dict | None:
    p = cache_path(wav)
    if not p.exists():
        return None
    try:
        c = json.loads(p.read_text())
    except ValueError:
        log.warning("ignoring unreadable transcript cache %s", p)
        return None
    if c.get("format") != CACHE_FORMAT or c.get("wav_sha256") != file_sha256(wav):
        log.warning("transcript cache %s does not match the WAV (re-recorded?); ignoring it", p.name)
        return None
    return c


def _speaker_tracks(wav: str | Path, mono_speaker: str) -> dict[str, bytes]:
    chans = load_wav_channels(str(wav))
    if len(chans) == 2:
        return dict(zip(CHANNEL_SPEAKERS, chans))
    if len(chans) == 1:
        return {mono_speaker: chans[0]}
    mix = np.mean([np.frombuffer(c, dtype=np.int16).astype(np.float64) for c in chans], axis=0)
    return {mono_speaker: mix.astype(np.int16).tobytes()}


def build_segments(cfg: Config, wav: str | Path, mono_speaker: str = "caller",
                   use_cache: bool = True) -> tuple[list[Segment], bool]:
    """Segments in the order a live call would produce them (by end time). Returns (segments,
    from_cache)."""
    tracks = _speaker_tracks(wav, mono_speaker)
    cache = load_cache(wav) if use_cache else None
    segs: list[Segment] = []
    if cache:
        for s in cache["segments"]:
            pcm = tracks.get(s["speaker"]) or next(iter(tracks.values()))
            a, b = int(s["start"] * SAMPLE_RATE) * 2, int(s["end"] * SAMPLE_RATE) * 2
            segs.append(Segment(s["speaker"], s["start"], s["end"], s.get("speech_end", s["end"]), pcm[a:b],
                                s.get("text", ""), s.get("language", "en"), "cache"))
    else:
        for speaker, pcm in tracks.items():
            for c in chunk_stream(pcm, **cfg.chunker_kw()):
                segs.append(Segment(speaker, c.start / SAMPLE_RATE, c.end / SAMPLE_RATE,
                                    c.speech_end / SAMPLE_RATE, c.pcm))
    segs.sort(key=lambda s: s.end)
    return segs, cache is not None


def write_cache(wav: str | Path, segs: list[Segment], cfg: Config, extra: dict | None = None) -> Path | None:
    """Save transcripts, only when every chunk came from Sarvam: a run that fell back to the local
    whisper (or mock STT) must not become the transcript every later replay uses."""
    have = [s for s in segs if s.text is not None]
    if not have or any(s.source != "sarvam" for s in have):
        if have:
            log.info("not caching transcripts: %d of %d chunks came from %s", sum(s.source != "sarvam" for s in have),
                     len(have), "/".join(sorted({s.source for s in have if s.source != "sarvam"})))
        return None
    body = {
        "format": CACHE_FORMAT, "wav": Path(wav).name, "wav_sha256": file_sha256(wav),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "stt": f"{cfg.stt_model}/{cfg.stt_mode}", "chunking": cfg.chunker_kw(),
        "segments": [{"speaker": s.speaker, "start": round(s.start, 3), "end": round(s.end, 3),
                      "speech_end": round(s.speech_end, 3), "text": s.text or "", "language": s.language or "en",
                      "source": s.source} for s in segs if s.text is not None],
        **(extra or {}),
    }
    p = cache_path(wav)
    p.write_text(json.dumps(body, ensure_ascii=False, indent=1))
    return p

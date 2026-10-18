"""Speech-to-text engines. transcribe() returns (text, language, source); language is hi | kn | en.

  SarvamSTT    the real one (saaras:v3 over HTTPS)
  WhisperSTT   local faster-whisper on the GPU via ~/hk-voice-io; optional, imported lazily
  SttRouter    Sarvam first; on errors / 429s it opens a breaker and uses Whisper for a while
  MockSTT      canned scam script (wiring tests)
"""
from __future__ import annotations

import asyncio
import ctypes
import glob
import importlib.util
import logging
import os
import sys
import time
from pathlib import Path

import httpx
import numpy as np

from config import SARVAM_STT_URL, Config

log = logging.getLogger("chaukanna.stt")

MOCK_SCRIPT = [
    "Hello, this is Inspector Sharma from CBI Mumbai.",
    "A parcel in your name contains illegal narcotics and fake passports.",
    "You are under digital arrest. Do not tell anyone and do not disconnect the call.",
    "To verify your account, tell me the OTP that you just received.",
]

Result = tuple[str, str, str]           # text, language, source


def short_lang(code: str | None) -> str:
    c = (code or "en").split("-")[0].lower()
    if c == "ur":                       # Whisper often hears spoken Hindi as Urdu
        return "hi"
    return c if c in ("hi", "kn") else "en"


class SttError(Exception):
    def __init__(self, msg: str, status: int | None = None) -> None:
        super().__init__(msg)
        self.status = status


SarvamError = SttError                  # old name


class MockSTT:
    """Canned scam script, one line per chunk (wiring tests, no network)."""

    name = "mock"

    def __init__(self, script: list[str] | None = None, delay_ms: float | None = None) -> None:
        self.script = script or MOCK_SCRIPT
        self.i = 0
        self.delay = (float(os.getenv("MOCK_STT_DELAY_MS", "0")) if delay_ms is None else delay_ms) / 1000

    async def transcribe(self, wav: bytes, pcm: bytes) -> Result:
        if self.delay:
            await asyncio.sleep(self.delay)                   # behave like a real network STT
        text = self.script[self.i % len(self.script)]
        self.i += 1
        return text, "en", self.name


class SarvamSTT:
    name = "sarvam"

    def __init__(self, cfg: Config, http: httpx.AsyncClient, timeout: float | None = None) -> None:
        self.cfg, self.http = cfg, http
        self.timeout = timeout or float(os.getenv("SARVAM_STT_TIMEOUT_SECONDS", "5"))

    async def transcribe(self, wav: bytes, pcm: bytes) -> Result:
        if not self.cfg.sarvam_key:
            raise SttError("SARVAM_API_KEY is not set", 401)
        data = {"model": self.cfg.stt_model}
        if self.cfg.stt_model.startswith("saaras"):
            data["mode"] = self.cfg.stt_mode
        try:
            r = await self.http.post(
                SARVAM_STT_URL, headers={"api-subscription-key": self.cfg.sarvam_key},
                files={"file": ("chunk.wav", wav, "audio/wav")}, data=data,
                timeout=httpx.Timeout(self.timeout, connect=3.0))
        except httpx.HTTPError as e:
            raise SttError(f"{type(e).__name__}: {e}") from e
        if r.status_code >= 400:
            raise SttError(f"HTTP {r.status_code}: {r.text[:200]}", r.status_code)
        j = r.json()
        return (j.get("transcript") or "").strip(), short_lang(j.get("language_code")), self.name


# --------------------------------------------------------------------------- local whisper
def whisper_available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def _preload_cuda_libs() -> None:
    """ctranslate2 dlopens libcublas/libcudnn by soname; pip's nvidia-* wheels are not on the
    loader path, so load them by absolute path first (same fix flowtype needed)."""
    for site in sys.path:
        for pattern in ("nvidia/cublas/lib/libcublasLt.so.*", "nvidia/cublas/lib/libcublas.so.*",
                        "nvidia/cudnn/lib/libcudnn*.so.*"):
            for lib in sorted(glob.glob(os.path.join(site, pattern))):
                try:
                    ctypes.CDLL(lib, mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass


def _hf_offline(on: bool) -> None:
    os.environ["HF_HUB_OFFLINE"] = "1" if on else "0"
    try:
        import huggingface_hub.constants as c
        c.HF_HUB_OFFLINE = on
    except Exception:                                          # noqa: BLE001
        pass


class WhisperSTT:
    """faster-whisper through hk-voice-io's ASRModel (device="cuda" passed explicitly, CPU int8 if
    CUDA fails). Language is picked among hi/en/kn from Whisper's own detection."""

    name = "whisper"

    def __init__(self, model: str | None = None, device: str | None = None) -> None:
        self.model_size = model or os.getenv("WHISPER_MODEL", "small")
        self.device = device or os.getenv("WHISPER_DEVICE", "cuda")
        self.language = os.getenv("WHISPER_LANGUAGE", "auto")
        self.model = None
        self.loaded_on = ""
        self._load_lock = asyncio.Lock()
        self._run_lock = asyncio.Lock()                        # one transcription at a time on the GPU
        self.error: str | None = None

    def _load_sync(self):
        hk = Path(os.getenv("HK_VOICE_DIR", str(Path.home() / "hk-voice-io")))
        if importlib.util.find_spec("hk_voice") is None and (hk / "hk_voice" / "asr.py").exists():
            sys.path.insert(0, str(hk))
        if self.device == "cuda":
            _preload_cuda_libs()
        attempts = [(self.device, "float16" if self.device == "cuda" else "int8")]
        if self.device == "cuda":
            attempts.append(("cpu", "int8"))
        last = None
        for offline in (True, False):                          # the cache first: this runs when the net is down
            _hf_offline(offline)
            for device, ctype in attempts:
                try:
                    try:
                        from hk_voice.asr import ASRModel
                        m = ASRModel(model_size=self.model_size, language="auto", device=device,
                                     compute_type=ctype).model
                    except ImportError:
                        from faster_whisper import WhisperModel
                        m = WhisperModel(self.model_size, device=device, compute_type=ctype)
                    # one tiny run proves the CUDA libs actually load (they are dlopened on first use)
                    m.transcribe(np.zeros(16000, dtype=np.float32), beam_size=1, language="en")
                    self.loaded_on = f"{device}/{ctype}" + ("" if offline else " (downloaded)")
                    return m
                except Exception as e:                         # noqa: BLE001 - try the next option
                    last = e
                    log.warning("whisper %s on %s (%s) failed: %s", self.model_size, device,
                                "cache only" if offline else "online", str(e)[:200])
        raise RuntimeError(f"faster-whisper unavailable: {last}")

    async def ensure_loaded(self) -> bool:
        if self.model is not None:
            return True
        if self.error:
            return False
        async with self._load_lock:
            if self.model is None and not self.error:
                t0 = time.monotonic()
                try:
                    self.model = await asyncio.to_thread(self._load_sync)
                    log.info("whisper fallback ready: %s on %s (%.1fs)", self.model_size, self.loaded_on,
                             time.monotonic() - t0)
                except Exception as e:                         # noqa: BLE001
                    self.error = str(e)
                    log.error("whisper fallback disabled: %s", e)
        return self.model is not None

    def _transcribe_sync(self, pcm: bytes) -> tuple[str, str]:
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        lang = None if self.language == "auto" else self.language
        if lang is None:
            try:
                _, _, probs = self.model.detect_language(audio)
                p = dict(probs)
                p["hi"] = p.get("hi", 0.0) + p.get("ur", 0.0)
                lang = max(("hi", "en", "kn"), key=lambda k: p.get(k, 0.0))
            except Exception:                                  # noqa: BLE001 - let transcribe detect
                lang = None
        segs, info = self.model.transcribe(audio, beam_size=1, language=lang, vad_filter=False,
                                           condition_on_previous_text=False, temperature=0.0,
                                           max_new_tokens=120)   # one pass, bounded: never stall the queue
        text = " ".join(s.text.strip() for s in segs if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0))
        return text.strip(), short_lang(lang or info.language)

    async def transcribe(self, wav: bytes, pcm: bytes) -> Result:
        if not await self.ensure_loaded():
            raise SttError(f"whisper unavailable: {self.error}")
        async with self._run_lock:
            text, lang = await asyncio.to_thread(self._transcribe_sync, pcm)
        return text, lang, self.name


# --------------------------------------------------------------------------- router
class SttRouter:
    """Sarvam first. A failure falls through to Whisper for that chunk; repeated failures, a 429 or
    an auth error open a breaker so the next chunks go straight to Whisper (no timeout wait), and
    Sarvam is retried when the breaker closes."""

    name = "router"

    def __init__(self, primary, fallback=None) -> None:
        self.primary, self.fallback = primary, fallback
        self.open_until = 0.0
        self.failures = 0

    def _trip(self, e: SttError) -> None:
        self.failures += 1
        hold = 0.0
        if e.status in (401, 403):
            hold = 300.0                                       # bad key: don't hammer it
        elif e.status == 429:
            hold = 20.0
        elif self.failures >= 2:
            hold = 30.0
        if hold:
            self.open_until = time.monotonic() + hold
            log.warning("Sarvam STT breaker open for %.0fs (%s)%s", hold, e,
                        "; using local whisper" if self.fallback else "")

    async def transcribe(self, wav: bytes, pcm: bytes) -> Result:
        if self.fallback and time.monotonic() < self.open_until:
            return await self.fallback.transcribe(wav, pcm)
        try:
            r = await self.primary.transcribe(wav, pcm)
            if self.failures:
                log.info("Sarvam STT back")
            self.failures = 0
            return r
        except SttError as e:
            log.warning("Sarvam STT failed: %s", e)
            self._trip(e)
            if self.fallback is None:
                raise
            return await self.fallback.transcribe(wav, pcm)

    async def warm(self) -> None:
        if self.fallback:
            await self.fallback.ensure_loaded()


def build_stt(cfg: Config, http: httpx.AsyncClient, mode: str = "auto"):
    """mode: auto (Sarvam, whisper fallback if installed) | sarvam | whisper | mock"""
    if mode == "mock" or cfg.mock_stt:
        return MockSTT()
    if mode == "whisper":
        return WhisperSTT()
    fallback = WhisperSTT() if (mode == "auto" and os.getenv("STT_FALLBACK", "whisper") == "whisper"
                                and whisper_available()) else None
    return SttRouter(SarvamSTT(cfg, http), fallback)

"""Speech-to-text engines. Each returns (text, language) where language is hi | kn | en."""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

from config import SARVAM_STT_URL, Config

log = logging.getLogger("chaukanna.stt")

MOCK_SCRIPT = [
    "Hello, this is Inspector Sharma from CBI Mumbai.",
    "A parcel in your name contains illegal narcotics and fake passports.",
    "You are under digital arrest. Do not tell anyone and do not disconnect the call.",
    "To verify your account, tell me the OTP that you just received.",
]


def short_lang(code: str | None) -> str:
    c = (code or "en").split("-")[0].lower()
    return c if c in ("hi", "kn") else "en"


class MockSTT:
    """Canned scam script, one line per chunk (wiring tests, no network)."""

    name = "mock"

    def __init__(self, script: list[str] | None = None, delay_ms: float | None = None) -> None:
        self.script = script or MOCK_SCRIPT
        self.i = 0
        self.delay = (float(os.getenv("MOCK_STT_DELAY_MS", "0")) if delay_ms is None else delay_ms) / 1000

    async def transcribe(self, wav: bytes, pcm: bytes) -> tuple[str, str]:
        if self.delay:
            await asyncio.sleep(self.delay)                   # behave like a real network STT
        text = self.script[self.i % len(self.script)]
        self.i += 1
        return text, "en"


class SarvamError(Exception):
    def __init__(self, msg: str, status: int | None = None) -> None:
        super().__init__(msg)
        self.status = status


class SarvamSTT:
    name = "sarvam"

    def __init__(self, cfg: Config, http: httpx.AsyncClient, timeout: float = 8.0) -> None:
        self.cfg, self.http, self.timeout = cfg, http, timeout

    async def transcribe(self, wav: bytes, pcm: bytes) -> tuple[str, str]:
        if not self.cfg.sarvam_key:
            raise SarvamError("SARVAM_API_KEY is not set")
        data = {"model": self.cfg.stt_model}
        if self.cfg.stt_model.startswith("saaras"):
            data["mode"] = self.cfg.stt_mode
        try:
            r = await self.http.post(
                SARVAM_STT_URL, headers={"api-subscription-key": self.cfg.sarvam_key},
                files={"file": ("chunk.wav", wav, "audio/wav")}, data=data, timeout=self.timeout)
        except httpx.HTTPError as e:
            raise SarvamError(f"{type(e).__name__}: {e}") from e
        if r.status_code >= 400:
            raise SarvamError(f"HTTP {r.status_code}: {r.text[:200]}", r.status_code)
        j = r.json()
        return (j.get("transcript") or "").strip(), short_lang(j.get("language_code"))

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from schemas import LLMVerdict

log = logging.getLogger("classifier.backend")


@dataclass
class LLMContext:
    """Immutable snapshot of a call handed to a backend (taken under the call lock, so the
    backend never sees the transcript change underneath it)."""

    call_id: str
    caller_number: str
    chunks: list[tuple[str, str, str]]  # (speaker, language, text), oldest first, last WINDOW chunks
    earlier: str | None = None  # the backend's previous assessment once older chunks scrolled out
    language: str = "en"
    keyword_signals: list[str] = field(default_factory=list)

    @property
    def transcript(self) -> str:
        return "\n".join(f"[{sp.upper()} | {lang}] {text}" for sp, lang, text in self.chunks)


class Backend(ABC):
    name = "base"

    def __init__(self) -> None:
        self.last_used = self.name

    @abstractmethod
    async def classify(self, ctx: LLMContext) -> LLMVerdict: ...

    async def aclose(self) -> None:  # optional cleanup
        return None


class FallbackBackend(Backend):
    """Try `primary` with a hard timeout; on any error or timeout use `fallback`.
    `last_used` names whichever produced the verdict (e.g. 'gemini(fallback)')."""

    def __init__(self, primary: Backend, fallback: Backend, primary_timeout_s: float) -> None:
        self.primary, self.fallback, self.timeout = primary, fallback, primary_timeout_s
        self.name = primary.name
        self.last_used = primary.name

    async def classify(self, ctx: LLMContext) -> LLMVerdict:
        try:
            v = await asyncio.wait_for(self.primary.classify(ctx), timeout=self.timeout)
            self.last_used = self.primary.name
            return v
        except asyncio.CancelledError:
            raise
        except Exception as e:  # timeout, refused, 4xx/5xx, bad JSON
            log.warning("%s failed (%s: %s) -> %s", self.primary.name, type(e).__name__, str(e)[:120], self.fallback.name)
            v = await self.fallback.classify(ctx)
            self.last_used = f"{self.fallback.name}(fallback)"
            return v

    async def aclose(self) -> None:
        await self.primary.aclose()
        await self.fallback.aclose()

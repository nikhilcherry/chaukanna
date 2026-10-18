import asyncio
import os

import keywords
from backends.base import Backend, LLMContext
from schemas import LLMVerdict


class MockBackend(Backend):
    """Offline stand-in for an LLM: re-runs the keyword rules over the snapshot after an
    artificial delay (MOCK_DELAY_MS, default 300) so the async path can be exercised without a key."""

    name = "mock"

    def __init__(self, delay_ms: float | None = None) -> None:
        super().__init__()
        self.delay = (float(os.getenv("MOCK_DELAY_MS", "300")) if delay_ms is None else delay_ms) / 1000

    async def classify(self, ctx: LLMContext) -> LLMVerdict:
        await asyncio.sleep(self.delay)
        st = keywords.KeywordState()
        for sp, lang, text in ctx.chunks:
            keywords.scan_chunk(st, sp, text, lang)
        kv = keywords.verdict(st)
        return LLMVerdict(scam_type=kv.scam_type, pressure=kv.pressure, asks_otp_or_pin=kv.asks_otp_or_pin,
                          demands_secrecy=kv.demands_secrecy, confidence=kv.confidence, language=kv.language,
                          summary_for_family=kv.summary)

"""Fake backends for engine tests."""
import asyncio

from backends.base import Backend, LLMContext  # noqa: E402
from schemas import LLMVerdict  # noqa: E402


def lv(pressure=0, scam_type="none", otp=False, secrecy=False, conf=0.9, summary="model summary"):
    return LLMVerdict(scam_type=scam_type, pressure=pressure, asks_otp_or_pin=otp, demands_secrecy=secrecy,
                      confidence=conf, language="en", summary_for_family=summary)


class ScriptedBackend(Backend):
    """Returns `verdicts[i]` for the i-th call after `delays[i]` seconds (last entry repeats)."""

    name = "scripted"

    def __init__(self, verdicts, delays=(0.0,)):
        super().__init__()
        self.verdicts, self.delays, self.calls = list(verdicts), list(delays), 0
        self.contexts: list[LLMContext] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def classify(self, ctx):
        i = self.calls
        self.calls += 1
        self.contexts.append(ctx)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delays[min(i, len(self.delays) - 1)])
            return self.verdicts[min(i, len(self.verdicts) - 1)]
        finally:
            self.in_flight -= 1


class RaisingBackend(Backend):
    name = "raising"

    def __init__(self, exc=RuntimeError("backend exploded")):
        super().__init__()
        self.exc, self.calls = exc, 0

    async def classify(self, ctx):
        self.calls += 1
        raise self.exc


class HangingBackend(Backend):
    name = "hanging"

    async def classify(self, ctx):
        await asyncio.sleep(3600)

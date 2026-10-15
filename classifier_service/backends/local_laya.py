import asyncio
import logging
import os

from backends._openai_compat import chat_verdict
from backends.base import Backend
from backends.gemini import GeminiBackend
from schemas import Verdict
from store import CallState

log = logging.getLogger("classifier.laya")
LOCAL_TIMEOUT_S = 1.5


class LocalLayaBackend(Backend):
    """Local model on the laptop GPU behind an OpenAI-compatible endpoint
    (llama.cpp / vLLM / Ollama /v1). Falls back to Gemini on timeout or error."""

    name = "local_laya"

    def __init__(self) -> None:
        self.url = os.getenv("LAYA_URL", "http://127.0.0.1:8001/v1/chat/completions")
        self.model = os.getenv("LAYA_MODEL", "laya")
        self.key = os.getenv("LAYA_API_KEY", "")
        self._fallback: GeminiBackend | None = None
        self.last_used = "local_laya"

    async def classify(self, call_id: str, st: CallState) -> Verdict:
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        try:
            v = await asyncio.wait_for(
                chat_verdict(self.url, self.model, call_id, st, headers, LOCAL_TIMEOUT_S),
                timeout=LOCAL_TIMEOUT_S,
            )
            self.last_used = "local_laya"
            return v
        except Exception as e:  # timeout, connection refused, bad JSON, schema mismatch
            log.warning("local_laya failed (%s: %s) -> falling back to gemini", type(e).__name__, e)
            self._fallback = self._fallback or GeminiBackend()
            self.last_used = "gemini(fallback)"
            return await self._fallback.classify(call_id, st)

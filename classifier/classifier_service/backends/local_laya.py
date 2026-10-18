import os

import httpx

from backends._openai_compat import chat_verdict
from backends.base import Backend, LLMContext
from schemas import LLMVerdict


class LocalLayaBackend(Backend):
    """Local model on the laptop GPU behind an OpenAI-compatible endpoint (llama.cpp / vLLM /
    Ollama /v1). get_backend() wraps it in FallbackBackend(..., GeminiBackend(), 1.5 s)."""

    name = "local_laya"

    def __init__(self) -> None:
        super().__init__()
        self.url = os.getenv("LAYA_URL", "http://127.0.0.1:8001/v1/chat/completions")
        self.model = os.getenv("LAYA_MODEL", "laya")
        key = os.getenv("LAYA_API_KEY", "")
        self.headers = {"Authorization": f"Bearer {key}"} if key else {}
        self.client = httpx.AsyncClient()

    async def classify(self, ctx: LLMContext) -> LLMVerdict:
        return await chat_verdict(self.client, self.url, self.model, ctx, self.headers, timeout=float(os.getenv("LAYA_TIMEOUT_S", "1.5")))

    async def aclose(self) -> None:
        await self.client.aclose()

import os

import httpx

from backends._openai_compat import chat_verdict
from backends.base import Backend, LLMContext
from schemas import LLMVerdict


class SarvamBackend(Backend):
    """Sarvam chat-completions API (OpenAI-compatible). Untested against the live API."""

    name = "sarvam"

    def __init__(self) -> None:
        super().__init__()
        self.url = os.getenv("SARVAM_URL", "https://api.sarvam.ai/v1/chat/completions")
        self.model = os.getenv("SARVAM_MODEL", "sarvam-m")
        key = os.getenv("SARVAM_API_KEY", "")
        self.headers = {"api-subscription-key": key, "Authorization": f"Bearer {key}"}
        self.client = httpx.AsyncClient()

    async def classify(self, ctx: LLMContext) -> LLMVerdict:
        return await chat_verdict(self.client, self.url, self.model, ctx, self.headers, timeout=4.0)

    async def aclose(self) -> None:
        await self.client.aclose()

import os

from backends._openai_compat import chat_verdict
from backends.base import Backend
from schemas import Verdict
from store import CallState


class SarvamBackend(Backend):
    """Sarvam chat-completions API (OpenAI-compatible)."""

    name = "sarvam"

    def __init__(self) -> None:
        self.url = os.getenv("SARVAM_URL", "https://api.sarvam.ai/v1/chat/completions")
        self.model = os.getenv("SARVAM_MODEL", "sarvam-m")
        self.key = os.getenv("SARVAM_API_KEY", "")

    async def classify(self, call_id: str, st: CallState) -> Verdict:
        headers = {"api-subscription-key": self.key, "Authorization": f"Bearer {self.key}"}
        return await chat_verdict(self.url, self.model, call_id, st, headers, timeout=4.0)

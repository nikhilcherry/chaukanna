import os

from google import genai
from google.genai import types

from backends.base import Backend
from prompt import SYSTEM_PROMPT, build_user_content
from schemas import Verdict
from store import CallState


class GeminiBackend(Backend):
    name = "gemini"

    def __init__(self) -> None:
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
        self.config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=Verdict,
            temperature=0.0,
            # Latency budget is <500ms: no thinking tokens.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )

    async def classify(self, call_id: str, st: CallState) -> Verdict:
        resp = await self.client.aio.models.generate_content(
            model=self.model, contents=build_user_content(call_id, st), config=self.config
        )
        v = resp.parsed if isinstance(resp.parsed, Verdict) else Verdict.model_validate_json(resp.text)
        return v.model_copy(update={"call_id": call_id})

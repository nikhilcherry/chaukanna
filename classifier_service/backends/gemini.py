import os

from google import genai
from google.genai import types

from backends.base import Backend, LLMContext
from prompt import SYSTEM_PROMPT, build_user_content
from schemas import LLMVerdict


class GeminiBackend(Backend):
    name = "gemini"

    def __init__(self, model: str | None = None) -> None:
        super().__init__()
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
        self.config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=LLMVerdict,
            temperature=0.0,
            thinking_config=types.ThinkingConfig(thinking_budget=0),  # latency: no thinking tokens
        )

    async def classify(self, ctx: LLMContext) -> LLMVerdict:
        resp = await self.client.aio.models.generate_content(model=self.model, contents=build_user_content(ctx), config=self.config)
        return resp.parsed if isinstance(resp.parsed, LLMVerdict) else LLMVerdict.model_validate_json(resp.text)

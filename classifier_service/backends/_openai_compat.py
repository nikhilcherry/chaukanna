import json

import httpx

from backends.base import LLMContext
from prompt import SYSTEM_PROMPT, build_user_content
from schemas import LLMVerdict

SCHEMA_HINT = "\n\nJSON schema:\n" + json.dumps(LLMVerdict.model_json_schema())


async def chat_verdict(client: httpx.AsyncClient, url: str, model: str, ctx: LLMContext, headers: dict, timeout: float) -> LLMVerdict:
    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + SCHEMA_HINT},
            {"role": "user", "content": build_user_content(ctx)},
        ],
        "response_format": {"type": "json_object"},
    }
    r = await client.post(url, json=body, headers=headers, timeout=timeout)
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"]
    text = text.strip().removeprefix("```json").removesuffix("```").strip()
    return LLMVerdict.model_validate_json(text)

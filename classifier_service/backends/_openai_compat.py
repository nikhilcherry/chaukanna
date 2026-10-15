import json

import httpx

from prompt import SYSTEM_PROMPT, build_user_content
from schemas import Verdict
from store import CallState

SCHEMA_HINT = "\n\nJSON schema:\n" + json.dumps(Verdict.model_json_schema())


async def chat_verdict(
    url: str, model: str, call_id: str, st: CallState, headers: dict, timeout: float
) -> Verdict:
    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + SCHEMA_HINT},
            {"role": "user", "content": build_user_content(call_id, st)},
        ],
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(url, json=body, headers=headers)
        r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"]
    text = text.strip().removeprefix("```json").removesuffix("```").strip()
    return Verdict.model_validate_json(text).model_copy(update={"call_id": call_id})

"""Jev backend without the network: answer mapping, concurrency cap, 403 backoff, fallback."""
import asyncio
import json
import os

import httpx
import pytest
from fakes import ScriptedBackend, lv

os.environ.setdefault("TYPESAFE_API_KEY", "test-key")
from backends import jev  # noqa: E402
from backends.base import FallbackBackend, LLMContext  # noqa: E402

CTX = LLMContext("c1", "+919000000001", [("caller", "hi", "CBI se bol raha hoon"), ("victim", "hi", "ji?")] * 6, None, "hi")


def answers(stype="digital_arrest", p_none=0.0, score=3.0, otp=0.98, sec=0.5):
    probs = {k: 0.0 for k in jev.SCAM_TYPES}
    probs[stype] = 1.0 - (p_none if stype != "none" else 0.0)
    probs["none"] = probs.get("none", 0.0) + (p_none if stype != "none" else 1.0)
    return {"scam_type": {"choice": stype, "probabilities": probs, "confidence": 0.9},
            "pressure": {"score": score, "probabilities": {}}, "asks_otp": {"noul": otp}, "secrecy": {"noul": sec}}


def test_mapping_uses_probabilities():
    v = jev.JevBackend.to_verdict(answers(), CTX)
    assert v.scam_type == "digital_arrest" and v.pressure == 3 and v.asks_otp_or_pin
    assert v.demands_secrecy is False                       # 0.5 is "unsure": left to the keywords
    assert v.language == "hi" and v.confidence == 1.0 and "posing as police" in v.summary_for_family


def test_family_money_request_is_not_scam_pressure():
    # Jev's real answer on "transfer the rent to my account" from Mom: type none (0.95), pressure score 1.54
    v = jev.JevBackend.to_verdict(answers("none", score=1.54, otp=0.02, sec=0.02), CTX)
    assert v.pressure == 0 and v.scam_type == "none"


def test_state_sends_last_chunks_with_speakers():
    st = jev.JevBackend.state(CTX)
    assert len(st["transcript"]) == jev.STATE_CHUNKS and st["call"]["earlier_chunks_not_shown"] == 12 - jev.STATE_CHUNKS
    assert {t["speaker"] for t in st["transcript"]} == {"CALLER", "LISTENER"}


def _backend(handler) -> jev.JevBackend:
    b = jev.JevBackend()
    b.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return b


def test_concurrency_is_capped_at_three():
    state = {"now": 0, "max": 0}

    async def handler(request):
        state["now"] += 1
        state["max"] = max(state["max"], state["now"])
        await asyncio.sleep(0.05)
        state["now"] -= 1
        body = json.loads(request.content)
        assert set(body["questions"]) == {"scam_type", "pressure", "asks_otp", "secrecy"} and body["model"] == "jev-latest"
        return httpx.Response(200, json={"answers": answers()})

    async def go():
        b = _backend(handler)
        await asyncio.gather(*(b.classify(CTX) for _ in range(10)))
        await b.aclose()

    asyncio.run(go())
    assert state["max"] == 3


def test_403_backs_off_and_fallback_answers():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(403, json={"error": "forbidden"})

    async def go():
        b = _backend(handler)
        fb = FallbackBackend(b, ScriptedBackend([lv(2, "digital_arrest")]), 1.5)
        v1 = await fb.classify(CTX)
        v2 = await fb.classify(CTX)                       # inside the backoff window: no HTTP call at all
        assert v1.pressure == 2 and v2.pressure == 2 and fb.last_used == "scripted(fallback)"
        await b.aclose()

    asyncio.run(go())
    assert calls["n"] == 1


def test_slow_jev_falls_back_within_timeout():
    async def handler(request):
        await asyncio.sleep(5)
        return httpx.Response(200, json={"answers": answers()})

    async def go():
        fb = FallbackBackend(_backend(handler), ScriptedBackend([lv(1, "kyc_update")]), 0.2)
        t = asyncio.get_running_loop().time()
        v = await fb.classify(CTX)
        assert v.scam_type == "kyc_update" and asyncio.get_running_loop().time() - t < 1.0

    asyncio.run(go())


def test_auto_backend_prefers_jev(monkeypatch):
    from backends import get_backend
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    b = get_backend("auto")
    assert isinstance(b, FallbackBackend) and b.primary.name == "jev" and b.fallback.name == "gemini"
    monkeypatch.delenv("TYPESAFE_API_KEY")
    assert get_backend("auto").name == "gemini"
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert get_backend("auto") is None

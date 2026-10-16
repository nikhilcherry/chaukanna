import asyncio
import time

import pytest
from fakes import HangingBackend, RaisingBackend, ScriptedBackend, lv

from callers import CallerRegistry
from engine import Engine, Settings
from schemas import ClassifyRequest, Verdict

OTP_CHUNK = "Ab verification ke liye apna OTP aur bank PIN batayiye."
CBI_CHUNK = "Namaste, main CBI officer Rajesh Sharma bol raha hoon, Delhi headquarters se."
ARREST_CHUNK = "Aapke Aadhaar par money laundering ka case hai, aap digital arrest mein hain, kisi ko mat batana."


def req(text, speaker="caller", call_id="c1", number="+91 90000 00001", lang="hi"):
    return ClassifyRequest(call_id=call_id, caller_number=number, speaker=speaker, chunk_text=text, language=lang)


def run(coro):
    return asyncio.run(coro)


def engine(backend=None, **kw) -> Engine:
    return Engine(backend, Settings(**kw), CallerRegistry())


# ---------------------------------------------------------------- 1. fast path + background LLM
def test_slow_llm_does_not_block_and_lands_on_next_chunk():
    async def go():
        b = ScriptedBackend([lv(2, "digital_arrest", summary="Caller claims CBI.")], delays=[0.8])
        e = engine(b, budget_ms=400)
        t = time.perf_counter()
        v1 = await e.classify(req(CBI_CHUNK))
        first_ms = (time.perf_counter() - t) * 1000
        assert v1.source == "keywords" and v1.pressure == 1   # keyword verdict, LLM still running
        assert first_ms < 450                                 # waited at most the budget
        await asyncio.sleep(0.6)                              # next 4 s chunk; LLM has landed
        t = time.perf_counter()
        v2 = await e.classify(req("Ji, boliye.", speaker="victim"))
        assert (time.perf_counter() - t) * 1000 < 50
        assert v2.pressure == 2 and v2.source == "merged" and v2.llm_chunks_behind == 1
        assert v2.summary_for_family.startswith("Caller claims CBI")
    run(go())


def test_at_most_one_llm_in_flight_per_call_and_latest_transcript_used():
    async def go():
        b = ScriptedBackend([lv(1, "digital_arrest")], delays=[0.3])
        e = engine(b, budget_ms=50)
        for i in range(5):
            await e.classify(req(f"{CBI_CHUNK} part {i}"))
        await asyncio.sleep(0.8)
        assert b.max_in_flight == 1
        assert b.calls == 2                                   # first run + one coalesced rerun
        assert "part 4" in b.contexts[-1].transcript          # rerun saw every chunk
    run(go())


def test_fast_local_model_is_awaited_inside_budget():
    async def go():
        b = ScriptedBackend([lv(3, "kyc_update", otp=True)], delays=[0.03])
        e = engine(b, budget_ms=400)
        v = await e.classify(req("Hello madam, good afternoon."))
        assert v.pressure == 3 and v.source == "scripted" and v.latency_ms < 400
    run(go())


def test_victim_chunks_do_not_trigger_llm_by_default():
    async def go():
        b = ScriptedBackend([lv(0)], delays=[0.0])
        e = engine(b)
        await e.classify(req("haan ji", speaker="victim"))
        await asyncio.sleep(0.05)
        assert b.calls == 0
    run(go())


# ---------------------------------------------------------------- 2. never 5xx, degraded
def test_failing_backend_degrades_to_keywords():
    async def go():
        b = RaisingBackend()
        e = engine(b)
        await e.classify(req(CBI_CHUNK))
        await asyncio.sleep(0.05)
        v = await e.classify(req(OTP_CHUNK))
        assert v.degraded is True and v.pressure == 3 and v.asks_otp_or_pin
        assert v.recommended_whisper_clip == "warn_otp"
    run(go())


def test_hanging_backend_times_out_and_response_stays_fast():
    async def go():
        e = engine(HangingBackend(), budget_ms=200, llm_timeout_s=0.3)
        t = time.perf_counter()
        v1 = await e.classify(req(CBI_CHUNK))
        assert (time.perf_counter() - t) < 0.3 and v1.pressure == 1
        await asyncio.sleep(0.4)
        v2 = await e.classify(req(OTP_CHUNK))
        assert v2.degraded and v2.pressure == 3
    run(go())


def test_circuit_breaker_stops_calling_a_dead_backend():
    async def go():
        b = RaisingBackend()
        e = engine(b)
        for i in range(8):
            await e.classify(req(f"hello {i}", call_id=f"c{i}"))
            await asyncio.sleep(0.01)
        assert b.calls == e.s.breaker_failures
    run(go())


def test_pipeline_exception_returns_degraded_not_500(monkeypatch):
    import keywords

    async def go():
        e = engine()
        v1 = await e.classify(req(OTP_CHUNK))
        monkeypatch.setattr(keywords, "verdict", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
        v2 = await e.classify(req("more text"))
        assert v2.degraded and v2.pressure == v1.pressure and v2.recommended_whisper_clip == "none"
    run(go())


def test_http_never_5xx_with_failing_backend(monkeypatch):
    import httpx

    import main

    monkeypatch.setattr(main, "engine", engine(RaisingBackend()))

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
            for text in (CBI_CHUNK, OTP_CHUNK, ""):
                r = await c.post("/classify", json={"call_id": "h1", "caller_number": "", "speaker": "caller",
                                                    "chunk_text": text, "language": "hi-IN"})
                assert r.status_code == 200
                await asyncio.sleep(0.02)
            body = r.json()
            assert body["degraded"] is True and body["pressure"] == 3
            assert (await c.post("/reset/h1")).json()["cleared"] is True
    run(go())


# ---------------------------------------------------------------- 3. race, monotonic, TTL
def test_concurrent_legs_never_lower_pressure():
    """Old bug: each request read the previous verdict before awaiting the LLM, so a slow
    high-pressure answer could be overwritten by a fast low one."""
    async def go():
        # LLM: first call slow + scary, every later call fast + calm.
        b = ScriptedBackend([lv(3, "digital_arrest", secrecy=True)] + [lv(0)] * 50, delays=[0.25] + [0.01] * 50)
        e = engine(b, budget_ms=300)
        done: list[tuple[float, Verdict]] = []

        async def leg(speaker, i):
            v = await e.classify(req(f"chunk {i} from {speaker}", speaker=speaker))
            done.append((time.perf_counter(), v))

        for i in range(10):
            await asyncio.gather(leg("caller", i), leg("victim", i))
        returned = [v.pressure for _, v in sorted(done, key=lambda x: x[0])]
        assert returned == sorted(returned), returned          # never decreases in the order answered
        assert returned[-1] == 3 and e.calls["c1"].last.demands_secrecy
    run(go())


def test_late_calm_llm_cannot_undo_keyword_alarm():
    async def go():
        b = ScriptedBackend([lv(0, summary="Ordinary call.")], delays=[0.1])
        e = engine(b, budget_ms=50)
        v1 = await e.classify(req(OTP_CHUNK))
        await asyncio.sleep(0.2)
        v2 = await e.classify(req("theek hai"))
        assert v1.pressure == 3 and v2.pressure == 3 and v2.asks_otp_or_pin
    run(go())


def test_ttl_expiry_forgets_idle_calls_and_cancels_llm():
    async def go():
        e = engine(HangingBackend(), ttl_s=0.05, budget_ms=10, llm_timeout_s=60)
        await e.classify(req(CBI_CHUNK, call_id="old"))
        task = e.calls["old"].llm_task
        await asyncio.sleep(0.1)
        await e.classify(req("hi", call_id="fresh"))
        assert e.sweep() == 1
        assert "old" not in e.calls and "fresh" in e.calls
        await asyncio.sleep(0)
        assert task.cancelled() or task.done()
        v = await e.classify(req("hello again", call_id="old"))   # a new call with the same id starts clean
        assert v.chunk_index == 1 and v.pressure == 0
    run(go())


def test_max_calls_evicts_least_recent():
    async def go():
        e = engine(max_calls=3)
        for i in range(5):
            await e.classify(req("hello", call_id=f"c{i}"))
        assert sorted(e.calls) == ["c2", "c3", "c4"]
    run(go())


# ---------------------------------------------------------------- 4. whisper once
def test_each_clip_whispers_once_with_reason():
    async def go():
        e = engine()
        clips = []
        for text in (CBI_CHUNK, OTP_CHUNK, OTP_CHUNK, "OTP jaldi bataiye", ARREST_CHUNK, "ok", "ok", "ok"):
            v = await e.classify(req(text))
            clips.append(v.recommended_whisper_clip)
            if v.recommended_whisper_clip != "none":
                assert v.whisper_reason
        assert clips.count("warn_otp") == 1 and clips[1] == "warn_otp"
        assert clips.count("warn_digital_arrest") == 1 and clips.count("warn_secrecy") == 1
        assert sum(c != "none" for c in clips) == 3
    run(go())


def test_known_scammer_whispers_on_first_chunk():
    async def go():
        e = engine()
        v = await e.classify(req("Hello, am I speaking to Mrs Rao?", number="+91 99887 76655"))
        assert v.known_scammer and v.caller_risk == "listed" and v.pressure >= 2
        assert v.recommended_whisper_clip == "warn_known_scammer" and "scam list" in v.whisper_reason
        v2 = await e.classify(req("Madam one minute please", number="+91 99887 76655"))
        assert v2.recommended_whisper_clip == "none" and v2.known_scammer
    run(go())


def test_risky_country_code_is_a_weak_signal():
    async def go():
        e = engine()
        v = await e.classify(req("Hello sir, how are you?", number="+855 98 765 432"))
        assert v.known_scammer and v.caller_risk == "risky_country_code"
        assert v.pressure == 1 and v.recommended_whisper_clip == "none"
    run(go())


# ---------------------------------------------------------------- delivery OTP policy
DELIVERY = ["Hello ma'am, Amazon delivery hai, main aapke gate pe khada hoon.",
            "Ma'am parcel ke liye OTP bata dijiye jo SMS mein aaya hai, delivery complete karni hai."]


@pytest.mark.parametrize("policy,expect_p,expect_clip", [("caution", 1, "none"), ("warn", 3, "warn_otp")])
def test_delivery_otp_policy(policy, expect_p, expect_clip):
    async def go():
        # gemini-2.5-flash's real answers on this call: none p0, then bank_impersonation p2 on the OTP chunk
        b = ScriptedBackend([lv(0), lv(2, "bank_impersonation", otp=True)], delays=[0.0])
        e = engine(b, delivery_otp_policy=policy, budget_ms=200)
        vs = [await e.classify(req(t)) for t in DELIVERY]
        await asyncio.sleep(0.05)
        vs.append(await e.classify(req("Haan theek hai.", speaker="victim")))
        assert max(v.pressure for v in vs) == expect_p
        assert vs[-1].asks_otp_or_pin
        assert [v.recommended_whisper_clip for v in vs if v.recommended_whisper_clip != "none"] in ([], [expect_clip])
        if policy == "warn":
            assert any(v.recommended_whisper_clip == "warn_otp" for v in vs)
    run(go())


def test_response_keeps_original_contract_fields():
    async def go():
        v = await engine().classify(req(CBI_CHUNK))
        d = v.model_dump()
        for k in ("call_id", "scam_type", "pressure", "asks_otp_or_pin", "demands_secrecy", "confidence", "language",
                  "recommended_whisper_clip", "summary_for_family"):
            assert k in d
        assert d["language"] in ("hi", "kn", "en") and 0 <= d["confidence"] <= 1
    run(go())


def test_known_slow_backend_is_not_waited_for():
    """Once the backend is known to take longer than the budget, caller chunks answer at once."""
    async def go():
        b = ScriptedBackend([lv(1, "digital_arrest")], delays=[0.6])
        e = engine(b, budget_ms=400)
        await e.classify(req(CBI_CHUNK))
        await asyncio.sleep(0.8)                      # first run done -> latency estimate ~600 ms
        t = time.perf_counter()
        await e.classify(req("Aapke naam se parcel aaya hai."))
        assert (time.perf_counter() - t) * 1000 < 50
    run(go())


def test_keyword_alarm_is_never_held_for_the_llm():
    async def go():
        b = ScriptedBackend([lv(1)], delays=[0.3])
        e = engine(b, budget_ms=450)
        await e.classify(req("Hello madam, good afternoon."))     # seeds the ~300 ms estimate
        await asyncio.sleep(0.4)
        t = time.perf_counter()
        v = await e.classify(req(OTP_CHUNK))                        # waitable LLM, but keywords found an OTP ask
        assert (time.perf_counter() - t) * 1000 < 50 and v.recommended_whisper_clip == "warn_otp"
        t = time.perf_counter()
        await e.classify(req("Theek hai, aap baad mein call kijiye."))  # quiet chunk: waits for the fresh verdict
        assert 0.2 < time.perf_counter() - t < 0.45
    run(go())

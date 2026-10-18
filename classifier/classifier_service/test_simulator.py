"""Replays calls against a running service and prints how the verdict escalates.

    python main.py                                  (from classifier_service/, serves :8010)
    python test_simulator.py [base_url] [--gap 4] [--concurrent]

--gap        seconds between chunks (real calls: ~4 s; the LLM verdict lands in between)
--concurrent also fire caller+victim legs of one call at the same instant, to check the
             per-call lock: pressure must never go down and each clip must fire once.
"""
import argparse
import asyncio
import statistics
import time

import httpx

DIGITAL_ARREST = [
    ("caller", "hi", "Namaste, main CBI officer Rajesh Sharma bol raha hoon, Delhi headquarters se."),
    ("victim", "hi", "Ji? Kya hua sir, main kuch samjhi nahi."),
    ("caller", "hi", "Aapke naam se ek FedEx parcel pakda gaya hai customs mein, usme drugs aur fake passports hain."),
    ("victim", "hi", "Nahi nahi, maine toh koi parcel nahi bheja. Yeh galat hai."),
    ("caller", "hi", "Aapke Aadhaar par money laundering ka case hai, arrest warrant nikal chuka hai. Aap digital arrest mein hain, call disconnect mat karna."),
    ("caller", "hi", "Yeh baat confidential hai, kisi ko mat batana, family ko bhi nahi. Ab verification ke liye apna OTP aur bank PIN batayiye, aur safe RBI account mein paisa transfer kijiye."),
]
DELIVERY = [
    ("caller", "en", "Hello ma'am, I'm the delivery boy from Swiggy Instamart, I'm outside your building."),
    ("victim", "en", "Oh okay, which gate are you at?"),
    ("caller", "en", "Main gate near the security cabin. Which floor is it, third floor?"),
    ("victim", "en", "Yes, flat 302. I'll come down to collect it, give me two minutes."),
]
latencies: list[float] = []


async def post(c: httpx.AsyncClient, call_id: str, number: str, speaker: str, lang: str, text: str) -> dict:
    t0 = time.perf_counter()
    r = await c.post("/classify", json=dict(call_id=call_id, caller_number=number, speaker=speaker, chunk_text=text, language=lang))
    latencies.append((time.perf_counter() - t0) * 1000)
    r.raise_for_status()
    return r.json()


def show(i: int, speaker: str, text: str, v: dict) -> None:
    clip = v["recommended_whisper_clip"]
    print(f"[{i}] {speaker:6} {text[:64]!r}\n    pressure={v['pressure']} type={v['scam_type']} otp={v['asks_otp_or_pin']} "
          f"secret={v['demands_secrecy']} conf={v['confidence']:.2f} src={v.get('source')} behind={v.get('llm_chunks_behind')} "
          f"{latencies[-1]:.0f} ms{'  WHISPER ' + clip + ' <- ' + v.get('whisper_reason', '') if clip != 'none' else ''}")


async def replay(c: httpx.AsyncClient, name: str, chunks: list, number: str, gap: float) -> list[int]:
    call_id = f"sim-{name}-{int(time.time())}"
    print(f"\n=== {name} ({call_id}) ===")
    out = []
    for i, (speaker, lang, text) in enumerate(chunks, 1):
        v = await post(c, call_id, number, speaker, lang, text)
        out.append(v["pressure"])
        show(i, speaker, text, v)
        await asyncio.sleep(gap)
    print(f"    -> {v['summary_for_family']}")
    await c.post(f"/reset/{call_id}")
    print("pressure: " + " -> ".join(map(str, out)))
    return out


async def concurrent_legs(c: httpx.AsyncClient, gap: float) -> bool:
    """Both legs of one call hit /classify at the same instant, chunk after chunk."""
    call_id = f"sim-race-{int(time.time())}"
    print(f"\n=== concurrent legs ({call_id}) ===")
    answered: list[tuple[float, dict]] = []
    caller = [x for x in DIGITAL_ARREST if x[0] == "caller"]

    async def one(speaker, lang, text):
        v = await post(c, call_id, "+91 98000 11122", speaker, lang, text)
        answered.append((time.perf_counter(), v))

    for i, (_, lang, text) in enumerate(caller):
        await asyncio.gather(one("caller", lang, text), one("victim", lang, f"haan ji sir, samajh gayi ({i})"))
        await asyncio.sleep(gap)
    await c.post(f"/reset/{call_id}")
    seq = [v["pressure"] for _, v in sorted(answered, key=lambda x: x[0])]
    clips = [v["recommended_whisper_clip"] for _, v in answered if v["recommended_whisper_clip"] != "none"]
    ok = seq == sorted(seq) and len(clips) == len(set(clips))
    print(f"pressure in answer order: {seq}\nclips: {clips}\n  monotonic + whisper-once: {'PASS' if ok else 'FAIL'}")
    return ok


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default="http://localhost:8010")
    ap.add_argument("--gap", type=float, default=2.0)
    ap.add_argument("--concurrent", action="store_true")
    a = ap.parse_args()
    async with httpx.AsyncClient(base_url=a.base, timeout=10) as c:
        print((await c.get("/health")).json())
        scam = await replay(c, "digital_arrest", DIGITAL_ARREST, "+91 98765 43210", a.gap)
        ok = await replay(c, "delivery_driver", DELIVERY, "+91 99001 23456", a.gap)
        race_ok = await concurrent_legs(c, a.gap) if a.concurrent else True
    lat = sorted(latencies)
    print("\nRESULT:")
    print(f"  digital arrest reaches 3: {'PASS' if max(scam) == 3 else 'FAIL'}, never decreases: {'PASS' if scam == sorted(scam) else 'FAIL'}")
    print(f"  delivery driver stays <=1: {'PASS' if max(ok) <= 1 else 'FAIL'}")
    if a.concurrent:
        print(f"  concurrent legs: {'PASS' if race_ok else 'FAIL'}")
    print(f"  /classify latency over HTTP: p50 {statistics.median(lat):.0f} ms, p95 {lat[int(0.95 * (len(lat) - 1))]:.0f} ms, "
          f"max {lat[-1]:.0f} ms (n={len(lat)})")


if __name__ == "__main__":
    asyncio.run(main())

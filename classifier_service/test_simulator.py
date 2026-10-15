"""Replays two calls against a running service and prints the pressure escalation.

    uvicorn main:app --port 8000     (from classifier_service/)
    python test_simulator.py [base_url]
"""
import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

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


def replay(name: str, chunks: list, number: str) -> list[int]:
    call_id = f"sim-{name}-{int(time.time())}"
    c = httpx.Client(base_url=BASE, timeout=10)
    print(f"\n=== {name} ({call_id}) ===")
    out = []
    for i, (speaker, lang, text) in enumerate(chunks, 1):
        t0 = time.perf_counter()
        r = c.post("/classify", json=dict(call_id=call_id, caller_number=number, speaker=speaker, chunk_text=text, language=lang))
        ms = (time.perf_counter() - t0) * 1000
        r.raise_for_status()
        v = r.json()
        out.append(v["pressure"])
        print(f"[{i}] {speaker:6} {text[:70]!r}\n    pressure={v['pressure']} type={v['scam_type']} otp={v['asks_otp_or_pin']} "
              f"secret={v['demands_secrecy']} conf={v['confidence']:.2f} clip={v['recommended_whisper_clip']} ({ms:.0f} ms)\n    -> {v['summary_for_family']}")
    c.post(f"/reset/{call_id}")
    print("pressure: " + " -> ".join(map(str, out)))
    return out


if __name__ == "__main__":
    scam = replay("digital_arrest", DIGITAL_ARREST, "+91 98765 43210")
    ok = replay("delivery_driver", DELIVERY, "+91 99887 76655")
    print("\nRESULT:")
    print(f"  digital arrest reaches 3: {'PASS' if max(scam) == 3 else 'FAIL'}, never decreases: {'PASS' if scam == sorted(scam) else 'FAIL'}")
    print(f"  delivery driver stays <=0: {'PASS' if max(ok) == 0 else 'FAIL'}")

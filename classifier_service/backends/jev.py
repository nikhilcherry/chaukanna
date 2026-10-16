"""Jev (TypeSafe System One): typed, calibrated judgments instead of generated JSON.

One request carries four independent questions over the same state (the last few speaker-
tagged chunks): scam_type (choice), pressure (score over four described situations),
asks_otp (noul) and demands_secrecy (noul). Jev writes no text, so summary_for_family is a
template built from the typed answers. get_backend() wraps this in FallbackBackend(...,
Gemini, 1.5 s).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx

from backends.base import Backend, LLMContext
from schemas import LLMVerdict

log = logging.getLogger("classifier.jev")
URL = "https://api.typesafe.ai/v1/systemone"
# More than ~3 concurrent requests has got this key 403'd before: one cap for the whole process.
MAX_CONCURRENCY = int(os.getenv("JEV_MAX_CONCURRENCY", "3"))
_SEMS: dict[int, asyncio.Semaphore] = {}


def _sem() -> asyncio.Semaphore:
    """One semaphore per event loop (asyncio primitives can't cross loops; tests run several)."""
    loop = asyncio.get_running_loop()
    return _SEMS.setdefault(id(loop), asyncio.Semaphore(MAX_CONCURRENCY))
STATE_CHUNKS = int(os.getenv("JEV_STATE_CHUNKS", "8"))
FLAG_ON = float(os.getenv("JEV_FLAG_THRESHOLD", "0.65"))  # noul >= this -> true; below -> leave it to keywords

SCAM_TYPES = {
    "digital_arrest": "The caller claims to be police, CBI, ED, NCB, TRAI, RBI, customs, a court or a courier (FedEx/DHL) "
                      "and says the listener is linked to a crime (drugs or fake passports in a parcel, money laundering, "
                      "Aadhaar misuse), threatens arrest or 'digital arrest', or keeps them on a video call.",
    "kyc_update": "The caller says the listener's KYC, PAN, Aadhaar or SIM KYC is expired or not updated and the account "
                  "or SIM will be blocked, and asks them to install an app (AnyDesk, TeamViewer, an APK), click a link "
                  "or share details.",
    "bank_impersonation": "The caller pretends to be bank, card, UPI or insurance staff (suspicious transaction, card "
                          "blocked, reward points, limit increase) and asks for an OTP, CVV, PIN or UPI PIN, or to "
                          "approve a collect request.",
    "prize_lottery": "The caller says the listener won a lottery, KBC prize, lucky draw, gift or cashback and asks for a "
                     "fee, bank details or a PIN to receive it.",
    "other": "Clearly a scam of another kind: a relative or friend 'in trouble' needing money urgently (accident, police "
             "station, bail), electricity disconnection, investment or task scam, job offer, sextortion, tech support.",
    "none": "An ordinary call: family or friends, a delivery rider asking for the address, gate, floor or the parcel's "
            "delivery OTP, a real bank confirming a transaction that says it never asks for OTPs, a clinic, a real "
            "police verification visit, or people discussing the news.",
}
PRESSURE_LEVELS = [
    "An ordinary conversation: greetings, family talk, a delivery rider asking for directions, a bank confirming a "
    "transaction, people discussing the news.",
    "A stranger makes an unsolicited claim to be an official, police, bank or courier, or mentions a problem with "
    "the listener's account, parcel or documents, but has not threatened or demanded anything yet.",
    "The caller threatens the listener (arrest, legal case, account or SIM block, penalty), pressures them with "
    "authority or urgency, or orders them to stay on the line and follow instructions.",
    "The caller demands an OTP, PIN, CVV, a money transfer, a fee, an app install or screen share, or tells the "
    "listener to keep it secret and not tell family; or the listener is already complying (reading out a code, "
    "agreeing to pay, transfer or install).",
]
QUESTIONS = {
    "scam_type": {
        "type": "choice",
        "instructions": "This is a live phone call in India between a CALLER (unknown party) and the LISTENER (our user, "
                        "often elderly), transcribed by noisy speech-to-text and possibly code-mixed Hindi/Kannada/"
                        "English. Which kind of call is it, judging the whole transcript so far?",
        "criteria": SCAM_TYPES,
    },
    "pressure": {
        "type": "score",
        "instructions": "In this live phone call in India, how far has the CALLER gone in pressuring the LISTENER so far?",
        "criteria": PRESSURE_LEVELS,
    },
    "asks_otp": {
        "type": "noul",
        "instructions": "Has the CALLER asked the LISTENER to tell or share an OTP, PIN, UPI PIN, CVV, password, card "
                        "number or a code from an SMS? A caller warning the listener never to share their OTP is not asking.",
    },
    "secrecy": {
        "type": "noul",
        "instructions": "Has the CALLER told the LISTENER to keep this secret or confidential, not to tell family, the "
                        "bank or police, not to hang up or disconnect, or to stay alone on the call or on camera? A bank "
                        "saying 'do not share your OTP with anyone' does not count.",
    },
}

_TYPE_PHRASE = {
    "digital_arrest": "is posing as police/CBI/customs (digital-arrest script)", "kyc_update": "is running a KYC / account-block script",
    "bank_impersonation": "is posing as the bank", "prize_lottery": "is offering a fake prize/lottery", "other": "appears to be running a scam",
}


class JevBackend(Backend):
    name = "jev"

    def __init__(self) -> None:
        super().__init__()
        self.key = os.getenv("TYPESAFE_API_KEY", "")
        if not self.key:
            raise RuntimeError("TYPESAFE_API_KEY is not set")
        self.model = os.getenv("JEV_MODEL", "jev-latest")
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(float(os.getenv("JEV_TIMEOUT_S", "1.5")), connect=1.0))
        self.cooldown_until = 0.0
        self.backoff_s = 2.0
        self.last_raw: dict | None = None

    @staticmethod
    def state(ctx: LLMContext) -> dict:
        chunks = ctx.chunks[-STATE_CHUNKS:]
        return {
            "call": {"caller_number": ctx.caller_number or "unknown", "earlier_chunks_not_shown": max(0, len(ctx.chunks) - len(chunks)),
                     "earlier_assessment": ctx.earlier or None},
            "transcript": [{"speaker": "CALLER" if sp == "caller" else "LISTENER", "text": text} for sp, _, text in chunks],
        }

    async def classify(self, ctx: LLMContext) -> LLMVerdict:
        return self.to_verdict(await self.ask(ctx), ctx)

    async def ask(self, ctx: LLMContext) -> dict:
        """One request, four answers (raw TypeSafe answer dict)."""
        now = time.monotonic()
        if now < self.cooldown_until:
            raise RuntimeError(f"jev backing off for {self.cooldown_until - now:.1f}s after 403/429/529")
        body = {"model": self.model, "state": self.state(ctx), "questions": QUESTIONS}
        async with _sem():
            r = await self.client.post(URL, json=body, headers={"Authorization": f"Bearer {self.key}"})
        if r.status_code in (403, 429, 529):
            self.cooldown_until = time.monotonic() + self.backoff_s
            self.backoff_s = min(self.backoff_s * 2, 60.0)
            raise RuntimeError(f"jev HTTP {r.status_code}; backing off")
        r.raise_for_status()
        self.backoff_s = 2.0
        self.last_raw = r.json()["answers"]
        return self.last_raw

    @staticmethod
    def to_verdict(a: dict, ctx: LLMContext) -> LLMVerdict:
        st = a["scam_type"]
        stype = st["choice"]
        probs = st.get("probabilities", {})
        conf = float(probs.get(stype, st.get("confidence", 0.5)))
        # The pressure score measures how hard the caller pushes, and a mother asking for the rent
        # "demands a transfer" too. Composite: expected pressure x P(this is a scam at all).
        p_scam = 1.0 - float(probs.get("none", 0.0))
        score = float(a["pressure"]["score"]) * p_scam  # probability-weighted position 0..3
        pressure = max(0, min(3, int(score + 0.5)))
        p_otp, p_sec = float(a["asks_otp"]["noul"]), float(a["secrecy"]["noul"])
        otp, secrecy = p_otp >= FLAG_ON, p_sec >= FLAG_ON  # unsure (< threshold) -> false; keyword flags OR in later
        if pressure == 0:
            summary = "Ordinary call, nothing suspicious so far."
        else:
            parts = [x for x, on in (("asked for an OTP/PIN", otp), ("demanded secrecy", secrecy)) if on]
            summary = f"Caller {_TYPE_PHRASE.get(stype, 'sounds suspicious')}" + (": " + " and ".join(parts) if parts else "") + "."
        return LLMVerdict(scam_type=stype, pressure=pressure, asks_otp_or_pin=otp, demands_secrecy=secrecy,
                          confidence=round(min(max(conf, 0.0), 1.0), 3), language=ctx.language if ctx.language in ("hi", "kn", "en") else "en",
                          summary_for_family=summary)

    async def aclose(self) -> None:
        await self.client.aclose()
